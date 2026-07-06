"""V3.9.18 #131 patch — handoff → ticket bridge (work ticket enrich, no duplicates)."""

from __future__ import annotations

import re

import crowley
import tickets

HANDOFF_PERSIST_TYPES = frozenset({"builder_handoff", "architect_handoff"})
_WORK_TICKET_RE = re.compile(
    r"(?:ticket|closed\s+ticket|work\s+ticket)\s*#(\d+)",
    re.IGNORECASE,
)
_BARE_TICKET_HASH_RE = re.compile(r"(?<!\w)#(\d+)\b")

_parity_metrics: dict[str, int] = {
    "tickets_created": 0,
    "work_ticket_enriched": 0,
    "follow_up_archival": 0,
    "archival_upserted": 0,
    "duplicates_canceled": 0,
    "missing_links_blocked": 0,
}


def parity_metrics() -> dict[str, object]:
    """#184 — observability counters for handoff↔ticket parity."""
    report = verify_handoff_ticket_parity(limit=20)
    return {
        "counters": dict(_parity_metrics),
        "parity_ok": report.get("parity_ok"),
        "missing_count": report.get("missing_count", 0),
        "duplicate_group_count": report.get("duplicate_group_count", 0),
    }


def _record_parity_metric(name: str, *, amount: int = 1) -> None:
    _parity_metrics[name] = int(_parity_metrics.get(name, 0)) + amount


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


def extract_referenced_ticket_ids(
    content: str,
    *,
    metadata: dict[str, object] | None = None,
) -> list[int]:
    """Collect ticket ids from metadata, Context Basis, and body (#167)."""
    seen: set[int] = set()
    ordered: list[int] = []

    def _add(raw: object) -> None:
        try:
            ticket_id = int(raw)
        except (TypeError, ValueError):
            return
        if ticket_id not in seen:
            seen.add(ticket_id)
            ordered.append(ticket_id)

    if metadata:
        for key in ("closed_work_ticket_id", "work_ticket_id", "ticket_id"):
            if key in metadata:
                _add(metadata.get(key))

    context = _section_text(content, "Context Basis")
    for blob in (context, content):
        if not blob:
            continue
        for match in _WORK_TICKET_RE.finditer(blob):
            _add(match.group(1))
        for match in _BARE_TICKET_HASH_RE.finditer(blob):
            _add(match.group(1))
    return ordered


def extract_work_ticket_id(
    content: str,
    *,
    metadata: dict[str, object] | None = None,
) -> int | None:
    """Parse work ticket id from handoff metadata or Context Basis / body."""
    refs = extract_referenced_ticket_ids(content, metadata=metadata)
    return refs[0] if refs else None


def resolve_work_ticket_link(
    content: str,
    metadata: dict[str, object] | None = None,
    *,
    closed_work_ticket_id: int | None = None,
) -> tuple[int | None, str]:
    """#182 — prefer metadata; regex content is explicit fallback."""
    if closed_work_ticket_id is not None:
        return int(closed_work_ticket_id), "explicit_metadata"
    if metadata:
        for key in ("closed_work_ticket_id", "work_ticket_id", "ticket_id"):
            raw = metadata.get(key)
            if raw is not None:
                try:
                    return int(raw), f"metadata.{key}"
                except (TypeError, ValueError):
                    continue
    refs = extract_referenced_ticket_ids(content, metadata=metadata)
    if refs:
        return refs[0], "content_reference"
    return None, "unresolved"


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


