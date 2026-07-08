#!/usr/bin/env python3
"""Read-only audit: ticket ID continuity, memory refs, handoff parity, visibility gaps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402
import handoff_ticket_bridge  # noqa: E402
import tickets  # noqa: E402

_TICKET_REF_RE = re.compile(r"(?:ticket\s*#|#)(\d{1,5})\b", re.IGNORECASE)


def _ticket_ids_in_db(project_id: int | None) -> list[int]:
    conn = crowley.connect_db()
    try:
        if project_id is None:
            rows = conn.execute("SELECT id FROM tickets ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM tickets WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
        return [int(row["id"]) for row in rows]
    finally:
        conn.close()


def _status_histogram(project_id: int | None) -> dict[str, int]:
    conn = crowley.connect_db()
    try:
        if project_id is None:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM tickets GROUP BY status"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM tickets WHERE project_id = ? GROUP BY status",
                (project_id,),
            ).fetchall()
        return {str(row["status"]): int(row["c"]) for row in rows}
    finally:
        conn.close()


def _linked_memory_coverage(project_id: int | None) -> dict[str, int]:
    conn = crowley.connect_db()
    try:
        clause = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (project_id,) if project_id is not None else ()
        total = conn.execute(f"SELECT COUNT(*) FROM tickets {clause}", params).fetchone()[0]
        linked = conn.execute(
            f"SELECT COUNT(*) FROM tickets {clause}"
            + (" AND" if clause else "WHERE")
            + " linked_memory_id IS NOT NULL",
            params,
        ).fetchone()[0]
        return {"total": int(total), "with_linked_memory_id": int(linked)}
    finally:
        conn.close()


def _memory_ticket_refs(project_id: int | None) -> dict[str, object]:
    conn = crowley.connect_db()
    try:
        clause = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (project_id,) if project_id is not None else ()
        rows = conn.execute(
            f"SELECT id, content, summary FROM memory_items {clause}",
            params,
        ).fetchall()
    finally:
        conn.close()

    ticket_ids = set(_ticket_ids_in_db(project_id))
    memory_ids = {int(row["id"]) for row in rows}
    refs: set[int] = set()
    for row in rows:
        for field in (row["content"] or "", row["summary"] or ""):
            for match in _TICKET_REF_RE.finditer(field):
                refs.add(int(match.group(1)))

    orphans: list[dict[str, object]] = []
    for ref in sorted(refs - ticket_ids):
        classification = (
            "false_positive_memory_id"
            if ref in memory_ids
            else "missing_ticket_row"
        )
        orphans.append({"ticket_ref": ref, "classification": classification})

    return {
        "distinct_refs": len(refs),
        "orphan_count": len(orphans),
        "orphans": orphans,
    }


def _anchor_ticket(project_id: int | None, *, oldest: bool) -> dict[str, object] | None:
    sort = "oldest" if oldest else "newest"
    status = "all"
    rows = tickets.list_tickets(
        project_id=project_id,
        status=status,
        open_only=False,
        limit=1,
        sort=sort,
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "id": int(row["id"]),
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def build_audit_report(*, parity_limit: int = 200) -> dict[str, object]:
    project = crowley.get_active_project()
    project_id = int(project["id"]) if project is not None else None
    project_payload = crowley.row_to_dict(project) if project is not None else None
    ids = _ticket_ids_in_db(project_id)
    gaps: list[int] = []
    if ids:
        id_set = set(ids)
        gaps = [i for i in range(ids[0], ids[-1] + 1) if i not in id_set]

    by_status = _status_histogram(project_id)
    open_count = tickets.count_tickets(project_id=project_id, open_only=True)
    total_count = tickets.count_tickets(project_id=project_id, status="all")

    parity = handoff_ticket_bridge.verify_handoff_ticket_parity(limit=parity_limit)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": project_payload,
        "ticket_storage": {
            "table": "tickets",
            "legacy_tables": [],
            "count": len(ids),
            "min_id": ids[0] if ids else None,
            "max_id": ids[-1] if ids else None,
            "gaps": gaps,
            "by_status": by_status,
            "linked_memory": _linked_memory_coverage(project_id),
        },
        "memory_refs": _memory_ticket_refs(project_id),
        "handoff_parity": parity,
        "visibility": {
            "ticket_list_default": "status=open (~{} rows)".format(open_count),
            "ticket_list_full_history": "status=all sort=oldest ({} rows)".format(total_count),
            "agent_sync_open_cap": "section_caps tickets_open (default 20)",
            "agent_sync_closed_cap": "section_caps tickets_closed (default 5)",
            "deep_sync_tickets_default": "scope=open (unchanged)",
            "deep_sync_full_history": "scope=history via agent.deep_sync",
            "conclusion": (
                "No ticket data loss detected — history filtered by default open-only views"
                if not gaps
                else "ID gaps detected — see gaps list"
            ),
        },
        "anchors": {
            "first": _anchor_ticket(project_id, oldest=True),
            "latest": _anchor_ticket(project_id, oldest=False),
        },
    }


def _markdown_report(data: dict[str, object]) -> str:
    storage = data.get("ticket_storage") or {}
    visibility = data.get("visibility") or {}
    lines = [
        "# Ticket Lineage Audit",
        "",
        f"Generated: {data.get('generated_at')}",
        "",
        "## Storage",
        "",
        f"- Count: {storage.get('count')}",
        f"- ID range: {storage.get('min_id')} – {storage.get('max_id')}",
        f"- Gaps: {len(storage.get('gaps') or [])}",
        f"- By status: {json.dumps(storage.get('by_status'), sort_keys=True)}",
        "",
        "## Visibility gap",
        "",
        f"- {visibility.get('conclusion')}",
        f"- Default list: {visibility.get('ticket_list_default')}",
        f"- Full history: {visibility.get('ticket_list_full_history')}",
        "",
        "## Memory orphan refs",
        "",
    ]
    mem = data.get("memory_refs") or {}
    lines.append(f"- Distinct refs: {mem.get('distinct_refs')}")
    lines.append(f"- Orphans: {mem.get('orphan_count')}")
    for orphan in mem.get("orphans") or []:
        if isinstance(orphan, dict):
            lines.append(f"  - #{orphan.get('ticket_ref')} ({orphan.get('classification')})")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ticket lineage (read-only)")
    parser.add_argument("--parity-limit", type=int, default=200)
    parser.add_argument("--out", type=str, default="", help="Write markdown report to path")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    report = build_audit_report(parity_limit=args.parity_limit)
    if args.json or not args.out:
        print(json.dumps(report, indent=2))
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_markdown_report(report), encoding="utf-8")
        if not args.json:
            print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
