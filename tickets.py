"""Crowley concurrent ticketing domain."""

from __future__ import annotations

import json
import sqlite3

import crowley


# --- concurrent ticketing (V3.9) ----------------------------------------------


TICKET_STATUSES = frozenset({
    "open",
    "claimed",
    "in_progress",
    "blocked",
    "done",
    "cancelled",
})
TICKET_OPEN_STATUSES = frozenset({"open", "claimed", "in_progress", "blocked"})
TICKET_ASSIGNEES = frozenset({"codex", "cursor", "crowley", "mr_go", "unassigned"})
TICKET_SOURCES = frozenset({"codex", "cursor", "crowley", "mr_go", "manual", "system", "chatgpt"})
TICKET_EVENT_TYPES = frozenset({
    "created",
    "claimed",
    "status_change",
    "cancelled",
    "comment",
    "handoff_linked",
    "handoff_reconciled",
    "assignee_change",
    "priority_change",
})


def _validate_ticket_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in TICKET_STATUSES:
        raise ValueError(f"invalid ticket status: {status}")
    return normalized


def _validate_ticket_assignee(assignee: str) -> str:
    normalized = assignee.strip().lower()
    if normalized not in TICKET_ASSIGNEES:
        raise ValueError(f"invalid ticket assignee: {assignee}")
    return normalized


def _validate_ticket_source(source: str) -> str:
    normalized = source.strip().lower()
    if normalized not in TICKET_SOURCES:
        raise ValueError(f"invalid ticket source: {source}")
    return normalized


def _ticket_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return crowley.row_to_dict(row)


def append_ticket_event(
    ticket_id: int,
    event_type: str,
    actor: str,
    payload: dict[str, object] | None = None,
) -> int:
    import agent_identity

    if event_type not in TICKET_EVENT_TYPES:
        raise ValueError(f"invalid ticket event type: {event_type}")
    now = crowley._now_iso()
    actor_norm = actor.strip().lower()
    enriched = agent_identity.enrich_event_payload(
        payload,
        agent_id=actor_norm,
        source=actor_norm,
        timestamp=now,
        action=f"ticket.{event_type}",
        content_hint=f"ticket:{ticket_id}",
    )
    conn = crowley.connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO ticket_events (ticket_id, event_type, actor, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, event_type, actor_norm, json.dumps(enriched), now),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def create_ticket(
    title: str,
    *,
    description: str = "",
    assignee: str = "unassigned",
    priority: int = 2,
    parent_id: int | None = None,
    blocked_by_ticket_id: int | None = None,
    source: str = "manual",
    actor: str = "system",
    project_id: int | None = None,
    linked_memory_id: int | None = None,
    status: str = "open",
) -> dict[str, object]:
    """Create a ticket and initial event. Returns {ticket, event_id}."""
    import agent_identity

    actor_norm = actor.strip().lower()
    allowed, message = agent_identity.check_domain_permission(actor_norm, "ticket.create")
    if not allowed:
        raise ValueError(message or "permission_denied")
    title_text = crowley._normalize_text(title)
    if not title_text:
        raise ValueError("ticket title is required")

    if project_id is None:
        project = crowley.get_active_project()
        if project is None:
            raise ValueError("no active project")
        project_id = int(project["id"])

    status_norm = _validate_ticket_status(status)
    assignee_norm = _validate_ticket_assignee(assignee)
    source_norm = _validate_ticket_source(source)
    priority_val = max(1, min(int(priority), 4))
    now = crowley._now_iso()

    if linked_memory_id is not None:
        existing = get_ticket_by_linked_memory_id(int(linked_memory_id))
        if existing is not None:
            raise ValueError(
                f"linked_memory_id {linked_memory_id} already linked to ticket #{existing['id']}"
            )

    conn = crowley.connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO tickets (
                project_id, title, description, status, assignee, priority,
                parent_id, blocked_by_ticket_id, source,
                created_at, updated_at, closed_at, linked_memory_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                project_id,
                title_text,
                description.strip(),
                status_norm,
                assignee_norm,
                priority_val,
                parent_id,
                blocked_by_ticket_id,
                source_norm,
                now,
                now,
                linked_memory_id,
            ),
        )
        ticket_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    event_id = append_ticket_event(
        ticket_id,
        "created",
        actor,
        {
            "title": title_text,
            "assignee": assignee_norm,
            "priority": priority_val,
            "source": source_norm,
        },
    )
    ticket = get_ticket_by_id(ticket_id)
    if ticket is None:
        raise RuntimeError("ticket create failed")
    import write_audit

    write_audit.record_write_audit(
        agent_id=actor_norm,
        action="ticket.create",
        entity_type="ticket",
        entity_id=ticket_id,
        before=None,
        after=write_audit.ticket_row_snapshot(ticket),
    )
    crowley.record_system_metric("ticket_created", label=str(ticket_id))
    return {"ticket": _ticket_row_to_dict(ticket), "event_id": event_id}


