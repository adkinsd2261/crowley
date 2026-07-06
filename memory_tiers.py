"""V3.9.17 #115–#116 — Memory tiers, promotion, and decay."""

from __future__ import annotations

import json
import sqlite3
from typing import Literal

import agent_identity

MemoryTier = Literal["ephemeral", "working", "canonical"]

MEMORY_TIERS: tuple[MemoryTier, ...] = ("ephemeral", "working", "canonical")
TIER_KEY = "memory_tier"
TIER_RANK: dict[str, int] = {"ephemeral": 0, "working": 1, "canonical": 2}
TIER_RETRIEVAL_BOOST: dict[str, float] = {
    "canonical": 0.25,
    "working": 0.10,
    "ephemeral": 0.0,
}
EPHEMERAL_TTL_HOURS = 72
DECAY_CONFIDENCE_STEP = 0.05
MIN_CONFIDENCE = 0.2


def normalize_tier(value: str | None, *, default: MemoryTier = "working") -> MemoryTier:
    if value and str(value).strip().lower() in MEMORY_TIERS:
        return str(value).strip().lower()  # type: ignore[return-value]
    return default


def infer_tier(
    *,
    memory_type: str,
    pinned: bool,
    source: str,
    write_action: str | None = None,
    is_canon: bool = False,
) -> MemoryTier:
    if pinned or is_canon:
        return "canonical"
    if memory_type in {"constraint", "decision"} and source in {"codex", "chatgpt", "manual"}:
        return "working"
    if write_action in {"note.ingest", "handoff.note"} or source == "implicit":
        return "ephemeral"
    return "working"


def tier_from_metadata_json(metadata_json: str | None) -> MemoryTier:
    if not metadata_json or not str(metadata_json).strip():
        return "working"
    try:
        meta = json.loads(metadata_json)
    except json.JSONDecodeError:
        return "working"
    if isinstance(meta, dict):
        return normalize_tier(str(meta.get(TIER_KEY, "working")))
    return "working"


def apply_tier_to_metadata(
    metadata: dict[str, object] | None,
    tier: MemoryTier,
) -> dict[str, object]:
    merged = dict(metadata or {})
    merged[TIER_KEY] = tier
    return merged


def retrieval_tier_boost(metadata_json: str | None, *, pinned: bool = False) -> float:
    if pinned:
        return TIER_RETRIEVAL_BOOST["canonical"]
    tier = tier_from_metadata_json(metadata_json)
    return TIER_RETRIEVAL_BOOST.get(tier, 0.0)


def promote_memory_tier(
    memory_id: int,
    *,
    agent_id: str,
    target_tier: MemoryTier = "canonical",
) -> dict[str, object]:
    allowed, message = agent_identity.check_domain_permission(
        agent_id, "memory.promote_canonical"
    )
    if not allowed:
        raise ValueError(message or "permission_denied")
    if target_tier != "canonical":
        raise ValueError("only promotion to canonical is supported")

    import crowley

    conn = crowley.connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (int(memory_id),),
        ).fetchone()
        if row is None:
            raise LookupError(f"memory not found: {memory_id}")
        meta_raw = str(row["metadata_json"] or "{}")
        try:
            meta = json.loads(meta_raw) if meta_raw.strip() else {}
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        current = tier_from_metadata_json(meta_raw)
        if TIER_RANK[current] >= TIER_RANK[target_tier]:
            return {
                "ok": True,
                "memory_id": int(memory_id),
                "tier": current,
                "promoted": False,
            }
        meta = apply_tier_to_metadata(meta, target_tier)
        meta["promoted_at"] = crowley._now_iso()
        meta["promoted_by"] = agent_identity.normalize_agent_id(agent_id)
        now = crowley._now_iso()
        conn.execute(
            """
            UPDATE memory_items
            SET metadata_json = ?, updated_at = ?, confidence = MAX(confidence, 0.9)
            WHERE id = ?
            """,
            (json.dumps(meta, sort_keys=True, ensure_ascii=False), now, int(memory_id)),
        )
        conn.commit()
        return {
            "ok": True,
            "memory_id": int(memory_id),
            "tier": target_tier,
            "promoted": True,
            "from_tier": current,
        }
    finally:
        conn.close()


def run_memory_decay(*, project_id: int | None = None, dry_run: bool = False) -> dict[str, object]:
    import crowley

    conn = crowley.connect_db()
    expired = 0
    decayed = 0
    try:
        if project_id is None:
            project_id = crowley._active_project_id(conn)
        clauses = ["status = 'active'"]
        params: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        rows = conn.execute(
            f"SELECT * FROM memory_items WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
        now = crowley._now_iso()
        for row in rows:
            tier = tier_from_metadata_json(
                str(row["metadata_json"]) if row["metadata_json"] else None
            )
            if tier == "ephemeral":
                created = str(row["created_at"])
                age_row = conn.execute(
                    "SELECT (julianday('now') - julianday(?)) * 24 AS hours",
                    (created,),
                ).fetchone()
                hours = float(age_row["hours"]) if age_row else 0.0
                if hours >= EPHEMERAL_TTL_HOURS:
                    expired += 1
                    if not dry_run:
                        conn.execute(
                            "UPDATE memory_items SET status = 'stale', updated_at = ? WHERE id = ?",
                            (now, int(row["id"])),
                        )
                continue
            if tier == "working":
                confidence = float(row["confidence"])
                access = int(row["access_count"] or 0)
                if access == 0 and confidence > MIN_CONFIDENCE:
                    decayed += 1
                    if not dry_run:
                        new_conf = max(MIN_CONFIDENCE, confidence - DECAY_CONFIDENCE_STEP)
                        conn.execute(
                            """
                            UPDATE memory_items
                            SET confidence = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (new_conf, now, int(row["id"])),
                        )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return {
        "ok": True,
        "expired_ephemeral": expired,
        "decayed_working": decayed,
        "dry_run": dry_run,
    }
