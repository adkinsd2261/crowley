"""Agent sync limit enforcement, Adaptive Sync Envelope (ASE), and deep sync pagination."""

from __future__ import annotations

import base64
import json
from typing import Any, Callable

MAX_PAYLOAD_BYTES = 180 * 1024
ASE_ENVELOPE_VERSION = "ase_v1"
AGENT_SYNC_LIMIT_MAX = 50

DEEP_SYNC_SECTIONS = frozenset({
    "handoffs",
    "tickets",
    "memory",
    "decisions",
    "constraints",
    "events",
})


def normalize_agent_sync_limit(limit: object, *, default: int = 20) -> int:
    try:
        parsed = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, AGENT_SYNC_LIMIT_MAX))


def section_caps(sync_limit: int) -> dict[str, int]:
    """Derive per-section list caps from the caller limit (#231)."""
    sync_limit = normalize_agent_sync_limit(sync_limit)
    return {
        "handoffs": min(sync_limit, 10),
        "tickets_open": min(sync_limit, 20),
        "tickets_closed": min(sync_limit, 5),
        "events_other": min(sync_limit, 5),
        "events_own": min(sync_limit, 3),
        "decisions": min(sync_limit, 5),
        "constraints": min(sync_limit, 5),
        "memories": min(sync_limit, 4),
        "activity_wire": min(sync_limit, 5),
        "task_frame_working": min(sync_limit, 6),
    }