def get_ticket_by_id(ticket_id: int) -> sqlite3.Row | None:
    conn = crowley.connect_db()
    try:
        return conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    finally:
        conn.close()


def get_ticket_by_linked_memory_id(memory_id: int) -> dict[str, object] | None:
    """Return ticket linked to a handoff memory id, if any."""
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
    return _ticket_row_to_dict(row)


def list_ticket_events(ticket_id: int, *, limit: int = 20) -> list[sqlite3.Row]:
    limit = max(1, min(int(limit), 100))
    conn = crowley.connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM ticket_events
            WHERE ticket_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (ticket_id, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def list_recent_ticket_events_for_project(
    project_id: int,
    *,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Recent ticket board events across a project (newest first)."""
    limit = max(1, min(int(limit), 50))
    conn = crowley.connect_db()
    try:
        rows = conn.execute(
            """
            SELECT
                te.id AS event_id,
                te.ticket_id,
                te.event_type,
                te.actor,
                te.payload,
                te.created_at,
                t.title AS ticket_title,
                t.status AS ticket_status
            FROM ticket_events te
            INNER JOIN tickets t ON t.id = te.ticket_id
            WHERE t.project_id = ?
            ORDER BY datetime(te.created_at) DESC, te.id DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def _format_ticket_event_feed_summary(
    event_type: str,
    actor: str,
    payload: dict[str, object],
    *,
    ticket_id: int,
    ticket_title: str,
) -> str:
    title = crowley._truncate(str(ticket_title or f"Ticket #{ticket_id}"), 80)
    normalized = str(event_type or "event")
    if normalized == "status_change":
        return (
            f"Ticket #{ticket_id} {title} — "
            f"{payload.get('from', '?')} → {payload.get('to', '?')}"
        )
    if normalized == "created":
        return f"Ticket #{ticket_id} opened — {title}"
    if normalized == "claimed":
        return f"Ticket #{ticket_id} claimed by {actor} — {title}"
    if normalized == "cancelled":
        reason = str(payload.get("reason") or "").strip()
        base = f"Ticket #{ticket_id} cancelled — {title}"
        return f"{base} ({reason})" if reason else base
    if normalized == "handoff_linked":
        mem = payload.get("memory_id")
        return f"Ticket #{ticket_id} linked handoff memory #{mem} — {title}"
    if normalized == "comment":
        text = crowley._truncate(str(payload.get("text") or ""), 120)
        return f"Ticket #{ticket_id} comment — {text}" if text else f"Ticket #{ticket_id} comment — {title}"
    if normalized == "assignee_change":
        return (
            f"Ticket #{ticket_id} assignee {payload.get('from', '?')} → "
            f"{payload.get('to', '?')} — {title}"
        )
    if normalized == "priority_change":
        return (
            f"Ticket #{ticket_id} priority P{payload.get('from', '?')} → "
            f"P{payload.get('to', '?')} — {title}"
        )
    return f"Ticket #{ticket_id} {normalized} — {title}"


def _tickets_by_linked_memory_ids(memory_ids: list[int]) -> dict[int, list[int]]:
    import memory_ticket_linkage

    return memory_ticket_linkage.batch_linked_ticket_ids(memory_ids)


def _ticket_linked_handoff(memory_id: int | None) -> dict[str, object] | None:
    if memory_id is None:
        return None
    conn = crowley.connect_db()
    try:
        row = crowley._load_active_memory_item(conn, int(memory_id))
    finally:
        conn.close()
    if row is None:
        return {
            "memory_id": int(memory_id),
            "summary": "(memory not found)",
        }
    return {
        "memory_id": int(memory_id),
        "source": row["source"],
        "memory_type": row["memory_type"],
        "created_at": row["created_at"],
        "summary": crowley._handoff_summary_line(str(row["content"])),
        **{
            k: v
            for k, v in crowley._memory_item_api_dict(row).items()
            if k in {"attribution", "agent_id"}
        },
    }


def build_recent_changes_feed(
    project_id: int | None,
    *,
    limit: int = 20,
) -> dict[str, object]:
    """Unified recent-changes timeline from handoffs and ticket events."""
    if project_id is None:
        return {"items": []}

    limit = max(1, min(int(limit), 50))
    per_source = max(5, limit // 2)

    agent_rows = crowley.list_recent_agent_events(limit=per_source, project_id=project_id)
    memory_ids = [int(row["id"]) for row in agent_rows]
    linked_tickets = _tickets_by_linked_memory_ids(memory_ids)
    ticket_rows = list_recent_ticket_events_for_project(project_id, limit=per_source)

    items: list[dict[str, object]] = []
    for row in agent_rows:
        items.append(
            {
                "kind": "handoff",
                "id": f"handoff:{row['id']}",
                "created_at": row["created_at"],
                "source": row["source"],
                "memory_type": row["memory_type"],
                "summary": crowley._handoff_summary_line(str(row["content"])),
                "next_action": crowley._handoff_next_action_line(str(row["content"])),
                "linked_ticket_ids": linked_tickets.get(int(row["id"]), []),
            }
        )

    for row in ticket_rows:
        payload_raw = row["payload"]
        try:
            payload = json.loads(str(payload_raw or "{}"))
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        ticket_id = int(row["ticket_id"])
        items.append(
            {
                "kind": "ticket",
                "id": f"ticket_event:{row['event_id']}",
                "created_at": row["created_at"],
                "source": str(row["actor"] or "system"),
                "event_type": row["event_type"],
                "ticket_id": ticket_id,
                "ticket_title": row["ticket_title"],
                "summary": _format_ticket_event_feed_summary(
                    str(row["event_type"]),
                    str(row["actor"]),
                    payload,
                    ticket_id=ticket_id,
                    ticket_title=str(row["ticket_title"] or ""),
                ),
            }
        )

    items.sort(
        key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or "")),
        reverse=True,
    )
    return {"items": items[:limit]}


def list_tickets(
    *,
    project_id: int | None = None,
    status: str | None = None,
    open_only: bool = False,
    assignee: str | None = None,
    priority_max: int | None = None,
    parent_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str = "priority",
) -> list[sqlite3.Row]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    clauses = ["1=1"]
    params: list[object] = []

    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)

    if open_only:
        marks = ",".join("?" for _ in TICKET_OPEN_STATUSES)
        clauses.append(f"status IN ({marks})")
        params.extend(sorted(TICKET_OPEN_STATUSES))
    elif status is not None:
        if status.strip().lower() == "all":
            pass
        elif "," in status:
            statuses = [_validate_ticket_status(part) for part in status.split(",")]
            marks = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({marks})")
            params.extend(statuses)
        else:
            clauses.append("status = ?")
            params.append(_validate_ticket_status(status))

    if assignee is not None:
        clauses.append("assignee = ?")
        params.append(_validate_ticket_assignee(assignee))

    if priority_max is not None:
        clauses.append("priority <= ?")
        params.append(max(1, min(int(priority_max), 4)))

    if parent_id is not None:
        clauses.append("parent_id = ?")
        params.append(parent_id)

    sort_norm = (sort or "priority").strip().lower()
    if sort_norm in {"newest", "created_desc", "recent"}:
        order_clause = "ORDER BY datetime(created_at) DESC, id DESC"
    elif sort_norm in {"oldest", "created_asc"}:
        order_clause = "ORDER BY datetime(created_at) ASC, id ASC"
    elif sort_norm in {"updated", "updated_desc"}:
        order_clause = "ORDER BY datetime(updated_at) DESC, id DESC"
    else:
        order_clause = "ORDER BY priority ASC, datetime(updated_at) DESC, id DESC"

    params.extend([limit, offset])
    conn = crowley.connect_db()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM tickets
            WHERE {' AND '.join(clauses)}
            {order_clause}
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def count_tickets(
    *,
    project_id: int | None = None,
    status: str | None = None,
    open_only: bool = False,
    assignee: str | None = None,
) -> int:
    clauses = ["1=1"]
    params: list[object] = []
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if open_only:
        marks = ",".join("?" for _ in TICKET_OPEN_STATUSES)
        clauses.append(f"status IN ({marks})")
        params.extend(sorted(TICKET_OPEN_STATUSES))
    elif status is not None:
        status_norm = status.strip().lower()
        if status_norm == "all":
            pass
        elif "," in status:
            statuses = [_validate_ticket_status(part) for part in status.split(",")]
            marks = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({marks})")
            params.extend(statuses)
        else:
            clauses.append("status = ?")
            params.append(_validate_ticket_status(status))
    if assignee is not None:
        clauses.append("assignee = ?")
        params.append(_validate_ticket_assignee(assignee))

    conn = crowley.connect_db()
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM tickets WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        return int(row["c"]) if row is not None else 0
    finally:
        conn.close()


