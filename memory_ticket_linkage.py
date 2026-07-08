"""Bidirectional ticket ↔ memory linkage (V4 memory index)."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

import crowley

LINKED_TICKET_IDS_COLUMN = "linked_ticket_ids_json"
_HANDOFF_SOURCES = frozenset({"cursor", "codex", "crowley", "chatgpt", "mr_go"})
_BARE_TICKET_HASH_RE = re.compile(r"(?<!\w)#(\d+)\b")
_MEMORY_TYPE_GROUPS: dict[str, str] = {
    "decision": "decisions",
    "lesson": "lessons",
    "qa_result": "qa_results",
    "project_update": "updates",
    "constraint": "constraints",
    "preference": "preferences",
    "summary": "summaries",
    "event": "events",
    "note": "notes",
}


def ensure_linkage_column(conn: sqlite3.Connection) -> None:
    """Add linked_ticket_ids_json to memory_items when missing."""
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()
    }
    if LINKED_TICKET_IDS_COLUMN not in cols:
        conn.execute(
            f"ALTER TABLE memory_items ADD COLUMN {LINKED_TICKET_IDS_COLUMN} TEXT"
        )


def _parse_json_ticket_ids(raw: object | None) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        items = parsed
    ordered: list[int] = []
    seen: set[int] = set()
    for item in items:
        try:
            ticket_id = int(item)
        except (TypeError, ValueError):
            continue
        if ticket_id not in seen:
            seen.add(ticket_id)
            ordered.append(ticket_id)
    return ordered


def stored_linked_ticket_ids(row: sqlite3.Row | dict[str, Any]) -> list[int]:
    if isinstance(row, dict):
        raw = row.get(LINKED_TICKET_IDS_COLUMN)
    elif LINKED_TICKET_IDS_COLUMN in row.keys():
        raw = row[LINKED_TICKET_IDS_COLUMN]
    else:
        raw = None
    return _parse_json_ticket_ids(raw)


def max_ticket_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(id) AS m FROM tickets").fetchone()
    if row is None or row["m"] is None:
        return 0
    return int(row["m"])


def valid_ticket_ids(conn: sqlite3.Connection, ticket_ids: list[int]) -> list[int]:
    if not ticket_ids:
        return []
    marks = ",".join("?" for _ in ticket_ids)
    rows = conn.execute(
        f"SELECT id FROM tickets WHERE id IN ({marks}) ORDER BY id ASC",
        ticket_ids,
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _metadata_ticket_ids(metadata: dict[str, object] | None) -> list[int]:
    if not metadata:
        return []
    ordered: list[int] = []
    seen: set[int] = set()
    for key in ("closed_work_ticket_id", "work_ticket_id", "ticket_id"):
        raw = metadata.get(key)
        if raw is None:
            continue
        try:
            ticket_id = int(raw)
        except (TypeError, ValueError):
            continue
        if ticket_id not in seen:
            seen.add(ticket_id)
            ordered.append(ticket_id)
    return ordered


def infer_ticket_ids_from_memory(
    row: sqlite3.Row | dict[str, Any],
    *,
    conn: sqlite3.Connection | None = None,
    max_id: int | None = None,
) -> list[int]:
    """Infer ticket ids from persisted links, reverse handoff link, metadata, and text."""
    local_conn = conn
    owned = False
    if local_conn is None:
        local_conn = crowley.connect_db()
        owned = True
    try:
        if max_id is None:
            max_id = max_ticket_id(local_conn)
        memory_id = int(row["id"] if not isinstance(row, dict) else row["id"])
        ordered: list[int] = []
        seen: set[int] = set()

        def _add(ticket_id: int) -> None:
            if ticket_id < 1 or ticket_id > max_id:
                return
            if ticket_id not in seen:
                seen.add(ticket_id)
                ordered.append(ticket_id)

        for ticket_id in stored_linked_ticket_ids(row):
            _add(ticket_id)

        reverse_rows = local_conn.execute(
            "SELECT id FROM tickets WHERE linked_memory_id = ? ORDER BY id ASC",
            (memory_id,),
        ).fetchall()
        for reverse in reverse_rows:
            _add(int(reverse["id"]))

        content = str(row["content"] if not isinstance(row, dict) else row["content"])
        summary = row["summary"] if not isinstance(row, dict) else row.get("summary")
        metadata_raw = (
            row["metadata_json"]
            if not isinstance(row, dict) and "metadata_json" in row.keys()
            else row.get("metadata_json") if isinstance(row, dict) else None
        )
        metadata: dict[str, object] | None = None
        if metadata_raw:
            try:
                parsed = json.loads(str(metadata_raw))
                if isinstance(parsed, dict):
                    metadata = parsed
            except json.JSONDecodeError:
                metadata = None

        import handoff_ticket_bridge

        for ticket_id in handoff_ticket_bridge.extract_referenced_ticket_ids(
            content, metadata=metadata
        ):
            _add(ticket_id)
        for ticket_id in _metadata_ticket_ids(metadata):
            _add(ticket_id)

        text = f"{content} {summary or ''}"
        for match in _BARE_TICKET_HASH_RE.finditer(text):
            _add(int(match.group(1)))

        return valid_ticket_ids(local_conn, ordered)
    finally:
        if owned:
            local_conn.close()


def merge_ticket_id_lists(*lists: list[int]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for items in lists:
        for ticket_id in items:
            if ticket_id not in seen:
                seen.add(ticket_id)
                ordered.append(ticket_id)
    return ordered


def persist_memory_ticket_links(
    conn: sqlite3.Connection,
    memory_id: int,
    ticket_ids: list[int],
    *,
    merge: bool = True,
) -> list[int]:
    """Persist linked ticket ids on a memory row; returns final list."""
    ensure_linkage_column(conn)
    ticket_ids = valid_ticket_ids(conn, ticket_ids)
    if merge:
        row = conn.execute(
            f"SELECT {LINKED_TICKET_IDS_COLUMN} FROM memory_items WHERE id = ?",
            (memory_id,),
        ).fetchone()
        existing = _parse_json_ticket_ids(
            row[LINKED_TICKET_IDS_COLUMN] if row is not None else None
        )
        ticket_ids = merge_ticket_id_lists(existing, ticket_ids)
    payload = json.dumps(ticket_ids)
    now = crowley._now_iso()
    conn.execute(
        f"""
        UPDATE memory_items
        SET {LINKED_TICKET_IDS_COLUMN} = ?, updated_at = ?
        WHERE id = ?
        """,
        (payload, now, memory_id),
    )
    return ticket_ids


def add_memory_ticket_link(memory_id: int, ticket_id: int) -> list[int]:
    conn = crowley.connect_db()
    try:
        ensure_linkage_column(conn)
        links = persist_memory_ticket_links(conn, memory_id, [ticket_id], merge=True)
        conn.commit()
        return links
    finally:
        conn.close()


def sync_handoff_memory_links(
    memory_id: int,
    content: str,
    *,
    metadata: dict[str, object] | None = None,
    ticket_ids: list[int] | None = None,
) -> list[int]:
    """After handoff ingest, persist memory → ticket links."""
    conn = crowley.connect_db()
    try:
        ensure_linkage_column(conn)
        row = crowley._load_active_memory_item(conn, memory_id)
        if row is None:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return []
        inferred = infer_ticket_ids_from_memory(row, conn=conn)
        merged = merge_ticket_id_lists(ticket_ids or [], inferred)
        links = persist_memory_ticket_links(conn, memory_id, merged, merge=True)
        conn.commit()
        return links
    finally:
        conn.close()


def batch_linked_ticket_ids(
    memory_ids: list[int],
    *,
    conn: sqlite3.Connection | None = None,
) -> dict[int, list[int]]:
    """Merged memory → ticket ids (persisted + reverse handoff link)."""
    if not memory_ids:
        return {}
    local_conn = conn
    owned = False
    if local_conn is None:
        local_conn = crowley.connect_db()
        owned = True
    try:
        ensure_linkage_column(local_conn)
        marks = ",".join("?" for _ in memory_ids)
        rows = local_conn.execute(
            f"""
            SELECT id, {LINKED_TICKET_IDS_COLUMN}
            FROM memory_items
            WHERE id IN ({marks})
            """,
            memory_ids,
        ).fetchall()
        linked: dict[int, list[int]] = {
            int(row["id"]): stored_linked_ticket_ids(row) for row in rows
        }
        reverse_rows = local_conn.execute(
            f"""
            SELECT id, linked_memory_id
            FROM tickets
            WHERE linked_memory_id IN ({marks})
            ORDER BY id ASC
            """,
            memory_ids,
        ).fetchall()
        for row in reverse_rows:
            mem_id = int(row["linked_memory_id"])
            ticket_id = int(row["id"])
            linked.setdefault(mem_id, [])
            if ticket_id not in linked[mem_id]:
                linked[mem_id].append(ticket_id)
        for mem_id in memory_ids:
            linked.setdefault(int(mem_id), [])
        return linked
    finally:
        if owned:
            local_conn.close()


def _memory_brief(row: sqlite3.Row) -> dict[str, object]:
    payload = crowley._memory_item_api_dict(row)
    payload["summary"] = crowley._handoff_summary_line(str(row["content"]))
    if len(str(payload.get("content") or "")) > 280:
        payload["content"] = crowley._truncate(str(payload["content"]), 280)
    return payload


def list_memories_for_ticket(
    ticket_id: int,
    *,
    limit: int = 50,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, object]]:
    """Memories explicitly linked to a ticket (persisted or canonical handoff)."""
    limit = max(1, min(int(limit), 200))
    local_conn = conn
    owned = False
    if local_conn is None:
        local_conn = crowley.connect_db()
        owned = True
    try:
        ensure_linkage_column(local_conn)
        rows = local_conn.execute(
            f"""
            SELECT m.*
            FROM memory_items m
            WHERE m.status = 'active'
              AND (
                m.id = (SELECT linked_memory_id FROM tickets WHERE id = ?)
                OR (
                  m.{LINKED_TICKET_IDS_COLUMN} IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM json_each(m.{LINKED_TICKET_IDS_COLUMN}) je
                    WHERE je.value = ?
                  )
                )
              )
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (ticket_id, ticket_id, limit),
        ).fetchall()
        return [_memory_brief(row) for row in rows]
    finally:
        if owned:
            local_conn.close()


