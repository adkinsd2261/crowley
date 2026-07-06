"""V3.9.17+ #131 — Persist completed handoffs as durable tickets (idempotent bridge)."""

from __future__ import annotations

import re
from typing import Any

import crowley
import tickets

HANDOFF_PERSIST_TYPES = frozenset({"builder_handoff", "architect_handoff"})
_SECTION_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _section_text(content: str, heading: str) -> str:
    text = crowley._memory_gate_section_text(content, heading)
    return text.strip() if text else ""


def _first_summary_bullet(content: str) -> str:
    section = _section_text(content, "Summary")
    if not section:
        return ""
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            return stripped[2:].strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return section.splitlines()[0].strip() if section else ""


def parse_handoff_ticket_fields(content: str) -> dict[str, str]:
    """Extract ticket title, description, QA, and file hints from handoff markdown."""
    summary = _section_text(content, "Summary")
    context = _section_text(content, "Context Basis")
    build = _section_text(content, "Build Complete")
    qa = _section_text(content, "QA Results")
    files = _section_text(content, "Files Changed")
    next_action = _section_text(content, "Next Action")

    title = _first_summary_bullet(content) or "Handoff record"
    if len(title) > 120:
        title = crowley._truncate(title, 117)

    description_parts: list[str] = []
    if summary:
        description_parts.append(f"## Summary\n\n{summary}")
    if context:
        description_parts.append(f"## Context Basis\n\n{context}")
    if build:
        description_parts.append(f"## Build Complete\n\n{build}")
    if files:
        description_parts.append(f"## Files / commits\n\n{files}")
    if next_action:
        description_parts.append(f"## Next Action\n\n{next_action}")

    description = "\n\n".join(description_parts).strip()
    if not description:
        description = crowley._truncate(content.strip(), 4000)

    return {
        "title": title,
        "description": description,
        "qa_summary": qa,
        "files_section": files,
    }


def get_ticket_for_handoff_memory(memory_id: int) -> dict[str, object] | None:
    """Return existing ticket linked to handoff memory_id, if any."""
    conn = crowley.connect_db()
    try:
        row = conn.execute(
            """
            SELECT * FROM tickets
            WHERE linked_memory_id = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (int(memory_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return tickets._ticket_row_to_dict(row)


def persist_handoff_as_ticket(
    memory_id: int,
    content: str,
    *,
    source: str,
    handoff_type: str,
    project_id: int | None = None,
    closed_work_ticket_id: int | None = None,
) -> dict[str, object]:
    """
    Create a done ticket for a completed handoff. Idempotent per memory_id.
    """
    if handoff_type not in HANDOFF_PERSIST_TYPES:
        return {"skipped": True, "reason": f"handoff type {handoff_type} not persisted"}

    existing = get_ticket_for_handoff_memory(memory_id)
    if existing is not None:
        return {
            "created": False,
            "idempotent": True,
            "ticket": existing,
            "memory_item_id": memory_id,
        }

    fields = parse_handoff_ticket_fields(content)
    description = fields["description"]
    if fields["qa_summary"]:
        description = f"{description}\n\n## QA Results\n\n{fields['qa_summary']}".strip()
    provenance = (
        f"Provenance: handoff memory #{memory_id} "
        f"({handoff_type}, source={source})"
    )
    if closed_work_ticket_id is not None:
        provenance += f"; closed work ticket #{closed_work_ticket_id}"
    description = f"{description}\n\n{provenance}".strip()

    assignee = source.strip().lower()
    if assignee not in tickets.TICKET_ASSIGNEES:
        assignee = "unassigned"

    result = tickets.create_ticket(
        fields["title"],
        description=description,
        assignee=assignee,
        priority=3,
        source=source if source in tickets.TICKET_SOURCES else "system",
        actor="system",
        project_id=project_id,
        linked_memory_id=int(memory_id),
        status="done",
    )
    ticket_id = int(result["ticket"]["id"])
    tickets.append_ticket_event(
        ticket_id,
        "handoff_linked",
        "system",
        {
            "memory_item_id": memory_id,
            "handoff_type": handoff_type,
            "provenance": f"handoff #{memory_id}",
            "closed_work_ticket_id": closed_work_ticket_id,
        },
    )
    return {
        "created": True,
        "idempotent": False,
        "ticket": result["ticket"],
        "memory_item_id": memory_id,
        "event_id": result.get("event_id"),
    }


def backfill_handoff_tickets(*, limit: int = 50) -> dict[str, object]:
    """Ingest recent handoffs missing linked tickets."""
    limit = max(1, min(int(limit), 200))
    rows = crowley.list_recent_agent_events(limit=limit * 2)
    created = 0
    skipped = 0
    results: list[dict[str, object]] = []

    for row in rows:
        if len(results) >= limit:
            break
        item = crowley._memory_item_api_dict(row)
        mem_id = item.get("id")
        if mem_id is None:
            continue
        memory_id = int(mem_id)
        if get_ticket_for_handoff_memory(memory_id) is not None:
            skipped += 1
            continue
        display = str(item.get("display", ""))
        body = str(item.get("body", "") or item.get("content", "") or display)
        if "handoff" not in display.lower() and "handoff" not in body.lower():
            if str(item.get("memory_type", "")) not in {"project_update", "summary"}:
                continue
        handoff_type = "builder_handoff"
        if "architect" in display.lower() or "architect_handoff" in body:
            handoff_type = "architect_handoff"
        elif "builder_handoff" not in body and "builder" not in display.lower():
            continue
        source = str(item.get("source", "cursor") or "cursor")
        project_id = item.get("project_id")
        bridge = persist_handoff_as_ticket(
            memory_id,
            body,
            source=source,
            handoff_type=handoff_type,
            project_id=int(project_id) if project_id is not None else None,
        )
        if bridge.get("created"):
            created += 1
        results.append(bridge)

    return {
        "scanned": len(results),
        "created": created,
        "skipped_existing": skipped,
        "results": results,
    }