def update_ticket(
    ticket_id: int,
    *,
    actor: str,
    status: str | None = None,
    assignee: str | None = None,
    priority: int | None = None,
    description: str | None = None,
    blocked_by_ticket_id: int | None = None,
    comment: str | None = None,
    linked_memory_id: int | None = None,
    clear_blocked_by: bool = False,
    clear_linked_memory: bool = False,
) -> dict[str, object]:
    row = get_ticket_by_id(ticket_id)
    if row is None:
        raise ValueError(f"ticket not found: {ticket_id}")

    import write_audit

    before_snapshot = write_audit.ticket_row_snapshot(row)
    fields: list[str] = []
    params: list[object] = []
    now = crowley._now_iso()
    old_status = str(row["status"])
    old_linked_memory_id = row["linked_memory_id"]

    if status is not None:
        status_norm = _validate_ticket_status(status)
        fields.append("status = ?")
        params.append(status_norm)
        if status_norm in {"done", "cancelled"}:
            fields.append("closed_at = ?")
            params.append(now)
        elif old_status in {"done", "cancelled"}:
            fields.append("closed_at = NULL")

    if assignee is not None:
        fields.append("assignee = ?")
        params.append(_validate_ticket_assignee(assignee))

    if priority is not None:
        fields.append("priority = ?")
        params.append(max(1, min(int(priority), 4)))

    if description is not None:
        fields.append("description = ?")
        params.append(description.strip())

    if clear_blocked_by:
        fields.append("blocked_by_ticket_id = NULL")
    elif blocked_by_ticket_id is not None:
        fields.append("blocked_by_ticket_id = ?")
        params.append(blocked_by_ticket_id)

    if clear_linked_memory:
        fields.append("linked_memory_id = NULL")
    elif linked_memory_id is not None:
        if old_linked_memory_id is not None and int(old_linked_memory_id) != int(linked_memory_id):
            raise ValueError(
                f"linked_memory_id is immutable on ticket #{ticket_id}: "
                f"existing={old_linked_memory_id}, requested={linked_memory_id}"
            )
        if old_linked_memory_id is None:
            fields.append("linked_memory_id = ?")
            params.append(linked_memory_id)

    if not fields and not comment:
        ticket = get_ticket_by_id(ticket_id)
        assert ticket is not None
        return {"ticket": _ticket_row_to_dict(ticket), "events": []}

    event_ids: list[int] = []
    if fields:
        fields.append("updated_at = ?")
        params.append(now)
        params.append(ticket_id)
        conn = crowley.connect_db()
        try:
            conn.execute(
                f"UPDATE tickets SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

        if status is not None and _validate_ticket_status(status) != old_status:
            event_ids.append(
                append_ticket_event(
                    ticket_id,
                    "status_change",
                    actor,
                    {"from": old_status, "to": _validate_ticket_status(status)},
                )
            )
        if assignee is not None and _validate_ticket_assignee(assignee) != str(row["assignee"]):
            event_ids.append(
                append_ticket_event(
                    ticket_id,
                    "assignee_change",
                    actor,
                    {"from": str(row["assignee"]), "to": _validate_ticket_assignee(assignee)},
                )
            )
        if priority is not None and int(priority) != int(row["priority"]):
            event_ids.append(
                append_ticket_event(
                    ticket_id,
                    "priority_change",
                    actor,
                    {"from": int(row["priority"]), "to": max(1, min(int(priority), 4))},
                )
            )

    if linked_memory_id is not None:
        new_linked = int(linked_memory_id)
        old_linked = (
            int(old_linked_memory_id)
            if old_linked_memory_id is not None
            else None
        )
        if old_linked != new_linked:
            event_ids.append(
                append_ticket_event(
                    ticket_id,
                    "handoff_linked",
                    actor,
                    {"memory_id": new_linked},
                )
            )
            try:
                import memory_ticket_linkage

                memory_ticket_linkage.add_memory_ticket_link(new_linked, ticket_id)
            except Exception:
                pass

    if comment and comment.strip():
        event_ids.append(
            append_ticket_event(
                ticket_id,
                "comment",
                actor,
                {"text": comment.strip()},
            )
        )

    ticket = get_ticket_by_id(ticket_id)
    assert ticket is not None
    if fields:
        write_audit.record_write_audit(
            agent_id=actor.strip().lower(),
            action="ticket.update",
            entity_type="ticket",
            entity_id=ticket_id,
            before=before_snapshot,
            after=write_audit.ticket_row_snapshot(ticket),
        )
    return {"ticket": _ticket_row_to_dict(ticket), "event_ids": event_ids}


def complete_ticket(ticket_id: int, *, actor: str = "system") -> dict[str, object]:
    result = update_ticket(ticket_id, actor=actor, status="done")
    crowley.record_system_metric("ticket_closed", label=str(ticket_id))
    return result


def cancel_ticket(
    ticket_id: int,
    *,
    actor: str,
    comment: str,
) -> dict[str, object]:
    import agent_identity

    actor_norm = actor.strip().lower()
    allowed, message = agent_identity.check_domain_permission(actor_norm, "ticket.cancel")
    if not allowed:
        raise ValueError(message or "permission_denied")
    reason = comment.strip()
    if not reason:
        raise ValueError("cancellation comment is required")
    row = get_ticket_by_id(ticket_id)
    if row is None:
        raise ValueError(f"ticket not found: {ticket_id}")
    old_status = str(row["status"])
    if old_status == "cancelled":
        return {
            "ticket": _ticket_row_to_dict(row),
            "event_ids": [],
            "already_cancelled": True,
        }
    result = update_ticket(ticket_id, actor=actor, status="cancelled")
    cancelled_event_id = append_ticket_event(
        ticket_id,
        "cancelled",
        actor,
        {"from": old_status, "reason": reason},
    )
    event_ids = list(result.get("event_ids") or [])
    event_ids.append(cancelled_event_id)
    ticket = get_ticket_by_id(ticket_id)
    assert ticket is not None
    crowley.record_system_metric("ticket_cancelled", label=str(ticket_id))
    return {"ticket": _ticket_row_to_dict(ticket), "event_ids": event_ids}


def claim_ticket(ticket_id: int, *, actor: str) -> dict[str, object]:
    row = get_ticket_by_id(ticket_id)
    if row is None:
        raise ValueError(f"ticket not found: {ticket_id}")
    status = str(row["status"])
    if status in {"done", "cancelled"}:
        raise ValueError(f"ticket {ticket_id} is closed")
    assignee = actor.strip().lower() if actor.strip().lower() in TICKET_ASSIGNEES else str(row["assignee"])
    new_status = "in_progress" if status in {"open", "claimed"} else status
    result = update_ticket(
        ticket_id,
        actor=actor,
        status=new_status,
        assignee=assignee,
    )
    append_ticket_event(ticket_id, "claimed", actor, {"status": new_status})
    return result


def get_ticket_detail(
    ticket_id: int,
    *,
    event_limit: int = 20,
    include_memories: bool = False,
    memory_limit: int = 50,
) -> dict[str, object] | None:
    row = get_ticket_by_id(ticket_id)
    if row is None:
        return None
    events = [
        {
            **crowley.row_to_dict(event),
            "payload": json.loads(str(event["payload"] or "{}")),
        }
        for event in list_ticket_events(ticket_id, limit=event_limit)
    ]
    ticket = _ticket_row_to_dict(row)
    linked_memory_id = ticket.get("linked_memory_id")
    linked_handoff = _ticket_linked_handoff(
        int(linked_memory_id) if linked_memory_id is not None else None
    )
    detail: dict[str, object] = {
        "ticket": ticket,
        "events": events,
        "linked_handoff": linked_handoff,
    }
    if include_memories:
        import memory_ticket_linkage

        context = memory_ticket_linkage.ticket_memory_context(
            ticket_id,
            memory_limit=memory_limit,
        )
        detail["linked_memories"] = context["by_type"]
        detail["linked_memories_total"] = context["total"]
        detail["linked_handoffs"] = context["handoffs"]
    return detail


def group_tickets_by_parent(
    tickets: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Group open tickets under parent initiatives for board/sync display."""
    if not tickets:
        return []

    open_ids = {int(ticket["id"]) for ticket in tickets}
    children_by_parent: dict[int, list[dict[str, object]]] = {}
    for ticket in tickets:
        parent_id = ticket.get("parent_id")
        if parent_id is None:
            continue
        children_by_parent.setdefault(int(parent_id), []).append(ticket)

    sort_key = lambda ticket: (int(ticket.get("priority", 4)), int(ticket["id"]))
    groups: list[dict[str, object]] = []

    for ticket in sorted(tickets, key=sort_key):
        parent_id = ticket.get("parent_id")
        if parent_id is not None and int(parent_id) in open_ids:
            continue
        ticket_id = int(ticket["id"])
        children = sorted(children_by_parent.get(ticket_id, []), key=sort_key)
        groups.append(
            {
                "ticket": ticket,
                "children": children,
                "is_initiative": bool(children),
            }
        )

    return groups


def _enrich_tickets_with_handoff_links(
    tickets: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Attach linked_handoff summary metadata for sync/UI (V3.9.9 #61)."""
    enriched: list[dict[str, object]] = []
    for ticket in tickets:
        item = dict(ticket)
        mem_id = item.get("linked_memory_id")
        if mem_id is not None:
            linked = _ticket_linked_handoff(int(mem_id))
            if linked is not None:
                item["linked_handoff"] = linked
                item["linked_handoff_summary"] = linked.get("summary")
        enriched.append(item)
    return enriched


def _ticket_anchor_payload(row: sqlite3.Row | dict[str, object]) -> dict[str, object]:
    data = row if isinstance(row, dict) else _ticket_row_to_dict(row)
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "status": data.get("status"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def build_ticket_lineage(project_id: int | None) -> dict[str, object]:
    """Compact ticket continuity metadata for sync and audit surfaces."""
    if project_id is None:
        return {
            "total": 0,
            "first_id": None,
            "latest_id": None,
            "gaps": [],
            "by_status": {},
            "first_ticket": None,
            "latest_ticket": None,
            "history_access": (
                "ticket.list status=all sort=oldest | agent.deep_sync section=tickets scope=history"
            ),
        }

    conn = crowley.connect_db()
    try:
        rows = conn.execute(
            "SELECT id FROM tickets WHERE project_id = ? ORDER BY id",
            (project_id,),
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        gap_list: list[int] = []
        if ids:
            id_set = set(ids)
            gap_list = [i for i in range(ids[0], ids[-1] + 1) if i not in id_set]
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM tickets WHERE project_id = ? GROUP BY status",
            (project_id,),
        ).fetchall()
        by_status = {str(row["status"]): int(row["c"]) for row in status_rows}
    finally:
        conn.close()

    first_rows = list_tickets(
        project_id=project_id,
        status="all",
        limit=1,
        sort="oldest",
    )
    latest_rows = list_tickets(
        project_id=project_id,
        status="all",
        limit=1,
        sort="newest",
    )
    return {
        "total": len(ids),
        "first_id": ids[0] if ids else None,
        "latest_id": ids[-1] if ids else None,
        "gaps": gap_list,
        "by_status": by_status,
        "first_ticket": _ticket_anchor_payload(first_rows[0]) if first_rows else None,
        "latest_ticket": _ticket_anchor_payload(latest_rows[0]) if latest_rows else None,
        "history_access": (
            "ticket.list status=all sort=oldest | agent.deep_sync section=tickets scope=history"
        ),
    }


def build_tickets_summary(
    project_id: int | None,
    agent: str | None = None,
    *,
    open_limit: int = 50,
    closed_limit: int = 5,
) -> dict[str, object]:
    if project_id is None:
        return {
            "open": [],
            "grouped_open": [],
            "assigned_to_agent": [],
            "blocked": [],
            "recently_closed": [],
            "lineage": build_ticket_lineage(None),
            "counts": {
                "open": 0,
                "in_progress": 0,
                "blocked": 0,
                "done_recent": 0,
                "total": 0,
                "done": 0,
                "cancelled": 0,
                "first_id": None,
                "latest_id": None,
                "gaps": [],
            },
        }

    open_rows = list_tickets(
        project_id=project_id,
        open_only=True,
        limit=max(1, min(int(open_limit), 50)),
    )
    open_payload = _enrich_tickets_with_handoff_links(
        [_ticket_row_to_dict(row) for row in open_rows]
    )
    grouped_open = group_tickets_by_parent(open_payload)
    agent_norm = agent.strip().lower() if isinstance(agent, str) else None
    assigned = [
        ticket
        for ticket in open_payload
        if agent_norm and str(ticket.get("assignee", "")).lower() == agent_norm
    ]
    blocked = [
        ticket for ticket in open_payload if str(ticket.get("status")) == "blocked"
    ]
    closed_rows = list_tickets(
        project_id=project_id,
        status="done,cancelled",
        limit=max(1, min(int(closed_limit), 20)),
        sort="newest",
    )
    lineage = build_ticket_lineage(project_id)
    by_status = lineage.get("by_status") if isinstance(lineage.get("by_status"), dict) else {}
    return {
        "open": open_payload,
        "grouped_open": grouped_open,
        "assigned_to_agent": assigned,
        "blocked": blocked,
        "recently_closed": _enrich_tickets_with_handoff_links(
            [_ticket_row_to_dict(row) for row in closed_rows]
        ),
        "lineage": lineage,
        "counts": {
            "open": count_tickets(project_id=project_id, status="open"),
            "in_progress": count_tickets(project_id=project_id, status="in_progress"),
            "blocked": count_tickets(project_id=project_id, status="blocked"),
            "open_total": count_tickets(project_id=project_id, open_only=True),
            "total": int(lineage.get("total") or 0),
            "done": int(by_status.get("done", 0)),
            "cancelled": int(by_status.get("cancelled", 0)),
            "first_id": lineage.get("first_id"),
            "latest_id": lineage.get("latest_id"),
            "gaps": lineage.get("gaps") or [],
        },
    }


def _ticket_handoff_prompt_suffix(ticket: dict[str, object]) -> str:
    """Prompt suffix for ticket ↔ handoff link (V3.9.9 #61)."""
    linked = ticket.get("linked_handoff")
    if isinstance(linked, dict):
        mem_id = linked.get("memory_id")
        summary = linked.get("summary")
        if mem_id is not None:
            return f" · handoff #{mem_id}: {summary}"
    mem_id = ticket.get("linked_memory_id")
    if mem_id is not None:
        return f" · handoff #{mem_id}"
    return ""


def _format_tickets_prompt_section(
    project_id: int | None,
    agent: str | None = None,
) -> str:
    summary = build_tickets_summary(project_id, agent)
    lines = [
        "Tickets (authoritative work board — use for assigned, blocked, or in-flight work):",
    ]
    assigned = summary["assigned_to_agent"]
    if isinstance(assigned, list) and assigned:
        lines.append("Assigned to Cursor:" if agent == "cursor" else "Assigned:")
        for ticket in assigned[:10]:
            if not isinstance(ticket, dict):
                continue
            lines.append(
                f"- #{ticket.get('id')} [{ticket.get('status')}] P{ticket.get('priority')} "
                f"{ticket.get('title')}{_ticket_handoff_prompt_suffix(ticket)}"
            )
    else:
        lines.append("Assigned: (none)")

    open_items = summary["grouped_open"]
    if isinstance(open_items, list) and open_items:
        lines.append("Open board:")
        for group in open_items[:10]:
            if not isinstance(group, dict):
                continue
            ticket = group.get("ticket")
            if not isinstance(ticket, dict):
                continue
            prefix = "Initiative" if group.get("is_initiative") else "Ticket"
            lines.append(
                f"- {prefix} #{ticket.get('id')} [{ticket.get('status')}] "
                f"{ticket.get('assignee')} | P{ticket.get('priority')} — {ticket.get('title')}"
            )
            children = group.get("children")
            if isinstance(children, list):
                for child in children[:8]:
                    if not isinstance(child, dict):
                        continue
                    lines.append(
                        f"  - child #{child.get('id')} [{child.get('status')}] "
                        f"P{child.get('priority')} — {child.get('title')}"
                    )
    else:
        lines.append("Open board: (none)")

    blocked = summary["blocked"]
    if isinstance(blocked, list) and blocked:
        lines.append("Blocked:")
        for ticket in blocked[:5]:
            if not isinstance(ticket, dict):
                continue
            lines.append(f"- #{ticket.get('id')} — {ticket.get('title')}")
    else:
        lines.append("Blocked: (none)")

    return "\n".join(lines)