def group_memories_by_type(
    memories: list[dict[str, object]],
) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for item in memories:
        memory_type = str(item.get("memory_type") or "other")
        bucket = _MEMORY_TYPE_GROUPS.get(memory_type, "other")
        grouped.setdefault(bucket, []).append(item)
    return grouped


def ticket_memory_context(
    ticket_id: int,
    *,
    memory_limit: int = 50,
) -> dict[str, object]:
    """Ticket-centric memory bundle for ticket.get / planning.ticket."""
    memories = list_memories_for_ticket(ticket_id, limit=memory_limit)
    handoffs = [
        item
        for item in memories
        if str(item.get("source", "")).lower() in _HANDOFF_SOURCES
        or str(item.get("memory_type")) in {"project_update", "event"}
    ]
    return {
        "total": len(memories),
        "by_type": group_memories_by_type(memories),
        "handoffs": handoffs,
        "items": memories,
    }


def backfill_memory_ticket_links(
    *,
    dry_run: bool = True,
    limit: int | None = None,
) -> dict[str, object]:
    """Infer and persist memory → ticket links for all memory_items."""
    conn = crowley.connect_db()
    try:
        ensure_linkage_column(conn)
        max_id = max_ticket_id(conn)
        query = "SELECT * FROM memory_items ORDER BY id ASC"
        params: list[object] = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(max(1, int(limit)))
        rows = conn.execute(query, params).fetchall()
        updated = 0
        unchanged = 0
        samples: list[dict[str, object]] = []
        for row in rows:
            memory_id = int(row["id"])
            before = stored_linked_ticket_ids(row)
            inferred = infer_ticket_ids_from_memory(row, conn=conn, max_id=max_id)
            if before == inferred:
                unchanged += 1
                continue
            updated += 1
            if len(samples) < 10:
                samples.append(
                    {
                        "memory_id": memory_id,
                        "before": before,
                        "after": inferred,
                    }
                )
            if not dry_run:
                persist_memory_ticket_links(conn, memory_id, inferred, merge=False)
        if not dry_run:
            conn.commit()
        return {
            "dry_run": dry_run,
            "scanned": len(rows),
            "updated": updated,
            "unchanged": unchanged,
            "max_ticket_id": max_id,
            "samples": samples,
        }
    finally:
        conn.close()


