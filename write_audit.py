"""V3.9.17 #114 — Append-only write audit log and rollback."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import agent_identity

AUDIT_ENTITY_TYPES = frozenset({"memory_item", "ticket", "handoff"})


def ensure_write_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS write_audit_log (
            id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            before_json TEXT,
            after_json TEXT,
            metadata_json TEXT,
            rolled_back_at TEXT,
            rollback_audit_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_write_audit_entity
            ON write_audit_log(entity_type, entity_id, created_at)
        """
    )


def _json_dumps(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _json_loads(raw: str | None) -> object | None:
    if not raw or not str(raw).strip():
        return None
    return json.loads(str(raw))


def record_write_audit(
    *,
    agent_id: str,
    action: str,
    entity_type: str,
    entity_id: int | None,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
    metadata: dict[str, object] | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    if entity_type not in AUDIT_ENTITY_TYPES:
        raise ValueError(f"invalid audit entity_type: {entity_type}")
    import crowley

    own_conn = conn is None
    if own_conn:
        conn = crowley.connect_db()
    try:
        ensure_write_audit_table(conn)
        now = crowley._now_iso()
        resolved_agent = agent_identity.normalize_agent_id(agent_id)
        cur = conn.execute(
            """
            INSERT INTO write_audit_log (
                created_at, agent_id, action, entity_type, entity_id,
                before_json, after_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                resolved_agent,
                action.strip(),
                entity_type,
                entity_id,
                _json_dumps(before),
                _json_dumps(after),
                _json_dumps(metadata),
            ),
        )
        audit_id = int(cur.lastrowid)
        if own_conn:
            conn.commit()
        return audit_id
    finally:
        if own_conn and conn is not None:
            conn.close()


def list_write_audit_log(
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict[str, object]], int]:
    import crowley

    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    clauses: list[str] = []
    params: list[object] = []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type.strip())
    if entity_id is not None:
        clauses.append("entity_id = ?")
        params.append(int(entity_id))
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    conn = crowley.connect_db()
    try:
        ensure_write_audit_table(conn)
        total = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM write_audit_log {where}",
                params,
            ).fetchone()["n"]
        )
        rows = conn.execute(
            f"""
            SELECT * FROM write_audit_log
            {where}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return [_audit_row_to_dict(row) for row in rows], total
    finally:
        conn.close()


def get_write_audit_entry(audit_id: int) -> dict[str, object] | None:
    import crowley

    conn = crowley.connect_db()
    try:
        ensure_write_audit_table(conn)
        row = conn.execute(
            "SELECT * FROM write_audit_log WHERE id = ?",
            (int(audit_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return _audit_row_to_dict(row)


def _audit_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    import crowley

    item = crowley.row_to_dict(row)
    item["before"] = _json_loads(str(item.pop("before_json", "") or "") or None)
    item["after"] = _json_loads(str(item.pop("after_json", "") or "") or None)
    meta_raw = item.pop("metadata_json", None)
    item["metadata"] = _json_loads(str(meta_raw) if meta_raw else None)
    item["rolled_back"] = bool(item.get("rolled_back_at"))
    return item


def rollback_write_audit(
    audit_id: int,
    *,
    agent_id: str,
) -> dict[str, object]:
    allowed, message = agent_identity.check_domain_permission(agent_id, "audit.rollback")
    if not allowed:
        raise ValueError(message or "permission_denied")

    import crowley

    conn = crowley.connect_db()
    try:
        ensure_write_audit_table(conn)
        row = conn.execute(
            "SELECT * FROM write_audit_log WHERE id = ?",
            (int(audit_id),),
        ).fetchone()
        if row is None:
            raise LookupError(f"audit entry not found: {audit_id}")
        if row["rolled_back_at"]:
            raise ValueError("audit entry already rolled back")

        entry = _audit_row_to_dict(row)
        entity_type = str(entry["entity_type"])
        entity_id = entry.get("entity_id")
        before = entry.get("before")
        after = entry.get("after")
        now = crowley._now_iso()
        resolved_agent = agent_identity.normalize_agent_id(agent_id)

        if entity_type == "memory_item":
            if entity_id is None:
                raise ValueError("memory_item audit missing entity_id")
            _rollback_memory_item(conn, int(entity_id), before, after, now=now)
        elif entity_type == "ticket":
            if entity_id is None:
                raise ValueError("ticket audit missing entity_id")
            _rollback_ticket(conn, int(entity_id), before, after, now=now)
        elif entity_type == "handoff":
            if entity_id is None:
                raise ValueError("handoff audit missing entity_id")
            _rollback_handoff(conn, int(entity_id), before, after, now=now)
        else:
            raise ValueError(f"rollback not supported for {entity_type}")

        rollback_id = record_write_audit(
            agent_id=resolved_agent,
            action="audit.rollback",
            entity_type=entity_type,
            entity_id=int(entity_id) if entity_id is not None else None,
            before=after if isinstance(after, dict) else None,
            after=before if isinstance(before, dict) else None,
            metadata={"rollback_of_audit_id": int(audit_id)},
            conn=conn,
        )
        conn.execute(
            """
            UPDATE write_audit_log
            SET rolled_back_at = ?, rollback_audit_id = ?
            WHERE id = ?
            """,
            (now, rollback_id, int(audit_id)),
        )
        conn.commit()
        return {
            "ok": True,
            "audit_id": int(audit_id),
            "rollback_audit_id": rollback_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
    finally:
        conn.close()


def _rollback_memory_item(
    conn: sqlite3.Connection,
    memory_id: int,
    before: object | None,
    after: object | None,
    *,
    now: str,
) -> None:
    import crowley

    row = conn.execute(
        "SELECT * FROM memory_items WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"memory_item not found: {memory_id}")

    if before is None:
        conn.execute(
            """
            UPDATE memory_items
            SET status = 'rolled_back', updated_at = ?
            WHERE id = ?
            """,
            (now, memory_id),
        )
        return

    if not isinstance(before, dict):
        raise ValueError("invalid before snapshot for memory_item rollback")
    conn.execute(
        """
        UPDATE memory_items SET
            memory_type = ?,
            content = ?,
            summary = ?,
            importance = ?,
            source = ?,
            pinned = ?,
            status = ?,
            confidence = ?,
            metadata_json = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            str(before.get("memory_type", row["memory_type"])),
            str(before.get("content", row["content"])),
            before.get("summary", row["summary"]),
            int(before.get("importance", row["importance"])),
            str(before.get("source", row["source"])),
            1 if before.get("pinned", row["pinned"]) else 0,
            str(before.get("status", row["status"])),
            float(before.get("confidence", row["confidence"])),
            _json_dumps(before.get("metadata"))
            if isinstance(before.get("metadata"), dict)
            else before.get("metadata_json", row["metadata_json"]),
            now,
            memory_id,
        ),
    )


def _rollback_ticket(
    conn: sqlite3.Connection,
    ticket_id: int,
    before: object | None,
    after: object | None,
    *,
    now: str,
) -> None:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise LookupError(f"ticket not found: {ticket_id}")

    if before is None:
        conn.execute(
            """
            UPDATE tickets
            SET status = 'cancelled', closed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, ticket_id),
        )
        return

    if not isinstance(before, dict):
        raise ValueError("invalid before snapshot for ticket rollback")
    conn.execute(
        """
        UPDATE tickets SET
            title = ?,
            description = ?,
            status = ?,
            assignee = ?,
            priority = ?,
            blocked_by_ticket_id = ?,
            linked_memory_id = ?,
            closed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            str(before.get("title", row["title"])),
            str(before.get("description", row["description"])),
            str(before.get("status", row["status"])),
            str(before.get("assignee", row["assignee"])),
            int(before.get("priority", row["priority"])),
            before.get("blocked_by_ticket_id", row["blocked_by_ticket_id"]),
            before.get("linked_memory_id", row["linked_memory_id"]),
            before.get("closed_at", row["closed_at"]),
            now,
            ticket_id,
        ),
    )


def _rollback_handoff(
    conn: sqlite3.Connection,
    memory_id: int,
    before: object | None,
    after: object | None,
    *,
    now: str,
) -> None:
    _rollback_memory_item(conn, memory_id, before, after, now=now)


def memory_row_snapshot(row: sqlite3.Row) -> dict[str, object]:
    import crowley

    item = crowley.row_to_dict(row)
    item.pop("embedding_blob", None)
    meta_raw = item.get("metadata_json")
    if isinstance(meta_raw, str) and meta_raw.strip():
        try:
            item["metadata"] = json.loads(meta_raw)
        except json.JSONDecodeError:
            pass
    return item


def ticket_row_snapshot(row: sqlite3.Row) -> dict[str, object]:
    import crowley

    return crowley.row_to_dict(row)
