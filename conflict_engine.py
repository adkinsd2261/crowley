"""V3.9.17 #117–#118 — Conflict detection and deterministic resolution."""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

import agent_identity
import memory_tiers

ConflictStatus = Literal["open", "resolved"]

RESOLUTION_HIERARCHY: list[str] = [
    "filesystem",
    "tickets",
    "agent_activity",
    "memory_tier_canonical",
    "memory_tier_working",
    "memory_tier_ephemeral",
    "newer_timestamp",
    "human_approved_over_ai",
]


def ensure_conflicts_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_conflicts (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            project_id INTEGER,
            left_memory_id INTEGER NOT NULL,
            right_memory_id INTEGER NOT NULL,
            conflict_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            resolution_trace_json TEXT,
            resolved_at TEXT,
            winner_memory_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_conflicts_status
            ON memory_conflicts(status, created_at)
        """
    )


def _memory_score_for_resolution(row: sqlite3.Row) -> tuple[int, str, float, int]:
    import crowley

    tier = memory_tiers.tier_from_metadata_json(
        str(row["metadata_json"]) if row["metadata_json"] else None
    )
    tier_rank = memory_tiers.TIER_RANK.get(tier, 1)
    meta_raw = row["metadata_json"]
    agent = "system"
    if meta_raw:
        try:
            meta = json.loads(str(meta_raw))
            attr = meta.get("write_attribution") if isinstance(meta, dict) else None
            if isinstance(attr, dict):
                agent = str(attr.get("agent_id", row["source"]))
        except json.JSONDecodeError:
            agent = str(row["source"])
    human_boost = 1 if agent in {"mr_go", "manual", "codex"} else 0
    ts = str(row["created_at"])
    return (tier_rank, ts, float(row["confidence"]), human_boost)


def detect_memory_conflicts(
    *,
    project_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    import crowley

    conn = crowley.connect_db()
    try:
        ensure_conflicts_table(conn)
        if project_id is None:
            project_id = crowley._active_project_id(conn)
        params: list[object] = []
        where = "status = 'active'"
        if project_id is not None:
            where += " AND project_id = ?"
            params.append(project_id)
        rows = conn.execute(
            f"SELECT * FROM memory_items WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()
        by_type: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in rows:
            tokens = crowley._tokenize(str(row["content"]))[:3]
            topic = " ".join(tokens) if tokens else crowley._normalize_dedupe_key(str(row["content"]))[:40]
            key = (str(row["memory_type"]), topic)
            by_type.setdefault(key, []).append(row)

        conflicts: list[dict[str, object]] = []
        now = crowley._now_iso()
        for (_mem_type, _norm), group in by_type.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    left, right = group[i], group[j]
                    if str(left["content"]).strip() == str(right["content"]).strip():
                        continue
                    existing = conn.execute(
                        """
                        SELECT id FROM memory_conflicts
                        WHERE status = 'open'
                          AND ((left_memory_id = ? AND right_memory_id = ?)
                            OR (left_memory_id = ? AND right_memory_id = ?))
                        """,
                        (int(left["id"]), int(right["id"]), int(right["id"]), int(left["id"])),
                    ).fetchone()
                    if existing:
                        conflicts.append(
                            {
                                "id": int(existing["id"]),
                                "left_memory_id": int(left["id"]),
                                "right_memory_id": int(right["id"]),
                                "conflict_type": "contradictory_same_topic",
                                "status": "open",
                            }
                        )
                        continue
                    cur = conn.execute(
                        """
                        INSERT INTO memory_conflicts (
                            created_at, project_id, left_memory_id, right_memory_id,
                            conflict_type, status
                        ) VALUES (?, ?, ?, ?, ?, 'open')
                        """,
                        (now, project_id, int(left["id"]), int(right["id"]), "contradictory_same_topic"),
                    )
                    conflict_id = int(cur.lastrowid)
                    conflicts.append(
                        {
                            "id": conflict_id,
                            "left_memory_id": int(left["id"]),
                            "right_memory_id": int(right["id"]),
                            "conflict_type": "contradictory_same_topic",
                            "status": "open",
                        }
                    )
                    if len(conflicts) >= limit:
                        conn.commit()
                        return conflicts
        conn.commit()
        return conflicts
    finally:
        conn.close()


def resolve_memory_conflict(
    conflict_id: int,
    *,
    agent_id: str,
) -> dict[str, object]:
    allowed, message = agent_identity.check_domain_permission(agent_id, "memory.promote_canonical")
    if not allowed:
        raise ValueError(message or "permission_denied")

    import crowley

    conn = crowley.connect_db()
    try:
        ensure_conflicts_table(conn)
        conflict = conn.execute(
            "SELECT * FROM memory_conflicts WHERE id = ?",
            (int(conflict_id),),
        ).fetchone()
        if conflict is None:
            raise LookupError(f"conflict not found: {conflict_id}")
        if str(conflict["status"]) == "resolved":
            raise ValueError("conflict already resolved")

        left = conn.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (int(conflict["left_memory_id"]),),
        ).fetchone()
        right = conn.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (int(conflict["right_memory_id"]),),
        ).fetchone()
        if left is None or right is None:
            raise ValueError("conflict references missing memory")

        left_score = _memory_score_for_resolution(left)
        right_score = _memory_score_for_resolution(right)

        import memory_tiers
        import system_integrity

        left_tier = memory_tiers.tier_from_metadata_json(
            str(left["metadata_json"]) if left["metadata_json"] else None
        )
        right_tier = memory_tiers.tier_from_metadata_json(
            str(right["metadata_json"]) if right["metadata_json"] else None
        )
        allowed, reason = system_integrity.can_auto_resolve_conflict(
            float(left["confidence"]),
            float(right["confidence"]),
            left_tier=left_tier,
            right_tier=right_tier,
        )
        if not allowed:
            raise ValueError(reason)

        winner = left if left_score >= right_score else right
        loser = right if winner is left else left
        now = crowley._now_iso()
        trace = {
            "hierarchy": RESOLUTION_HIERARCHY,
            "left_score": {
                "tier_rank": left_score[0],
                "timestamp": left_score[1],
                "confidence": left_score[2],
                "human_boost": left_score[3],
            },
            "right_score": {
                "tier_rank": right_score[0],
                "timestamp": right_score[1],
                "confidence": right_score[2],
                "human_boost": right_score[3],
            },
            "winner_memory_id": int(winner["id"]),
            "loser_memory_id": int(loser["id"]),
            "resolved_by": agent_identity.normalize_agent_id(agent_id),
        }
        conn.execute(
            "UPDATE memory_items SET status = 'merged', updated_at = ? WHERE id = ?",
            (now, int(loser["id"])),
        )
        conn.execute(
            """
            UPDATE memory_conflicts
            SET status = 'resolved', resolved_at = ?, winner_memory_id = ?,
                resolution_trace_json = ?
            WHERE id = ?
            """,
            (
                now,
                int(winner["id"]),
                json.dumps(trace, sort_keys=True, ensure_ascii=False),
                int(conflict_id),
            ),
        )
        conn.commit()
        return {"ok": True, "conflict_id": int(conflict_id), "resolution": trace}
    finally:
        conn.close()


def list_memory_conflicts(*, status: str = "open", limit: int = 20) -> list[dict[str, object]]:
    import crowley

    conn = crowley.connect_db()
    try:
        ensure_conflicts_table(conn)
        rows = conn.execute(
            """
            SELECT * FROM memory_conflicts
            WHERE status = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (status, max(1, min(int(limit), 100))),
        ).fetchall()
        items = []
        for row in rows:
            item = crowley.row_to_dict(row)
            trace_raw = item.pop("resolution_trace_json", None)
            item["resolution_trace"] = (
                json.loads(str(trace_raw)) if trace_raw else None
            )
            items.append(item)
        return items
    finally:
        conn.close()