def payload_bytes(bundle: dict[str, Any]) -> int:
    return len(json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _clip_summary(value: object, *, max_len: int = 200) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def compress_sync_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = item.get("id")
    if item_id is None:
        item_id = item.get("memory_id")
    summary = (
        item.get("summary")
        or item.get("display")
        or item.get("content")
        or item.get("title")
        or ""
    )
    timestamp = item.get("created_at") or item.get("timestamp") or item.get("updated_at")
    compressed: dict[str, Any] = {
        "id": item_id,
        "summary": _clip_summary(summary),
        "timestamp": timestamp,
    }
    source = item.get("source")
    if source:
        compressed["source"] = source
    return compressed


def compress_ticket_item(ticket: dict[str, Any]) -> dict[str, Any]:
    description = str(ticket.get("description") or "")
    summary = description.splitlines()[0] if description else str(ticket.get("title") or "")
    return {
        "id": ticket.get("id"),
        "summary": _clip_summary(summary or ticket.get("title")),
        "timestamp": ticket.get("updated_at") or ticket.get("created_at"),
        "status": ticket.get("status"),
        "assignee": ticket.get("assignee"),
        "title": ticket.get("title"),
    }


def _compress_handoffs(bundle: dict[str, Any]) -> None:
    handoffs = bundle.get("recent_handoffs")
    if not isinstance(handoffs, dict):
        return
    items = handoffs.get("items")
    if isinstance(items, list):
        handoffs["items"] = [compress_sync_item(item) for item in items if isinstance(item, dict)]


def _compress_events(bundle: dict[str, Any], key: str) -> None:
    items = bundle.get(key)
    if isinstance(items, list):
        bundle[key] = [compress_sync_item(item) for item in items if isinstance(item, dict)]


def _compress_memories(bundle: dict[str, Any], key: str) -> None:
    items = bundle.get(key)
    if isinstance(items, list):
        compressed: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = compress_sync_item(item)
            reason = item.get("inclusion_reason")
            if reason:
                row["inclusion_reason"] = _clip_summary(reason, max_len=120)
            compressed.append(row)
        bundle[key] = compressed


def _compress_tickets(bundle: dict[str, Any]) -> None:
    tickets = bundle.get("tickets")
    if not isinstance(tickets, dict):
        return
    for key in ("open", "assigned_to_agent", "blocked", "recently_closed"):
        rows = tickets.get(key)
        if isinstance(rows, list):
            tickets[key] = [compress_ticket_item(row) for row in rows if isinstance(row, dict)]
    grouped = tickets.get("grouped_open")
    if isinstance(grouped, list):
        tickets["grouped_open"] = [
            {
                **group,
                "tickets": [
                    compress_ticket_item(row)
                    for row in (group.get("tickets") or [])
                    if isinstance(row, dict)
                ],
            }
            if isinstance(group, dict)
            else group
            for group in grouped
        ]


def _trim_list(bundle: dict[str, Any], key: str) -> bool:
    items = bundle.get(key)
    if not isinstance(items, list) or len(items) <= 1:
        return False
    bundle[key] = items[: max(1, len(items) // 2)]
    return True


def _trim_handoffs(bundle: dict[str, Any]) -> bool:
    handoffs = bundle.get("recent_handoffs")
    if not isinstance(handoffs, dict):
        return False
    items = handoffs.get("items")
    if not isinstance(items, list) or len(items) <= 1:
        return False
    handoffs["items"] = items[: max(1, len(items) // 2)]
    handoffs["total"] = len(handoffs["items"])
    return True


def _trim_tickets(bundle: dict[str, Any]) -> bool:
    tickets = bundle.get("tickets")
    if not isinstance(tickets, dict):
        return False
    trimmed = False
    for key in ("open", "assigned_to_agent", "blocked", "recently_closed", "grouped_open"):
        rows = tickets.get(key)
        if isinstance(rows, list) and len(rows) > 1:
            tickets[key] = rows[: max(1, len(rows) // 2)]
            trimmed = True
    return trimmed


def _trim_memory(bundle: dict[str, Any]) -> bool:
    trimmed = False
    for key in (
        "relevant_memories",
        "supporting_memories",
        "constraint_memories",
        "recent_decisions",
        "events_from_other_agents",
        "events_from_this_agent",
    ):
        if _trim_list(bundle, key):
            trimmed = True
    task_frame = bundle.get("task_frame")
    if isinstance(task_frame, dict):
        for key in ("working_on", "blockers"):
            if _trim_list(task_frame, key):
                trimmed = True
        guardrails = task_frame.get("guardrails")
        if isinstance(guardrails, dict):
            for key in ("recent_decisions", "constraint_memories"):
                if _trim_list(guardrails, key):
                    trimmed = True
    return trimmed


def apply_adaptive_sync_envelope(
    bundle: dict[str, Any],
    *,
    max_bytes: int = MAX_PAYLOAD_BYTES,
) -> dict[str, Any]:
    """Byte-bounded ASE fill with handoffs > tickets > memory priority (#229)."""
    out: dict[str, Any] = dict(bundle)
    _compress_handoffs(out)
    _compress_tickets(out)
    _compress_events(out, "events_from_other_agents")
    _compress_events(out, "events_from_this_agent")
    _compress_memories(out, "relevant_memories")
    _compress_memories(out, "supporting_memories")
    _compress_memories(out, "constraint_memories")
    _compress_memories(out, "recent_decisions")

    truncated = {"handoffs": False, "tickets": False, "memory": False}
    trimmers: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("memory", _trim_memory),
        ("tickets", _trim_tickets),
        ("handoffs", _trim_handoffs),
    ]
    guard = 0
    while payload_bytes(out) > max_bytes and guard < 24:
        guard += 1
        trimmed_any = False
        for name, trimmer in trimmers:
            if trimmer(out):
                truncated[name] = True
                trimmed_any = True
                break
        if not trimmed_any:
            break

    sync_meta = out.get("sync_meta")
    if not isinstance(sync_meta, dict):
        sync_meta = {}
        out["sync_meta"] = sync_meta
    sync_meta.update(
        {
            "envelope": ASE_ENVELOPE_VERSION,
            "payload_bytes": payload_bytes(out),
            "max_payload_bytes": max_bytes,
            "truncated": truncated,
        }
    )
    out["bundle_shape"] = ASE_ENVELOPE_VERSION
    return out


def encode_deep_sync_cursor(section: str, offset: int) -> str:
    payload = json.dumps(
        {"section": section, "offset": max(0, int(offset))},
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_deep_sync_cursor(cursor: str | None) -> tuple[str, int]:
    if not cursor or not str(cursor).strip():
        return "", 0
    try:
        raw = base64.urlsafe_b64decode(str(cursor).encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("invalid deep_sync cursor") from None
    if not isinstance(data, dict):
        raise ValueError("invalid deep_sync cursor")
    section = str(data.get("section") or "").strip().lower()
    if section not in DEEP_SYNC_SECTIONS:
        raise ValueError(f"unsupported deep_sync section: {section}")
    try:
        offset = max(0, int(data.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    return section, offset


def build_deep_sync_page(
    agent: str,
    section: str,
    *,
    cursor: str | None = None,
    limit: int = 20,
    scope: str = "open",
) -> dict[str, Any]:
    """Cursor-paginated hydration for one agent.sync section (#230)."""
    import crowley
    import tickets

    normalized_agent = str(agent or "").strip().lower()
    if normalized_agent not in {"cursor", "codex", "chatgpt"}:
        raise ValueError(f"unsupported agent: {agent}")

    page_limit = normalize_agent_sync_limit(limit)
    cursor_section, offset = decode_deep_sync_cursor(cursor) if cursor else ("", 0)
    section_norm = str(section or "").strip().lower()
    if section_norm not in DEEP_SYNC_SECTIONS:
        raise ValueError(f"unsupported deep_sync section: {section}")
    if cursor_section and cursor_section != section_norm:
        raise ValueError("cursor section mismatch")

    project = crowley.get_active_project()
    project_id = int(project["id"]) if project is not None else None

    if section_norm == "handoffs":
        import agent_behavior

        feed = agent_behavior.build_auto_handoff_feed(limit=50)
        items = feed.get("items") if isinstance(feed.get("items"), list) else []
        page = [compress_sync_item(item) for item in items[offset : offset + page_limit] if isinstance(item, dict)]
    elif section_norm == "tickets":
        scope_norm = (scope or "open").strip().lower()
        if scope_norm not in {"open", "history", "closed"}:
            raise ValueError("scope must be open, history, or closed")
        if scope_norm == "history":
            rows = tickets.list_tickets(
                project_id=project_id,
                status="all",
                sort="oldest",
                limit=page_limit,
                offset=offset,
            )
            total = tickets.count_tickets(project_id=project_id, status="all")
        elif scope_norm == "closed":
            rows = tickets.list_tickets(
                project_id=project_id,
                status="done,cancelled",
                sort="newest",
                limit=page_limit,
                offset=offset,
            )
            total = tickets.count_tickets(project_id=project_id, status="done,cancelled")
        else:
            summary = tickets.build_tickets_summary(
                project_id, normalized_agent, open_limit=50, closed_limit=20
            )
            open_rows = summary.get("open") if isinstance(summary.get("open"), list) else []
            rows = open_rows[offset : offset + page_limit]
            total = tickets.count_tickets(project_id=project_id, open_only=True)
        if scope_norm == "open":
            page = [
                compress_ticket_item(row) for row in rows if isinstance(row, dict)
            ]
        else:
            page = [
                compress_ticket_item(tickets._ticket_row_to_dict(row))
                for row in rows
                if row is not None
            ]
    elif section_norm == "memory":
        retrieval = crowley.retrieve_work_context_memories(project_id, normalized_agent, limit=50)
        memories = retrieval.get("memories") if isinstance(retrieval.get("memories"), list) else []
        page = [compress_sync_item(item) for item in memories[offset : offset + page_limit] if isinstance(item, dict)]
    elif section_norm == "decisions":
        if project_id is None:
            page = []
        else:
            rows = crowley.list_decisions(project_id, limit=offset + page_limit)
            page = [
                compress_sync_item(crowley.row_to_dict(row))
                for row in rows[offset : offset + page_limit]
            ]
    elif section_norm == "constraints":
        rows = crowley._list_constraint_memories(project_id, limit=offset + page_limit)
        page = [compress_sync_item(item) for item in rows[offset : offset + page_limit] if isinstance(item, dict)]
    else:  # events
        raw_events = [
            crowley._memory_item_api_dict(row)
            for row in crowley.list_recent_agent_events(limit=offset + page_limit, project_id=project_id)
        ]
        other = [
            crowley._agent_sync_event_dict(event)
            for event in raw_events
            if str(event.get("source", "")).lower() != normalized_agent
        ]
        page = [compress_sync_item(item) for item in other[offset : offset + page_limit] if isinstance(item, dict)]

    next_offset = offset + len(page)
    has_more = len(page) >= page_limit
    result: dict[str, Any] = {
        "agent": normalized_agent,
        "section": section_norm,
        "items": page,
        "limit": page_limit,
        "offset": offset,
        "count": len(page),
        "next_cursor": encode_deep_sync_cursor(section_norm, next_offset) if has_more else None,
        "sync_meta": {
            "envelope": ASE_ENVELOPE_VERSION,
            "deep_sync": True,
            "payload_bytes": payload_bytes({"items": page}),
        },
    }
    if section_norm == "tickets":
        result["scope"] = scope_norm
        result["total"] = total
    return result