def audit_memory_ticket_linkage(
    *,
    project_id: int | None = None,
) -> dict[str, object]:
    """Linkage coverage report (% mapped, orphans, per-ticket gaps)."""
    conn = crowley.connect_db()
    try:
        ensure_linkage_column(conn)
        max_id = max_ticket_id(conn)
        clauses = ["1=1"]
        params: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)

        rows = conn.execute(
            f"SELECT * FROM memory_items WHERE {' AND '.join(clauses)}",
            params,
        ).fetchall()
        total = len(rows)
        mapped = 0
        high_signal_unmapped: list[int] = []
        high_signal_types = {
            "decision",
            "lesson",
            "qa_result",
            "project_update",
            "constraint",
        }
        orphan_refs: list[dict[str, object]] = []
        agent_handoffs_total = 0
        agent_handoffs_unlinked = 0

        ticket_memory_counts: dict[int, int] = {}
        reverse_by_memory = batch_linked_ticket_ids(
            [int(row["id"]) for row in rows], conn=conn
        )

        for row in rows:
            memory_id = int(row["id"])
            links = reverse_by_memory.get(memory_id, [])
            if not links:
                links = infer_ticket_ids_from_memory(row, conn=conn, max_id=max_id)
            if links:
                mapped += 1
                for ticket_id in links:
                    ticket_memory_counts[ticket_id] = ticket_memory_counts.get(ticket_id, 0) + 1
            memory_type = str(row["memory_type"])
            source = str(row["source"]).lower()
            if memory_type in high_signal_types and not links:
                high_signal_unmapped.append(memory_id)
            if source in _HANDOFF_SOURCES and memory_type in {"project_update", "event"}:
                agent_handoffs_total += 1
                if not links:
                    agent_handoffs_unlinked += 1

            content = f"{row['content']} {row['summary'] or ''}"
            for match in _BARE_TICKET_HASH_RE.finditer(content):
                ref_id = int(match.group(1))
                if ref_id > max_id:
                    orphan_refs.append(
                        {"memory_id": memory_id, "ref": ref_id, "kind": "above_max_ticket"}
                    )

        ticket_rows = conn.execute("SELECT id, linked_memory_id FROM tickets").fetchall()
        tickets_total = len(ticket_rows)
        tickets_with_memory = sum(
            1 for row in ticket_rows if row["linked_memory_id"] is not None
        )
        tickets_with_context = sum(
            1 for row in ticket_rows if ticket_memory_counts.get(int(row["id"]), 0) > 0
        )
        tickets_without_context = [
            int(row["id"])
            for row in ticket_rows
            if ticket_memory_counts.get(int(row["id"]), 0) == 0
        ]

        mapped_pct = round((mapped / total) * 100, 2) if total else 100.0
        return {
            "memory_items_total": total,
            "memory_items_mapped": mapped,
            "memory_items_mapped_pct": mapped_pct,
            "memory_items_unmapped": total - mapped,
            "high_signal_unmapped_count": len(high_signal_unmapped),
            "high_signal_unmapped_sample": high_signal_unmapped[:20],
            "agent_handoffs_total": agent_handoffs_total,
            "agent_handoffs_unlinked": agent_handoffs_unlinked,
            "orphan_ticket_refs": orphan_refs[:30],
            "orphan_ticket_ref_count": len(orphan_refs),
            "tickets_total": tickets_total,
            "tickets_with_linked_handoff": tickets_with_memory,
            "tickets_with_memory_context": tickets_with_context,
            "tickets_without_memory_context_count": len(tickets_without_context),
            "tickets_without_memory_context_sample": tickets_without_context[:25],
            "max_ticket_id": max_id,
        }
    finally:
        conn.close()