def list_tickets_for_handoff_memory(memory_id: int) -> list[dict[str, object]]:
    conn = crowley.connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM tickets
            WHERE linked_memory_id = ?
            ORDER BY id ASC
            """,
            (int(memory_id),),
        ).fetchall()
    finally:
        conn.close()
    return [tickets._ticket_row_to_dict(row) for row in rows]


def get_ticket_for_handoff_memory(memory_id: int) -> dict[str, object] | None:
    """Return canonical ticket for a handoff memory (#180 — earliest id wins)."""
    linked = list_tickets_for_handoff_memory(memory_id)
    return linked[0] if linked else None


def require_handoff_memory_parity(memory_id: int, bridge: dict[str, object]) -> None:
    """#177/#179 — fail fast when a persisted handoff lacks a linked ticket."""
    if bridge.get("skipped"):
        return
    if list_tickets_for_handoff_memory(memory_id):
        return
    _record_parity_metric("missing_links_blocked")
    raise ValueError(
        f"handoff_ticket_parity_failed: handoff #{memory_id} has no linked ticket "
        f"(bridge mode={bridge.get('mode')}, linkage={bridge.get('linkage_decision')})"
    )


def _build_persisted_description(
    fields: dict[str, str],
    *,
    memory_id: int,
    handoff_type: str,
    source: str,
    closed_work_ticket_id: int | None,
) -> str:
    description = fields["description"]
    if fields["qa_summary"]:
        description = f"{description}\n\n## QA Results\n\n{fields['qa_summary']}".strip()
    provenance = (
        f"Provenance: handoff memory #{memory_id} "
        f"({handoff_type}, source={source})"
    )
    if closed_work_ticket_id is not None:
        provenance += f"; work ticket #{closed_work_ticket_id}"
    return f"{description}\n\n{provenance}".strip()


def _upsert_linked_ticket_from_handoff(
    ticket_id: int,
    memory_id: int,
    content: str,
    *,
    source: str,
    handoff_type: str,
    closed_work_ticket_id: int | None = None,
) -> dict[str, object]:
    """Refresh canonical linked ticket fields from handoff content."""
    fields = parse_handoff_ticket_fields(content)
    description = _build_persisted_description(
        fields,
        memory_id=memory_id,
        handoff_type=handoff_type,
        source=source,
        closed_work_ticket_id=closed_work_ticket_id,
    )
    result = tickets.update_ticket(
        ticket_id,
        actor=source,
        status="done",
        linked_memory_id=int(memory_id),
        description=description,
        comment=f"Handoff #{memory_id} replay — ticket upserted",
    )
    tickets.append_ticket_event(
        ticket_id,
        "handoff_linked",
        source,
        {
            "memory_item_id": memory_id,
            "handoff_type": handoff_type,
            "provenance": f"handoff #{memory_id}",
            "mode": "upsert_linked",
        },
    )
    return result["ticket"]


def _cancel_duplicate_linked_tickets(
    memory_id: int,
    *,
    keep_id: int,
    actor: str = "system",
    dry_run: bool = False,
) -> list[int]:
    """Cancel and unlink duplicate tickets for the same handoff memory."""
    cancelled: list[int] = []
    for ticket in list_tickets_for_handoff_memory(memory_id):
        ticket_id = int(ticket["id"])
        if ticket_id == keep_id:
            continue
        cancelled.append(ticket_id)
        if dry_run:
            continue
        tickets.update_ticket(
            ticket_id,
            actor=actor,
            status="cancelled",
            clear_linked_memory=True,
            comment=f"Reconcile: duplicate handoff #{memory_id} (kept ticket #{keep_id})",
        )
        tickets.append_ticket_event(
            ticket_id,
            "handoff_reconciled",
            actor,
            {
                "memory_item_id": memory_id,
                "kept_ticket_id": keep_id,
                "action": "cancel_duplicate",
            },
        )
    if cancelled and not dry_run:
        _record_parity_metric("duplicates_canceled", amount=len(cancelled))
    return cancelled


def ensure_linked_memory_unique_index(conn) -> None:
    """#151 — one ticket per handoff memory (partial unique index)."""
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_linked_memory_unique
        ON tickets(linked_memory_id)
        WHERE linked_memory_id IS NOT NULL
        """
    )


def _handoff_context_for_memory(memory_id: int) -> dict[str, object] | None:
    item = crowley.get_memory_item_api_by_id(memory_id)
    if item is None:
        return None
    body = str(item.get("body", "") or item.get("content", "") or item.get("display", ""))
    source = str(item.get("source", "cursor") or "cursor")
    handoff_type = "builder_handoff"
    if "architect" in body.lower():
        handoff_type = "architect_handoff"
    project_id = item.get("project_id")
    metadata = item.get("metadata")
    return {
        "body": body,
        "source": source,
        "handoff_type": handoff_type,
        "project_id": int(project_id) if project_id is not None else None,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _list_duplicate_linked_memory_groups() -> list[dict[str, object]]:
    conn = crowley.connect_db()
    try:
        rows = conn.execute(
            """
            SELECT linked_memory_id, COUNT(*) AS ticket_count
            FROM tickets
            WHERE linked_memory_id IS NOT NULL
            GROUP BY linked_memory_id
            HAVING ticket_count > 1
            ORDER BY linked_memory_id ASC
            """
        ).fetchall()
    finally:
        conn.close()
    groups: list[dict[str, object]] = []
    for row in rows:
        memory_id = int(row["linked_memory_id"])
        linked = list_tickets_for_handoff_memory(memory_id)
        groups.append(
            {
                "memory_id": memory_id,
                "ticket_ids": [int(t["id"]) for t in linked],
                "ticket_count": len(linked),
            }
        )
    return groups


def _create_archival_ticket_for_handoff(
    memory_id: int,
    content: str,
    *,
    source: str,
    handoff_type: str,
    project_id: int | None = None,
    closed_work_ticket_id: int | None = None,
    linkage_decision: str = "archival_created",
) -> dict[str, object]:
    """Create a done ticket dedicated to this handoff memory."""
    existing = list_tickets_for_handoff_memory(memory_id)
    if existing:
        keep_id = int(existing[0]["id"])
        ticket = _upsert_linked_ticket_from_handoff(
            keep_id,
            memory_id,
            content,
            source=source,
            handoff_type=handoff_type,
            closed_work_ticket_id=closed_work_ticket_id,
        )
        _record_parity_metric("archival_upserted")
        return {
            "created": False,
            "idempotent": True,
            "mode": linkage_decision,
            "linkage_decision": linkage_decision,
            "ticket": ticket,
            "memory_item_id": memory_id,
            "work_ticket_id": closed_work_ticket_id,
        }

    fields = parse_handoff_ticket_fields(content)
    description = _build_persisted_description(
        fields,
        memory_id=memory_id,
        handoff_type=handoff_type,
        source=source,
        closed_work_ticket_id=closed_work_ticket_id,
    )

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
            "mode": linkage_decision,
            "linkage_decision": linkage_decision,
            "work_ticket_id": closed_work_ticket_id,
        },
    )
    _cancel_duplicate_linked_tickets(memory_id, keep_id=ticket_id, actor="system")
    _record_parity_metric("tickets_created")
    if linkage_decision == "follow_up_archival":
        _record_parity_metric("follow_up_archival")
    return {
        "created": True,
        "idempotent": False,
        "mode": linkage_decision,
        "linkage_decision": linkage_decision,
        "ticket": result["ticket"],
        "memory_item_id": memory_id,
        "work_ticket_id": closed_work_ticket_id,
        "event_id": result.get("event_id"),
    }


def enrich_work_ticket_from_handoff(
    work_ticket_id: int,
    memory_id: int,
    content: str,
    *,
    source: str,
    handoff_type: str,
) -> dict[str, object]:
    """Update an existing work ticket from handoff — no archival duplicate."""
    row = tickets.get_ticket_by_id(work_ticket_id)
    if row is None:
        return {
            "ok": False,
            "reason": f"work ticket not found: {work_ticket_id}",
            "linkage_decision": "work_ticket_missing",
        }

    existing_link = row["linked_memory_id"]
    if existing_link is not None and int(existing_link) != int(memory_id):
        project_id = int(row["project_id"]) if row["project_id"] is not None else None
        return _create_archival_ticket_for_handoff(
            memory_id,
            content,
            source=source,
            handoff_type=handoff_type,
            project_id=project_id,
            closed_work_ticket_id=work_ticket_id,
            linkage_decision="follow_up_archival",
        )

    if existing_link is not None and int(existing_link) == int(memory_id):
        _cancel_duplicate_linked_tickets(memory_id, keep_id=work_ticket_id, actor=source)
        return {
            "created": False,
            "idempotent": True,
            "mode": "work_ticket_already_linked",
            "linkage_decision": "work_ticket_already_linked",
            "ticket": tickets._ticket_row_to_dict(row),
            "memory_item_id": memory_id,
            "work_ticket_id": work_ticket_id,
        }

    fields = parse_handoff_ticket_fields(content)
    description = _build_persisted_description(
        fields,
        memory_id=memory_id,
        handoff_type=handoff_type,
        source=source,
        closed_work_ticket_id=work_ticket_id,
    )
    result = tickets.update_ticket(
        work_ticket_id,
        actor=source,
        status="done",
        linked_memory_id=int(memory_id),
        description=description,
        comment=f"Handoff #{memory_id} ingested — work ticket enriched",
    )
    tickets.append_ticket_event(
        work_ticket_id,
        "handoff_linked",
        source,
        {
            "memory_item_id": memory_id,
            "handoff_type": handoff_type,
            "provenance": f"handoff #{memory_id}",
            "mode": "work_ticket_enriched",
        },
    )
    _cancel_duplicate_linked_tickets(memory_id, keep_id=work_ticket_id, actor=source)
    _record_parity_metric("work_ticket_enriched")
    return {
        "created": False,
        "idempotent": False,
        "mode": "work_ticket_enriched",
        "linkage_decision": "work_ticket_enriched",
        "ticket": result["ticket"],
        "memory_item_id": memory_id,
        "work_ticket_id": work_ticket_id,
    }


def ensure_handoff_ticket_link(
    memory_id: int,
    content: str,
    *,
    source: str,
    handoff_type: str,
    project_id: int | None = None,
    closed_work_ticket_id: int | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """#167 — guarantee every persisted handoff memory has a linked ticket."""
    if list_tickets_for_handoff_memory(memory_id):
        linked = get_ticket_for_handoff_memory(memory_id)
        assert linked is not None
        return {
            "created": False,
            "idempotent": True,
            "mode": "already_linked",
            "linkage_decision": "already_linked",
            "ticket": linked,
            "memory_item_id": memory_id,
        }
    return persist_handoff_as_ticket(
        memory_id,
        content,
        source=source,
        handoff_type=handoff_type,
        project_id=project_id,
        closed_work_ticket_id=closed_work_ticket_id,
        metadata=metadata,
    )


def persist_handoff_as_ticket(
    memory_id: int,
    content: str,
    *,
    source: str,
    handoff_type: str,
    project_id: int | None = None,
    closed_work_ticket_id: int | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """
    Persist handoff as ticket record. Work tickets are enriched in place;
    archival tickets created only when no work ticket applies.
    """
    if handoff_type not in HANDOFF_PERSIST_TYPES:
        return {"skipped": True, "reason": f"handoff type {handoff_type} not persisted"}

    work_ticket_id, extraction_source = resolve_work_ticket_link(
        content,
        metadata,
        closed_work_ticket_id=closed_work_ticket_id,
    )

    linked = list_tickets_for_handoff_memory(memory_id)

    if work_ticket_id is not None:
        result = enrich_work_ticket_from_handoff(
            work_ticket_id,
            memory_id,
            content,
            source=source,
            handoff_type=handoff_type,
        )
        if result.get("linkage_decision") != "work_ticket_missing":
            result["ticket_extraction_source"] = extraction_source
            return result
        work_ticket_id = None

    if linked:
        canonical = get_ticket_for_handoff_memory(memory_id)
        assert canonical is not None
        keep_id = int(canonical["id"])
        _cancel_duplicate_linked_tickets(memory_id, keep_id=keep_id, actor=source)
        ticket = _upsert_linked_ticket_from_handoff(
            keep_id,
            memory_id,
            content,
            source=source,
            handoff_type=handoff_type,
            closed_work_ticket_id=work_ticket_id,
        )
        return {
            "created": False,
            "idempotent": True,
            "mode": "upsert_linked",
            "ticket": ticket,
            "memory_item_id": memory_id,
            "duplicate_count": len(linked),
        }

    result = _create_archival_ticket_for_handoff(
        memory_id,
        content,
        source=source,
        handoff_type=handoff_type,
        project_id=project_id,
        closed_work_ticket_id=None,
        linkage_decision="archival_created",
    )
    result["ticket_extraction_source"] = extraction_source
    return result


def verify_handoff_ticket_parity(*, limit: int = 50) -> dict[str, object]:
    """Compare recent handoffs to linked tickets; flag gaps and duplicates."""
    limit = max(1, min(int(limit), 200))
    rows = crowley.list_recent_agent_events(limit=limit * 2)
    handoffs: list[dict[str, object]] = []
    missing: list[int] = []
    duplicates: list[dict[str, object]] = []

    for row in rows:
        if len(handoffs) >= limit:
            break
        item = crowley._memory_item_api_dict(row)
        mem_id = item.get("id")
        if mem_id is None:
            continue
        memory_id = int(mem_id)
        body = str(item.get("body", "") or item.get("content", "") or item.get("display", ""))
        if "handoff" not in body.lower() and str(item.get("memory_type", "")) not in {
            "project_update",
            "summary",
        }:
            continue
        linked = list_tickets_for_handoff_memory(memory_id)
        entry = {
            "memory_id": memory_id,
            "ticket_ids": [int(t["id"]) for t in linked],
            "source": item.get("source"),
        }
        handoffs.append(entry)
        if not linked:
            missing.append(memory_id)
        elif len(linked) > 1:
            duplicates.append(entry)

    return {
        "handoffs_checked": len(handoffs),
        "missing_tickets": missing,
        "missing_count": len(missing),
        "duplicate_links": duplicates,
        "duplicate_group_count": len(duplicates),
        "parity_ok": not missing and not duplicates,
    }


def reconcile_handoff_ticket_parity(
    *,
    limit: int = 200,
    dry_run: bool = True,
) -> dict[str, object]:
    """
    #151 — audit + fix handoff ↔ ticket parity.
    Cancels duplicate links, backfills missing tickets, ensures unique index.
    """
    limit = max(1, min(int(limit), 500))
    before = verify_handoff_ticket_parity(limit=limit)
    actions: list[dict[str, object]] = []
    cancelled = 0
    backfilled = 0
    merged = 0

    for group in _list_duplicate_linked_memory_groups():
        memory_id = int(group["memory_id"])
        canonical = get_ticket_for_handoff_memory(memory_id)
        if canonical is None:
            continue
        keep_id = int(canonical["id"])
        dup_ids = _cancel_duplicate_linked_tickets(
            memory_id,
            keep_id=keep_id,
            dry_run=dry_run,
        )
        for ticket_id in dup_ids:
            actions.append(
                {
                    "action": "cancel_duplicate",
                    "memory_id": memory_id,
                    "ticket_id": ticket_id,
                    "kept_ticket_id": keep_id,
                }
            )
            cancelled += 1
            merged += 1

    for memory_id in list(before.get("missing_tickets", [])):
        ctx = _handoff_context_for_memory(int(memory_id))
        if ctx is None:
            actions.append({"action": "skip_missing_memory", "memory_id": memory_id})
            continue
        handoff_type = str(ctx["handoff_type"])
        if handoff_type not in HANDOFF_PERSIST_TYPES:
            actions.append({"action": "skip_non_persisted_handoff", "memory_id": memory_id})
            continue
        actions.append({"action": "backfill", "memory_id": memory_id})
        if dry_run:
            backfilled += 1
            continue
        bridge = persist_handoff_as_ticket(
            int(memory_id),
            str(ctx["body"]),
            source=str(ctx["source"]),
            handoff_type=handoff_type,
            project_id=ctx.get("project_id"),  # type: ignore[arg-type]
            metadata=ctx.get("metadata"),  # type: ignore[arg-type]
        )
        if bridge.get("created") or bridge.get("mode") in {
            "archival_created",
            "work_ticket_enriched",
            "upsert_linked",
        }:
            backfilled += 1

    index_applied = False
    if not dry_run:
        conn = crowley.connect_db()
        try:
            ensure_linked_memory_unique_index(conn)
            conn.commit()
            index_applied = True
        finally:
            conn.close()

    after = verify_handoff_ticket_parity(limit=limit) if not dry_run else before
    return {
        "dry_run": dry_run,
        "before": before,
        "after": after,
        "actions": actions,
        "cancelled_duplicates": cancelled,
        "backfilled": backfilled,
        "merged_groups": merged,
        "unique_index_applied": index_applied,
        "parity_ok_after": bool(after.get("parity_ok")) if not dry_run else None,
    }


def backfill_handoff_tickets(*, limit: int = 50) -> dict[str, object]:
    """Ingest recent handoffs missing linked tickets (skips duplicates)."""
    limit = max(1, min(int(limit), 200))
    rows = crowley.list_recent_agent_events(limit=limit * 2)
    created = 0
    enriched = 0
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
        if list_tickets_for_handoff_memory(memory_id):
            skipped += 1
            continue
        body = str(item.get("body", "") or item.get("content", "") or item.get("display", ""))
        if "handoff" not in body.lower() and str(item.get("memory_type", "")) not in {
            "project_update",
            "summary",
        }:
            continue
        handoff_type = "builder_handoff"
        if "architect" in body.lower():
            handoff_type = "architect_handoff"
        elif "builder_handoff" not in body.lower():
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
        mode = str(bridge.get("mode", ""))
        if bridge.get("created"):
            created += 1
        elif mode == "work_ticket_enriched":
            enriched += 1
        results.append(bridge)

    return {
        "scanned": len(results),
        "created": created,
        "enriched": enriched,
        "skipped_existing": skipped,
        "results": results,
    }
