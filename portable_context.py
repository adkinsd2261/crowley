"""Extracted V4.1 world/sync/portable runtime implementation."""

from __future__ import annotations

from typing import Any

DEFAULT_PROJECT_SLUG = "crowley"

_RUNTIME_BOUND = None
_LOCAL_NAMES = set(globals())

def _bind_runtime(rt: Any) -> None:
    global _RUNTIME_BOUND
    _RUNTIME_BOUND = rt
    impl_names = {name for name in globals() if name.startswith("_impl_")}
    protected = (
        set(_LOCAL_NAMES)
        | {"_bind_runtime", "_MISSING", "_is_runtime", "_dispatch"}
        | impl_names
        | {name.removeprefix("_impl_") for name in impl_names}
    )
    for name, value in vars(rt).items():
        if name not in protected:
            globals()[name] = value

_MISSING = object()

def _is_runtime(value: Any) -> bool:
    return hasattr(value, "connect_db") and hasattr(value, "setup_db")

def _dispatch(impl: Any, rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    if _is_runtime(rt):
        _bind_runtime(rt)
        return impl(*args, **kwargs)
    if rt is _MISSING:
        return impl(*args, **kwargs)
    return impl(rt, *args, **kwargs)

def build_portable_context_packet(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_portable_context_packet, rt, *args, **kwargs)

def render_portable_context_packet_markdown(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_render_portable_context_packet_markdown, rt, *args, **kwargs)

def parse_terminal_writeback(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_parse_terminal_writeback, rt, *args, **kwargs)

def ingest_terminal_writeback(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_ingest_terminal_writeback, rt, *args, **kwargs)

def build_portable_writeback_acceptance_report(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_portable_writeback_acceptance_report, rt, *args, **kwargs)

def write_portable_writeback_acceptance_report(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_write_portable_writeback_acceptance_report, rt, *args, **kwargs)

def load_portable_writeback_acceptance_report(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_load_portable_writeback_acceptance_report, rt, *args, **kwargs)

def _impl_build_portable_context_packet(
    surface: str = "chatgpt",
    *,
    project_slug: str | None = None,
) -> dict[str, object]:
    """Medium Crowley packet for manual paste into any AI surface (V3.9.12 #76)."""
    normalized_surface = (surface or "chatgpt").strip().lower() or "chatgpt"
    setup_db()
    project = (
        get_project_by_slug(project_slug)
        if project_slug
        else get_active_project()
    )
    project_id = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    state_payload = _state_payload_for_api(state)

    task_frame = build_task_frame_context(project_id, agent=None)
    working_on = task_frame.get("working_on")
    if isinstance(working_on, list):
        working_on = working_on[:PORTABLE_PACKET_WORKING_CAP]
    else:
        working_on = []

    tickets = build_tickets_summary(project_id, agent=None) if project_id else {}
    retrieval = retrieve_work_context_memories(
        project_id,
        agent=None,
        limit=PORTABLE_PACKET_MEMORY_CAP,
    )
    memories = _portable_memory_rows(
        retrieval["memories"] if isinstance(retrieval.get("memories"), list) else []
    )

    guardrails = task_frame.get("guardrails")
    recent_decisions: list[dict[str, object]] = []
    constraint_memories: list[dict[str, object]] = []
    if isinstance(guardrails, dict):
        for row in guardrails.get("recent_decisions") or []:
            if isinstance(row, dict):
                recent_decisions.append(
                    {
                        "summary": _portable_clip(row.get("summary"), 180),
                        "detail": _portable_clip(row.get("detail"), 180),
                    }
                )
        for row in guardrails.get("constraint_memories") or []:
            if isinstance(row, dict):
                constraint_memories.append(
                    {
                        "summary": _portable_clip(
                            row.get("summary") or row.get("content"), 200
                        ),
                        "memory_type": row.get("memory_type"),
                    }
                )
    recent_decisions = recent_decisions[:PORTABLE_PACKET_DECISIONS_CAP]
    constraint_memories = constraint_memories[:PORTABLE_PACKET_CONSTRAINTS_CAP]

    activity = _agent_activity_summary(project_id) if project_id else {}
    latest_contact = activity.get("latest_contact") if isinstance(activity, dict) else None
    wire = build_activity_wire(project_id, limit=PORTABLE_PACKET_WIRE_CAP)
    wire_lines: list[str] = []
    for item in wire.get("items") or []:
        if isinstance(item, dict) and item.get("line"):
            wire_lines.append(_portable_clip(item.get("line"), 160))

    open_initiatives: list[str] = []
    open_rows = tickets.get("open") if isinstance(tickets, dict) else []
    if isinstance(open_rows, list):
        for ticket in open_rows[:8]:
            if not isinstance(ticket, dict):
                continue
            open_initiatives.append(
                f"#{ticket.get('id')} [{ticket.get('status')}] "
                f"{_portable_clip(ticket.get('title'), 120)}"
            )

    return {
        "packet_version": PORTABLE_PACKET_VERSION,
        "crowley_version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "surface": normalized_surface,
        "identity": {
            "crowley_role": (
                f"Crowley is the persistent context layer for {USER_NAME}. "
                "It holds memory, tickets, project truth, and agent handoffs."
            ),
            "terminal_role": (
                f"You are a temporary reasoning surface ({normalized_surface}). "
                "You are not Crowley. Use this packet for context; end with structured "
                "writeback JSON — never invent project facts beyond what is included."
            ),
            "authority_order": (
                "filesystem docs → tickets → agent activity → project_state → "
                "canon → supporting memories in this packet"
            ),
        },
        "world": {
            "project": row_to_dict(project) if project is not None else None,
            "state": state_payload,
            "brain": get_brain_snapshot() if not is_test_mode() else None,
        },
        "work": {
            "focus": state_payload.get("focus") if state_payload else None,
            "phase": state_payload.get("phase") if state_payload else None,
            "next_action": state_payload.get("next_action") if state_payload else None,
            "working_on": working_on,
            "open_initiatives": open_initiatives,
            "latest_agent_contact": latest_contact,
            "in_the_air": wire_lines,
        },
        "guardrails": {
            "recent_decisions": recent_decisions,
            "constraints": constraint_memories,
        },
        "memories": memories,
        "retrieval_query": _portable_clip(retrieval.get("query"), 300),
        "writeback_contract": portable_writeback_contract(),
        "context_pull_guidance": (
            "If you needed context Crowley did not include, list concrete pull "
            "candidates in context_pull_candidates (file paths, ticket ids, handoff "
            "topics). Do not paste secrets. Put sensitive personal content only in "
            "sparks with appropriate lane and sensitivity — it stays candidate until reviewed."
        ),
        "caps": {
            "max_chars": PORTABLE_PACKET_MAX_CHARS,
            "memories": PORTABLE_PACKET_MEMORY_CAP,
            "working_on": PORTABLE_PACKET_WORKING_CAP,
        },
    }

def _impl_render_portable_context_packet_markdown(packet: dict[str, object]) -> str:
    """Paste-ready markdown rendering of a portable context packet."""
    sections: list[str] = []

    def add(title: str, body: str) -> None:
        body = body.strip()
        if body:
            sections.append(f"## {title}\n\n{body}")

    identity = packet.get("identity")
    if isinstance(identity, dict):
        add(
            "Crowley identity",
            "\n".join(
                line
                for line in (
                    str(identity.get("crowley_role") or ""),
                    str(identity.get("terminal_role") or ""),
                    f"Authority: {identity.get('authority_order')}",
                )
                if line
            ),
        )

    world = packet.get("world")
    if isinstance(world, dict):
        state = world.get("state")
        lines: list[str] = []
        project = world.get("project")
        if isinstance(project, dict):
            lines.append(
                f"Project: {project.get('name')} ({project.get('slug')}) — "
                f"{project.get('status')}"
            )
        if isinstance(state, dict):
            for key, label in (
                ("phase", "Phase"),
                ("focus", "Focus"),
                ("current_risk", "Risk"),
                ("next_action", "Next action"),
                ("what_changed", "What changed"),
            ):
                value = state.get(key)
                if value:
                    lines.append(f"{label}: {value}")
        add("Current world", "\n".join(lines))

    work = packet.get("work")
    if isinstance(work, dict):
        lines = []
        contact = work.get("latest_agent_contact")
        if isinstance(contact, dict):
            lines.append(
                f"Latest agent contact: {contact.get('source')} "
                f"#{contact.get('memory_id')} — "
                f"{_portable_clip(contact.get('summary'), 140)}"
            )
        for ticket in work.get("working_on") or []:
            if not isinstance(ticket, dict):
                continue
            acceptance = ticket.get("acceptance") or []
            acc = ""
            if isinstance(acceptance, list) and acceptance:
                acc = f" · acceptance: {_portable_clip(acceptance[0], 100)}"
            lines.append(
                f"- #{ticket.get('id')} [{ticket.get('status')}] "
                f"{ticket.get('title')}{acc}"
            )
        for line in work.get("open_initiatives") or []:
            lines.append(f"- {line}")
        for line in work.get("in_the_air") or []:
            lines.append(f"- In the air: {line}")
        add("Active work", "\n".join(lines))

    guardrails = packet.get("guardrails")
    if isinstance(guardrails, dict):
        lines = []
        for decision in guardrails.get("recent_decisions") or []:
            if isinstance(decision, dict) and decision.get("summary"):
                detail = decision.get("detail")
                suffix = f" — {detail}" if detail else ""
                lines.append(f"- Decision: {decision['summary']}{suffix}")
        for constraint in guardrails.get("constraints") or []:
            if isinstance(constraint, dict) and constraint.get("summary"):
                lines.append(f"- Constraint: {constraint['summary']}")
        add("Guardrails", "\n".join(lines))

    memories = packet.get("memories")
    if isinstance(memories, list) and memories:
        lines = []
        for mem in memories:
            if not isinstance(mem, dict):
                continue
            reason = mem.get("inclusion_reason")
            suffix = f" ({reason})" if reason else ""
            lines.append(
                f"- [{mem.get('memory_type')}] {mem.get('text')}{suffix}"
            )
        query = packet.get("retrieval_query")
        if query:
            lines.insert(0, f"_Retrieval query: {query}_\n")
        add("Supporting memories", "\n".join(lines))

    contract = packet.get("writeback_contract")
    if isinstance(contract, dict):
        example = contract.get("example")
        example_json = json.dumps(example, indent=2) if example else "{}"
        add(
            "Writeback contract",
            "\n".join(
                [
                    str(contract.get("description") or ""),
                    "",
                    "Reply with a single fenced JSON block:",
                    "",
                    "```json",
                    example_json,
                    "```",
                ]
            ),
        )

    guidance = packet.get("context_pull_guidance")
    if guidance:
        add("Context pull guidance", str(guidance))

    header = (
        f"# Crowley portable context packet\n\n"
        f"_v{packet.get('packet_version')} · Crowley {packet.get('crowley_version')} · "
        f"surface: {packet.get('surface')} · generated: {packet.get('generated_at')}_\n"
    )
    markdown = header + "\n\n".join(sections) + "\n"
    max_chars = int(
        (packet.get("caps") or {}).get("max_chars") or PORTABLE_PACKET_MAX_CHARS
    )
    trimmed = False
    if len(markdown) > max_chars:
        markdown = (
            markdown[: max_chars - 64].rstrip()
            + "\n\n… _[packet trimmed to char budget]_\n"
        )
        trimmed = True
    packet["rendered_chars"] = len(markdown)
    packet["trimmed"] = trimmed
    return markdown

def _impl_parse_terminal_writeback(raw: str | dict[str, object]) -> TerminalWritebackParseResult:
    """
    Validate structured terminal writeback without mutating memory (V3.9.12 #77).
    do_not_save entries are parsed but flagged for discard — never persisted here.
    """
    errors: list[str] = []
    try:
        payload = (
            extract_terminal_writeback_json(raw)
            if isinstance(raw, str)
            else raw
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return TerminalWritebackParseResult(ok=False, errors=[str(exc)])

    if not isinstance(payload, dict):
        return TerminalWritebackParseResult(
            ok=False, errors=["writeback payload must be a JSON object"]
        )

    session_raw = payload.get("session")
    if not isinstance(session_raw, dict):
        errors.append("session is required and must be an object")
        session: dict[str, object] = {}
    else:
        session = session_raw

    summary = str(session.get("summary") or "").strip()
    if not summary:
        errors.append("session.summary is required")

    surface = str(session.get("surface") or "").strip().lower()
    model = str(session.get("model") or "").strip() or None
    provider = str(session.get("provider") or "").strip().lower() or None

    sparks_raw = payload.get("sparks")
    sparks: list[dict[str, object]] = []
    if sparks_raw is None:
        sparks_raw = []
    if not isinstance(sparks_raw, list):
        errors.append("sparks must be an array when present")
    else:
        for index, entry in enumerate(sparks_raw):
            normalized = _normalize_terminal_spark(entry, index, errors)
            if normalized is not None:
                sparks.append(normalized)

    decisions = _writeback_string_items(payload.get("decisions"), "decisions", errors)
    lessons = _writeback_string_items(payload.get("lessons"), "lessons", errors)
    open_loops = _writeback_string_items(payload.get("open_loops"), "open_loops", errors)
    corrections = _writeback_string_items(
        payload.get("corrections"), "corrections", errors
    )
    context_pull_candidates = _writeback_string_items(
        payload.get("context_pull_candidates"),
        "context_pull_candidates",
        errors,
    )
    do_not_save = _writeback_string_items(
        payload.get("do_not_save"), "do_not_save", errors
    )

    if errors:
        return TerminalWritebackParseResult(ok=False, errors=errors)

    normalized: dict[str, object] = {
        "format": PORTABLE_WRITEBACK_FORMAT,
        "session": {
            "summary": summary,
            "surface": surface or None,
            "model": model,
            "provider": provider,
        },
        "sparks": sparks,
        "decisions": decisions,
        "lessons": lessons,
        "open_loops": open_loops,
        "corrections": corrections,
        "context_pull_candidates": context_pull_candidates,
        "do_not_save": do_not_save,
        "do_not_save_persist": False,
    }
    return TerminalWritebackParseResult(ok=True, errors=[], writeback=normalized)

def _impl_ingest_terminal_writeback(
    raw: str | dict[str, object],
    *,
    project: str = DEFAULT_PROJECT_SLUG,
) -> dict[str, object]:
    """
    Persist validated portable terminal writeback (V3.9.12 #78).
    Session recap is an episodic receipt; sparks are staged candidates.
    do_not_save entries are skipped; raw transcripts are never saved here.
    """
    parsed = parse_terminal_writeback(raw)
    if not parsed.ok:
        return {"status": "error", "errors": parsed.errors}

    writeback = parsed.writeback
    assert writeback is not None
    session_raw = writeback.get("session")
    if not isinstance(session_raw, dict):
        return {"status": "error", "errors": ["session object missing after parse"]}

    project_row = get_project_by_slug(project) if project else get_active_project()
    if project_row is None:
        raise ValueError(f"project not found: {project}")
    project_id = int(project_row["id"])

    session_summary = str(session_raw.get("summary") or "").strip()
    # Treat omitted surface as chatgpt for portable Actions sessions so
    # downstream acceptance criteria sees the same normalized value.
    surface = str(session_raw.get("surface") or "chatgpt").strip().lower() or "chatgpt"
    normalized_session = dict(session_raw)
    normalized_session["surface"] = surface
    normalized_writeback = dict(writeback)
    normalized_writeback["session"] = normalized_session
    session_metadata = _portable_session_receipt_metadata(normalized_writeback)

    session_receipt_id = save_memory_item(
        "summary",
        session_summary,
        summary=f"Portable terminal session ({surface})",
        source=PORTABLE_TERMINAL_SOURCE,
        project_id=project_id,
        importance=3,
        confidence=0.85,
        pinned=False,
        status="active",
        metadata=session_metadata,
    )
    if session_receipt_id is None:
        record_system_metric("ingest_error", label=PORTABLE_TERMINAL_SOURCE)
        return {
            "status": "error",
            "errors": ["failed to save session receipt"],
            "session_receipt_id": None,
        }

    spark_ids: list[int] = []
    v4_spark_ids: list[int] = []
    v4_spark_actions: list[str] = []
    rejected_sparks: list[str] = []
    sparks_raw = writeback.get("sparks") or []
    assert isinstance(sparks_raw, list)

    conn = connect_db()
    try:
        for spark in sparks_raw:
            if not isinstance(spark, dict):
                rejected_sparks.append("invalid spark object")
                continue
            content = str(spark.get("content") or "").strip()
            sensitivity = str(spark.get("sensitivity") or "normal").lower()
            is_sensitive = sensitivity in {"sensitive", "high"}
            spark_metadata = _portable_spark_metadata(
                spark,
                session=normalized_session,
                session_receipt_id=int(session_receipt_id),
            )
            item_id = save_memory_item(
                "event",
                content,
                summary=str(spark.get("why_keep") or "").strip() or None,
                source=PORTABLE_TERMINAL_SOURCE,
                project_id=project_id,
                importance=2 if is_sensitive else 3,
                confidence=float(spark.get("confidence") or 0.5),
                pinned=False,
                status=PORTABLE_SPARK_STATUS,
                metadata=spark_metadata,
                write_action="portable.writeback.ingest",
                conn=conn,
            )
            if item_id is None:
                rejected_sparks.append(_truncate(content, 64))
                continue

            spark_ids.append(int(item_id))
            try:
                import portable_writeback_sparks_bridge

                upsert = portable_writeback_sparks_bridge.upsert_portable_spark_to_v4(
                    conn,
                    spark,
                    source_memory_item_id=int(item_id),
                    project_id=project_id,
                    session_receipt_id=int(session_receipt_id),
                    session=normalized_session,
                )
            except ValueError as exc:
                rejected_sparks.append(f"{_truncate(content, 48)}: {exc}")
                continue

            v4_spark_ids.append(int(upsert.spark_id))
            v4_spark_actions.append(str(upsert.action))
            attach_memory_item_metadata(
                int(item_id),
                {
                    "v4_spark_id": int(upsert.spark_id),
                    "v4_spark_action": str(upsert.action),
                },
                conn=conn,
            )
        conn.commit()
    finally:
        conn.close()

    do_not_save = writeback.get("do_not_save") or []
    skipped_do_not_save = (
        [str(item) for item in do_not_save] if isinstance(do_not_save, list) else []
    )

    record_system_metric("ingest_ok", label=PORTABLE_TERMINAL_SOURCE)
    return {
        "status": "ok",
        "session_receipt_id": int(session_receipt_id),
        "spark_ids": spark_ids,
        "v4_spark_ids": v4_spark_ids,
        "v4_spark_actions": v4_spark_actions,
        "rejected_sparks": rejected_sparks,
        "skipped_do_not_save": skipped_do_not_save,
        "metadata": session_metadata,
    }

def _impl_build_portable_writeback_acceptance_report(
    *,
    apply: bool = False,
    reviewer: str = "operator",
    session_receipt_id: int | None = None,
) -> dict[str, object]:
    """Analyze staged portable writeback sparks; optionally promote accepted rows."""
    conn = connect_db()
    try:
        sessions = list_portable_writeback_sessions(conn=conn)
        if session_receipt_id is not None:
            sessions = [
                session
                for session in sessions
                if int(session.get("session_receipt_id") or -1) == int(session_receipt_id)
            ]
        accepted: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        deduped: list[dict[str, object]] = []
        promoted_metadata: list[dict[str, object]] = []

        for index, session in enumerate(sessions, start=1):
            session_id = int(session["session_receipt_id"])
            session_row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (session_id,)
            ).fetchone()
            if session_row is None:
                continue
            spark_rows = _portable_session_sparks(conn, session_id)
            is_fixture = session["classification"] == "test_fixture"
            canonical_ids, duplicate_map = _canonical_staged_spark_ids(spark_rows)
            session["sort_rank"] = index

            for spark_row in spark_rows:
                spark_id = int(spark_row["id"])
                duplicate_master = next(
                    (
                        master_id
                        for master_id, dup_ids in duplicate_map.items()
                        if spark_id in dup_ids
                    ),
                    None,
                )
                if duplicate_master is not None:
                    evaluation = {
                        "memory_item_id": spark_id,
                        "session_receipt_id": session_id,
                        "content": str(spark_row["content"] or ""),
                        "accepted": False,
                        "rejection_reason": "duplicate_staged_row",
                        "duplicate_of": duplicate_master,
                        "criteria": {
                            "dedup_canonical": False,
                        },
                    }
                    deduped.append(evaluation)
                    if apply and str(spark_row["status"]) == PORTABLE_SPARK_STATUS:
                        conn.execute(
                            """
                            UPDATE memory_items
                            SET status = 'merged', merged_into_id = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (duplicate_master, _now_iso(), spark_id),
                        )
                        attach_memory_item_metadata(
                            spark_id,
                            {
                                "review_rejected_as": "duplicate_staged_row",
                                "merged_into_id": duplicate_master,
                                "reviewed_at": _now_iso(),
                                "reviewed_by": reviewer,
                            },
                            conn=conn,
                        )
                    continue

                evaluation = _evaluate_portable_spark_acceptance(
                    session_row=session_row,
                    spark_row=spark_row,
                    spark_rows=spark_rows,
                    is_test_fixture=is_fixture,
                    canonical_ids=canonical_ids,
                    conn=conn,
                )
                if evaluation["accepted"]:
                    accepted.append(evaluation)
                    if apply and str(spark_row["status"]) == PORTABLE_SPARK_STATUS:
                        conn.execute(
                            """
                            UPDATE memory_items
                            SET status = 'active', updated_at = ?
                            WHERE id = ?
                            """,
                            (_now_iso(), spark_id),
                        )
                        attach_memory_item_metadata(
                            spark_id,
                            {
                                "candidate": False,
                                "promoted_at": _now_iso(),
                                "promoted_by": reviewer,
                                "promotion_source": "portable_writeback_acceptance",
                                "acceptance_criteria": evaluation["criteria"],
                            },
                            conn=conn,
                        )
                        vector = embed_text(str(spark_row["content"]))
                        if vector and len(vector) == EMBED_DIM:
                            provider = _memory_embed_provider()
                            model_name = (
                                "text-embedding-3-small"
                                if provider == "openai"
                                else EMBED_MODEL_LOCAL
                            )
                            index_memory_embedding(
                                conn, spark_id, vector, model_name
                            )
                else:
                    rejected.append(evaluation)
                    if apply and str(spark_row["status"]) == PORTABLE_SPARK_STATUS:
                        conn.execute(
                            """
                            UPDATE memory_items
                            SET status = 'rejected', updated_at = ?
                            WHERE id = ?
                            """,
                            (_now_iso(), spark_id),
                        )
                        attach_memory_item_metadata(
                            spark_id,
                            {
                                "review_rejected_as": evaluation["rejection_reason"],
                                "reviewed_at": _now_iso(),
                                "reviewed_by": reviewer,
                            },
                            conn=conn,
                        )

            if not is_fixture and apply:
                meta = session["metadata"]
                assert isinstance(meta, dict)
                for field, memory_type in (
                    ("decisions", "decision"),
                    ("lessons", "lesson"),
                ):
                    values = meta.get(field) or []
                    if not isinstance(values, list):
                        continue
                    for bullet in values:
                        text = str(bullet or "").strip()
                        if not text:
                            continue
                        if _find_active_memory_by_content(
                            conn,
                            content=text,
                            project_id=int(session_row["project_id"])
                            if session_row["project_id"] is not None
                            else None,
                        ):
                            continue
                        item_id = save_memory_item(
                            memory_type,
                            text,
                            summary=text,
                            source=PORTABLE_TERMINAL_SOURCE,
                            project_id=int(session_row["project_id"])
                            if session_row["project_id"] is not None
                            else None,
                            importance=4 if memory_type == "decision" else 3,
                            confidence=0.85,
                            pinned=False,
                            status="active",
                            metadata={
                                "promoted_from": "session_metadata",
                                "session_receipt_id": session_id,
                                "surface": meta.get("surface"),
                                "promoted_at": _now_iso(),
                                "promoted_by": reviewer,
                            },
                            conn=conn,
                        )
                        if item_id is not None:
                            promoted_metadata.append(
                                {
                                    "memory_item_id": int(item_id),
                                    "session_receipt_id": session_id,
                                    "memory_type": memory_type,
                                    "content": text,
                                }
                            )

        if apply:
            conn.commit()

        for entry in accepted:
            spark_id = entry.get("memory_item_id")
            entry["destination_memory_id"] = int(spark_id) if spark_id is not None else None
            entry["promotion_lineage"] = {
                "source_session_id": entry.get("session_receipt_id"),
                "spark_id": spark_id,
            }
        for entry in deduped:
            dup = entry.get("duplicate_of")
            entry["destination_memory_id"] = int(dup) if dup is not None else None

        report = {
            "status": "ok",
            "generated_at": _now_iso(),
            "applied": apply,
            "reviewer": reviewer,
            "criteria": WRITEBACK_ACCEPTANCE_CRITERIA,
            "sessions": sessions,
            "accepted": accepted,
            "rejected": rejected,
            "deduped": deduped,
            "promoted_session_metadata": promoted_metadata,
            "counts": {
                "sessions": len(sessions),
                "accepted": len(accepted),
                "rejected": len(rejected),
                "deduped": len(deduped),
                "promoted_session_metadata": len(promoted_metadata),
            },
        }
        return report
    finally:
        conn.close()

def _impl_write_portable_writeback_acceptance_report(
    report: dict[str, object],
    *,
    path: Path | None = None,
) -> Path:
    target = path or WRITEBACK_ACCEPTANCE_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target

def _impl_load_portable_writeback_acceptance_report(
    *, path: Path | None = None
) -> dict[str, object] | None:
    target = path or WRITEBACK_ACCEPTANCE_REPORT_PATH
    if not target.is_file():
        return None
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None
