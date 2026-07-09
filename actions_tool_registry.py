"""V3.9.15 — ChatGPT Actions tool registry and read/write dispatch."""

from __future__ import annotations

from typing import Any, Callable

import crowley
import crowley_tools
import github_read
import tickets
from actions_tool_runtime import invoke_tool_handler, tool_timeout_seconds
from crowley_tools import ToolDefinition, ToolKind


_TOOLS: dict[str, ToolDefinition] = {}
_INITIALIZED = False


def register_tool(defn: ToolDefinition) -> None:
    if defn.name in _TOOLS:
        raise ValueError(f"tool already registered: {defn.name}")
    import workflow

    _TOOLS[defn.name] = crowley_tools.complete_tool_metadata(
        defn,
        timeout_seconds=tool_timeout_seconds(defn.name),
        workflow_tier=workflow.tool_tier(defn.name),
    )


def ensure_registry() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _register_v313_tools()
    _register_domain_read_tools()
    _register_inspect_tools()
    _register_planning_tools()
    _register_write_tools()
    _register_github_tools()
    _INITIALIZED = True


def list_tools(*, kind: ToolKind | None = None) -> list[ToolDefinition]:
    ensure_registry()
    tools = list(_TOOLS.values())
    if kind is not None:
        tools = [tool for tool in tools if tool.kind == kind]
    return sorted(tools, key=lambda tool: tool.name)


def catalog_payload() -> dict[str, object]:
    ensure_registry()
    import workflow

    tool_names = sorted(_TOOLS.keys())
    return {
        "version": crowley.CROWLEY_VERSION,
        "release_label": crowley.CROWLEY_RELEASE_LABEL,
        "catalog_schema": "actions_tool_catalog_v1",
        "tools": [
            crowley_tools.actions_catalog_entry(
                tool,
                tier=tool.workflow_tier or workflow.tool_tier(tool.name),
            )
            for tool in list_tools()
        ],
        "gateway": {
            "read": "POST /api/actions/read {\"tool\": \"...\", \"args\": {...}}",
            "write": "POST /api/actions/write {\"tool\": \"...\", \"args\": {...}}",
            "canonical": "Use POST /read and POST /write only; legacy GET/POST alias routes delegate to the same tools.",
        },
        "examples": {
            "writeback.ingest": {
                "tool": "writeback.ingest",
                "args": {
                    "writeback": {
                        "session": {"summary": "Session receipt summary"},
                        "sparks": [
                            {
                                "content": "Actionable spark content",
                                "lane": "work",
                                "why_keep": "Why this spark should persist",
                                "confidence": 0.9,
                                "sensitivity": "normal",
                            }
                        ],
                    }
                },
            },
            "handoff.ingest": {
                "tool": "handoff.ingest",
                "args": {
                    "handoff_type": "architect_handoff",
                    "content": "# Crowley Handoff\\n\\n## Summary\\n- ...",
                },
            },
            "retrieve.search": {
                "tool": "retrieve.search",
                "args": {
                    "q": "what changed after the vec0 fix",
                    "limit": 5,
                },
            },
            "ticket.get": {
                "tool": "ticket.get",
                "args": {"ticket_id": 249},
            },
            "ticket.list": {
                "tool": "ticket.list",
                "args": {"status": "open", "limit": 5},
            },
        },
        "timeouts_seconds": {
            tool.name: int(tool.timeout_seconds or tool_timeout_seconds(tool.name))
            for tool in list_tools()
        },
        "workflow": workflow.workflow_enforcement_payload(tool_names=tool_names),
    }


def sync_tool_catalog_payload() -> dict[str, object]:
    """Authoritative tool schemas embedded in agent.sync (same registry as GET /catalog)."""
    payload = catalog_payload()
    return {
        "version": payload.get("version"),
        "release_label": payload.get("release_label"),
        "catalog_schema": payload.get("catalog_schema"),
        "source": "GET /api/actions/catalog",
        "tool_count": len(payload.get("tools") or []),
        "tools": payload.get("tools") or [],
        "examples": payload.get("examples") or {},
        "gateway": payload.get("gateway") or {},
        "timeouts_seconds": payload.get("timeouts_seconds") or {},
    }


def dispatch(
    kind: ToolKind,
    tool: str,
    args: object | None,
    *,
    session_key: str | None = None,
    agent_id: str | None = None,
) -> tuple[dict[str, object], int]:
    ensure_registry()
    name = str(tool or "").strip()
    if not name:
        return _error("tool_required", "tool name is required", 400)

    defn = _TOOLS.get(name)
    if defn is None:
        return _error("unknown_tool", f"unknown tool: {name}", 404)
    if defn.kind != kind:
        return _error(
            "wrong_gateway",
            f"tool {name} must be invoked via POST /api/actions/{defn.kind}",
            400,
        )

    import agent_identity
    import workflow

    session = workflow.normalize_session_key(session_key)
    allowed, boot_message = workflow.check_boot_gate(session, name)
    if not allowed and boot_message:
        return _error("boot_required", boot_message, 428)

    resolved_agent = agent_identity.normalize_agent_id(agent_id, fallback_source="chatgpt")
    if kind == "write":
        perm_ok, perm_message = agent_identity.check_write_permission(resolved_agent, name)
        if not perm_ok and perm_message:
            return _error("permission_denied", perm_message, 403)

    import agent_behavior

    query_text = None
    if isinstance(args, dict):
        query_text = (
            str(args.get("query") or args.get("q") or args.get("intent") or "")
            or None
        )

    import system_integrity

    gates_ok, error_code, http_status, gate_extra = system_integrity.run_enforcement_gates(
        session,
        name,
        query_text=query_text,
        kind=kind,
        agent_id=resolved_agent,
        boot_allowed=allowed,
        boot_message=boot_message if not allowed else None,
    )
    if not gates_ok and error_code:
        message = str(gate_extra.pop("message", error_code))
        return _error(error_code, message, http_status, **gate_extra)

    if args is not None and not isinstance(args, dict):
        return _error("invalid_args", "args must be a JSON object", 400)
    normalized_args: dict[str, Any] = dict(args) if isinstance(args, dict) else {}
    if "session_key" not in normalized_args:
        normalized_args["session_key"] = session
    if name == "inspect.retrieval_observability" and "session_key" not in normalized_args:
        normalized_args["session_key"] = session
    dispatch_id = system_integrity.next_dispatch_id()
    agent_behavior.begin_dispatch(session, dispatch_id)

    try:
        body, status, runtime_error = invoke_tool_handler(name, defn.handler, normalized_args)
        if runtime_error == "server_busy":
            return _error(
                "server_busy",
                "Crowley is processing other heavy Actions requests; retry shortly.",
                503,
            )
        if runtime_error == "tool_timeout":
            return _error(
                "tool_timeout",
                f"{name} exceeded {tool_timeout_seconds(name)}s; retry or narrow the request.",
                504,
                tool=name,
                timeout_seconds=tool_timeout_seconds(name),
            )
    except ValueError as exc:
        return _error("invalid_args", str(exc), 400)
    except LookupError as exc:
        return _error("not_found", str(exc), 404)
    if not isinstance(body, dict):
        body = {"result": body}
    intent = normalized_args.get("intent")
    trigger_rule = None
    if isinstance(gate_extra, dict) and gate_extra.get("triggering_rule"):
        trigger_rule = str(gate_extra.get("triggering_rule"))
    resolved_status = 200 if status is None else int(status)
    system_integrity.record_dispatch_observability(
        session,
        name,
        dispatch_id=dispatch_id,
        query_text=query_text,
        intent=str(intent) if intent else None,
        triggering_rule=trigger_rule,
        http_status=resolved_status,
    )
    if name == "agent.sync" and isinstance(body, dict):
        body = agent_behavior.attach_agent_sync_runtime(
            session,
            dispatch_id,
            body,
            tool_names=sorted(_TOOLS.keys()),
        )
        body = crowley.finalize_agent_sync_bundle(body)
    return body, resolved_status


def _error(code: str, message: str, status: int, **extra: object) -> tuple[dict[str, object], int]:
    payload: dict[str, object] = {"ok": False, "error": code, "message": message}
    if extra:
        payload.update(extra)
    return payload, status


def _optional_str(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_handoff_content(args: dict[str, Any]) -> str | None:
    """Canonical handoff body is ``content``; ``details`` and ``summary`` are accepted aliases."""
    content = _optional_str(args, "content") or _optional_str(args, "details")
    if content:
        return content
    return _optional_str(args, "summary")


def _search_query(args: dict[str, Any]) -> str | None:
    """Canonical retrieval arg is ``q``; ``query`` is accepted for client compatibility."""
    return _optional_str(args, "q") or _optional_str(args, "query")


def _optional_int(args: dict[str, Any], key: str, default: int) -> int:
    value = args.get(key, default)
    return max(1, min(int(value), 200))


def _optional_bool(args: dict[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _require_id(args: dict[str, Any], key: str = "id") -> int:
    if args.get(key) is None:
        raise ValueError(f"{key} is required")
    try:
        return int(args[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _require_entity_id(
    args: dict[str, Any],
    *,
    key: str = "id",
    aliases: tuple[str, ...] = (),
) -> int:
    """Resolve an entity id from canonical key or accepted aliases."""
    for name in (key, *aliases):
        if args.get(name) is None:
            continue
        try:
            return int(args[name])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc
    alias_hint = f" or {aliases[0]}" if aliases else ""
    raise ValueError(f"{key}{alias_hint} is required")


def _list_result(items: list[dict[str, object]], total: int, limit: int, offset: int) -> dict[str, object]:
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# --- V3.9.13 legacy tool handlers ---


def _handle_context_get(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    q = _optional_str(args, "q") or crowley.CONTEXT_DEFAULT_QUERY
    limit = _optional_int(args, "limit", 8)
    limit = min(limit, 50)
    project = _optional_str(args, "project")
    depth = _optional_str(args, "depth") or "medium"
    debug = bool(args.get("debug"))
    try:
        bundle = crowley.build_context_bundle(
            q=q,
            limit=limit,
            project_slug=project,
            depth=depth,
            debug=debug,
        )
    except ValueError as exc:
        return {"error": str(exc)}, 404
    return bundle, None


def _handle_retrieve_search(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    q = _search_query(args)
    if not q:
        raise ValueError("q is required")
    limit = min(_optional_int(args, "limit", 8), 50)
    depth = _optional_str(args, "depth") or "medium"
    debug = bool(args.get("debug"))
    return crowley.retrieve_memories_api(
        q=q,
        limit=limit,
        depth=depth,
        debug=debug,
    ), None


def _handle_portable_packet(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    project = _optional_str(args, "project")
    try:
        packet = crowley.build_portable_context_packet("chatgpt", project_slug=project)
        markdown = crowley.render_portable_context_packet_markdown(packet)
    except ValueError as exc:
        return {"error": str(exc)}, 404
    return {
        "packet": packet,
        "markdown": markdown,
        "char_count": len(markdown),
        "trimmed": bool(packet.get("trimmed")),
    }, None


def _handle_writeback_parse(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    writeback = args.get("writeback")
    text = _optional_str(args, "text")
    if writeback is not None:
        result = crowley.parse_terminal_writeback(writeback)
    elif text:
        result = crowley.parse_terminal_writeback(text)
    else:
        return {"ok": False, "errors": ["text or writeback object is required"]}, 400
    if not result.ok:
        return {"ok": False, "errors": result.errors}, 400
    return {"ok": True, "writeback": result.writeback}, None


def _writeback_ingest_args_error(args: dict[str, Any]) -> str | None:
    if args.get("writeback") is not None or _optional_str(args, "text"):
        return None
    if any(key in args for key in ("content", "type", "metadata", "summary")):
        return (
            "writeback.ingest expects args.writeback (portable terminal packet) or args.text, "
            "not handoff-style content/type/metadata. Use handoff.ingest for markdown handoffs."
        )
    return "text or writeback object is required"


def _handle_writeback_ingest(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    writeback = args.get("writeback")
    text = _optional_str(args, "text")
    project = _optional_str(args, "project") or "crowley"
    if writeback is None and not text:
        message = _writeback_ingest_args_error(args) or "text or writeback object is required"
        return {"status": "error", "errors": [message]}, 400
    try:
        if writeback is not None:
            result = crowley.ingest_terminal_writeback(writeback, project=project)
        else:
            result = crowley.ingest_terminal_writeback(text, project=project)
    except ValueError as exc:
        return {"status": "error", "errors": [str(exc)]}, 404
    if result.get("status") != "ok":
        return result, 400
    session_receipt_id = result.get("session_receipt_id")
    if session_receipt_id is not None:
        try:
            acceptance = crowley.auto_promote_portable_writeback_session(
                int(session_receipt_id),
                reviewer="chatgpt_actions_api",
            )
            result["auto_promotion"] = {
                "applied": True,
                "accepted": int(acceptance.get("counts", {}).get("accepted", 0)),
                "rejected": int(acceptance.get("counts", {}).get("rejected", 0)),
                "deduped": int(acceptance.get("counts", {}).get("deduped", 0)),
            }
        except Exception as exc:
            result["auto_promotion"] = {"applied": False, "error": str(exc)}
    return crowley.enrich_writeback_ingest_result(result), 201


def _handle_writeback_acceptance(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    refresh = _optional_bool(args, "refresh", False)
    apply = _optional_bool(args, "apply", False)
    if refresh or apply:
        report = crowley.build_portable_writeback_acceptance_report(
            apply=apply,
            reviewer="chatgpt_actions_api",
        )
        report_path = crowley.write_portable_writeback_acceptance_report(report)
        report["report_path"] = str(report_path)
        return report, None
    cached = crowley.load_portable_writeback_acceptance_report()
    if cached is not None:
        return cached, None
    report = crowley.build_portable_writeback_acceptance_report(apply=False)
    report_path = crowley.write_portable_writeback_acceptance_report(report)
    report["report_path"] = str(report_path)
    return report, None


def _register_v313_tools() -> None:
    register_tool(
        ToolDefinition(
            name="context.get",
            kind="read",
            description="Read Crowley context bundle (project state, tickets, knowledge, retrieval).",
            args_schema={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Query for knowledge and retrieval scoring"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "project": {"type": "string", "description": "Optional project slug"},
                    "depth": {
                        "type": "string",
                        "enum": ["light", "medium", "deep"],
                        "description": "Context depth mode (default: medium)",
                    },
                    "debug": {
                        "type": "boolean",
                        "description": "Include suppressed raw duplicates when true",
                    },
                },
            },
            handler=_handle_context_get,
        )
    )
    register_tool(
        ToolDefinition(
            name="retrieve.search",
            kind="read",
            description="Hybrid semantic memory search.",
            args_schema={
                "type": "object",
                "required": ["q"],
                "properties": {
                    "q": {"type": "string", "description": "Search query (canonical)"},
                    "query": {
                        "type": "string",
                        "description": "Alias for q (accepted for compatibility)",
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "depth": {
                        "type": "string",
                        "enum": ["light", "medium", "deep"],
                        "description": "Context depth mode (default: medium)",
                    },
                    "debug": {
                        "type": "boolean",
                        "description": "Include suppressed raw duplicates when true",
                    },
                },
            },
            handler=_handle_retrieve_search,
        )
    )
    register_tool(
        ToolDefinition(
            name="portable.packet",
            kind="read",
            description="Export portable context packet markdown for session start.",
            args_schema={
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                },
            },
            handler=_handle_portable_packet,
        )
    )
    register_tool(
        ToolDefinition(
            name="writeback.parse",
            kind="write",
            description="Validate terminal writeback JSON without persisting.",
            args_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "writeback": {"type": "object"},
                },
            },
            handler=_handle_writeback_parse,
        )
    )
    register_tool(
        ToolDefinition(
            name="writeback.ingest",
            kind="write",
            description=(
                "Persist session receipt and spark candidates via args.writeback; "
                "accepted normal sparks auto-promote to active for retrieval."
            ),
            args_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "writeback": {"type": "object"},
                    "project": {"type": "string", "default": "crowley"},
                },
            },
            handler=_handle_writeback_ingest,
        )
    )
    register_tool(
        ToolDefinition(
            name="writeback.acceptance",
            kind="read",
            description="Read portable writeback acceptance report; set refresh/apply to rebuild.",
            args_schema={
                "type": "object",
                "properties": {
                    "refresh": {"type": "boolean", "default": False},
                    "apply": {"type": "boolean", "default": False},
                },
            },
            handler=_handle_writeback_acceptance,
        )
    )


def _handle_memory_get(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    memory_id = _require_entity_id(args, aliases=("memory_id",))
    item = crowley.get_memory_item_api_by_id(memory_id)
    if item is None:
        raise LookupError(f"memory not found: {memory_id}")
    return item, None


def _handle_memory_list(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    limit = min(_optional_int(args, "limit", 10), 50)
    offset = max(0, int(args.get("offset", 0)))
    rows, total = crowley.list_memory_items(
        q=_optional_str(args, "q"),
        source=_optional_str(args, "source"),
        memory_type=_optional_str(args, "memory_type"),
        status=_optional_str(args, "status") or "active",
        limit=limit,
        offset=offset,
    )
    items = [crowley._memory_item_api_dict(row) for row in rows]
    return _list_result(items, total, limit, offset), None


def _handle_ticket_get(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    ticket_id = _require_entity_id(args, aliases=("ticket_id",))
    include_memories = bool(args.get("include_memories"))
    memory_limit = min(_optional_int(args, "memory_limit", 50), 200)
    detail = tickets.get_ticket_detail(
        ticket_id,
        include_memories=include_memories,
        memory_limit=memory_limit,
    )
    if detail is None:
        raise LookupError(f"ticket not found: {ticket_id}")
    return detail, None


def _handle_ticket_list(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    project = crowley.get_active_project()
    project_id = int(project["id"]) if project is not None else None
    status = _optional_str(args, "status") or "open"
    limit = min(_optional_int(args, "limit", 50), 200)
    offset = max(0, int(args.get("offset", 0)))
    open_only = status.strip().lower() == "open"
    status_filter = None if open_only else status
    sort = _optional_str(args, "sort") or "newest"
    rows = tickets.list_tickets(
        project_id=project_id,
        status=status_filter,
        open_only=open_only,
        assignee=_optional_str(args, "assignee"),
        priority_max=int(args["priority"]) if args.get("priority") is not None else None,
        parent_id=int(args["parent_id"]) if args.get("parent_id") is not None else None,
        limit=limit,
        offset=offset,
        sort=sort,
    )
    total = tickets.count_tickets(
        project_id=project_id,
        status=None if open_only else status_filter,
        open_only=open_only,
        assignee=_optional_str(args, "assignee"),
    )
    items = [crowley.row_to_dict(row) for row in rows]
    return _list_result(items, total, limit, offset), None


def _handle_session_get(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    detail = crowley.get_portable_session_api(_require_id(args))
    if detail is None:
        raise LookupError(f"session not found: {args['id']}")
    return detail, None


def _handle_session_list(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    limit = min(_optional_int(args, "limit", 10), 50)
    offset = max(0, int(args.get("offset", 0)))
    rows, total = crowley.list_memory_items(
        source=crowley.PORTABLE_TERMINAL_SOURCE,
        memory_type="summary",
        status=_optional_str(args, "status") or "active",
        limit=limit,
        offset=offset,
    )
    items = [crowley._memory_item_api_dict(row) for row in rows]
    return _list_result(items, total, limit, offset), None


def _handle_spark_get(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    item = crowley.get_memory_item_api_by_id(_require_id(args))
    if item is None:
        raise LookupError(f"spark not found: {args['id']}")
    if str(item.get("memory_type")) != "event":
        raise LookupError(f"spark not found: {args['id']}")
    return item, None


def _handle_spark_list(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    limit = min(_optional_int(args, "limit", 10), 50)
    offset = max(0, int(args.get("offset", 0)))
    status = _optional_str(args, "status") or "all"
    rows, total = crowley.list_memory_items(
        source=_optional_str(args, "source") or crowley.PORTABLE_TERMINAL_SOURCE,
        memory_type="event",
        status=status,
        limit=limit,
        offset=offset,
    )
    items = [crowley._memory_item_api_dict(row) for row in rows]
    return _list_result(items, total, limit, offset), None


def _handle_decision_get(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    item = crowley.get_decision_api_by_id(_require_id(args))
    if item is None:
        raise LookupError(f"decision not found: {args['id']}")
    return item, None


def _handle_decision_list(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    project = crowley.get_active_project()
    if project is None:
        return _list_result([], 0, 10, 0), None
    limit = min(_optional_int(args, "limit", 10), 50)
    rows = crowley.list_decisions(int(project["id"]), limit=limit)
    items = [crowley.row_to_dict(row) for row in rows]
    return {"items": items, "total": len(items), "limit": limit, "offset": 0}, None


def _is_handoff_memory(item: dict[str, object]) -> bool:
    memory_type = str(item.get("memory_type") or "")
    content = str(item.get("content") or "")
    if memory_type not in {"project_update", "qa_result", "event"}:
        return False
    lowered = content.lower()
    return "handoff" in lowered or lowered.startswith("# crowley handoff")


def _handle_handoff_get(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    item = crowley.get_memory_item_api_by_id(_require_id(args))
    if item is None or not _is_handoff_memory(item):
        raise LookupError(f"handoff not found: {args['id']}")
    return item, None


def _handle_handoff_list(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    limit = min(_optional_int(args, "limit", 20), 50)
    rows = crowley.list_recent_agent_events(limit=limit)
    items = [crowley._memory_item_api_dict(row) for row in rows]
    if _optional_str(args, "handoffs_only"):
        items = [item for item in items if _is_handoff_memory(item)]
    return {"items": items, "total": len(items), "limit": limit, "offset": 0}, None


def _handle_cognitive_context(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    import context_orchestration

    q = _optional_str(args, "q") or ""
    lane = _optional_str(args, "lane")
    limit = min(_optional_int(args, "limit", 12), 50)
    project = _optional_str(args, "project")
    depth = _optional_str(args, "depth") or "medium"
    debug = bool(args.get("debug"))
    try:
        return (
            context_orchestration.build_cognitive_context(
                q,
                lanes=lane,
                limit=limit,
                project=project,
                depth=depth,
                debug=debug,
            ),
            None,
        )
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}, 400


def _register_domain_read_tools() -> None:
    _domain_tools = [
        (
            "memory.get",
            "Get one memory item by id (any status).",
            {
                "properties": {
                    "id": {"type": "integer", "description": "Memory id (canonical)"},
                    "memory_id": {"type": "integer", "description": "Alias for id"},
                }
            },
            _handle_memory_get,
        ),
        ("memory.list", "List memory items with filters.", {"properties": {"q": {"type": "string"}, "source": {"type": "string"}, "memory_type": {"type": "string"}, "status": {"type": "string"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}}, _handle_memory_list),
        ("ticket.get", "Get ticket detail with events, linked handoff, and optional linked memories.", {"properties": {"id": {"type": "integer", "description": "Ticket id (canonical)"}, "ticket_id": {"type": "integer", "description": "Alias for id"}, "include_memories": {"type": "boolean", "description": "When true, include linked_memories grouped by type"}, "memory_limit": {"type": "integer", "description": "Cap linked memories returned (default 50, max 200)"}}}, _handle_ticket_get),
        ("ticket.list", "List tickets for active project (default sort: newest first).", {"properties": {"status": {"type": "string", "description": "open (default), all, done, cancelled, or comma-separated"}, "assignee": {"type": "string"}, "priority": {"type": "integer"}, "parent_id": {"type": "integer"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}, "sort": {"type": "string", "description": "newest (default), oldest, priority, or updated"}}}, _handle_ticket_list),
        ("session.get", "Get portable session receipt and linked sparks.", {"required": ["id"], "properties": {"id": {"type": "integer"}}}, _handle_session_get),
        ("session.list", "List portable terminal session receipts.", {"properties": {"status": {"type": "string"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}}, _handle_session_list),
        ("spark.get", "Get spark (memory event) by id.", {"required": ["id"], "properties": {"id": {"type": "integer"}}}, _handle_spark_get),
        ("spark.list", "List portable spark candidates/events.", {"properties": {"status": {"type": "string"}, "source": {"type": "string"}, "limit": {"type": "integer"}, "offset": {"type": "integer"}}}, _handle_spark_list),
        ("decision.get", "Get decision row by id.", {"required": ["id"], "properties": {"id": {"type": "integer"}}}, _handle_decision_get),
        ("decision.list", "List recent decisions for active project.", {"properties": {"limit": {"type": "integer"}}}, _handle_decision_list),
        ("handoff.get", "Get agent handoff memory by id.", {"required": ["id"], "properties": {"id": {"type": "integer"}}}, _handle_handoff_get),
        ("handoff.list", "List recent agent events / handoffs.", {"properties": {"limit": {"type": "integer"}, "handoffs_only": {"type": "boolean"}}}, _handle_handoff_list),
        (
            "cognitive.context",
            "Read V4 cognitive context from ranked sparks and active patterns.",
            {
                "properties": {
                    "q": {"type": "string"},
                    "lane": {"type": "string"},
                    "limit": {"type": "integer"},
                    "project": {"type": "string"},
                    "depth": {
                        "type": "string",
                        "enum": ["light", "medium", "deep"],
                    },
                    "debug": {"type": "boolean"},
                }
            },
            _handle_cognitive_context,
        ),
    ]
    for name, description, args_schema, handler in _domain_tools:
        register_tool(
            ToolDefinition(
                name=name,
                kind="read",
                description=description,
                args_schema={"type": "object", **args_schema},
                handler=handler,
            )
        )


def _register_inspect_tools() -> None:
    def _handle_inspect_recent_ingests(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        limit = min(_optional_int(args, "limit", 20), 50)
        items = crowley.list_recent_portable_ingests(limit=limit)
        return {"items": items, "total": len(items), "limit": limit}, None

    def _handle_inspect_recent_updates(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        limit = min(_optional_int(args, "limit", 20), 50)
        items = crowley.list_recent_memory_updates(limit=limit)
        return {"items": items, "total": len(items), "limit": limit}, None

    def _handle_inspect_writeback_result(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        result = crowley.build_writeback_inspect_result(_require_id(args, "session_receipt_id"))
        if result is None:
            raise LookupError(f"writeback result not found: {args.get('session_receipt_id')}")
        return result, None

    def _handle_memory_lineage(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        lineage = crowley.build_memory_lineage(_require_id(args))
        if lineage is None:
            raise LookupError(f"memory not found: {args['id']}")
        return lineage, None

    def _handle_memory_why_retrieved(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        explanation = crowley.explain_memory_in_retrieval(
            _require_id(args),
            q=_optional_str(args, "q"),
        )
        if explanation is None:
            raise LookupError(f"memory not found: {args['id']}")
        return explanation, None

    def _handle_inspect_audit_list(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        import write_audit

        entity_type = _optional_str(args, "entity_type")
        entity_id = int(args["entity_id"]) if args.get("entity_id") is not None else None
        limit = min(_optional_int(args, "limit", 20), 100)
        offset = max(0, int(args.get("offset", 0)))
        items, total = write_audit.list_write_audit_log(
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "total": total, "limit": limit, "offset": offset}, None

    def _handle_inspect_retrieval_observability(
        args: dict[str, Any],
    ) -> tuple[dict[str, Any], int | None]:
        import agent_behavior

        session_key = _optional_str(args, "session_key") or "default"
        limit = min(_optional_int(args, "limit", 20), 100)
        payload = agent_behavior.retrieval_observability(session_key, limit=limit)
        intent = _optional_str(args, "intent")
        if intent:
            payload["recommended_tools"] = agent_behavior.tools_for_intent(intent)
            payload["validation"] = agent_behavior.validate_retrieval_state(
                session_key, intent=intent
            )
        return payload, None

    def _handle_inspect_invariant_checks(
        args: dict[str, Any],
    ) -> tuple[dict[str, Any], int | None]:
        import system_integrity
        import workflow

        context = _optional_str(args, "context") or "qa"
        if context not in {"sync", "write", "qa", "dispatch"}:
            raise ValueError("context must be sync, write, qa, or dispatch")
        session_key = _optional_str(args, "session_key") or workflow.normalize_session_key(None)
        limit = min(_optional_int(args, "limit", 50), 200)
        parity = system_integrity.check_state_parity(session_key=session_key, limit=limit)
        invariants = system_integrity.run_invariant_checks(context, session_key=session_key)
        handoff_parity = parity.get("handoff_ticket_parity", {})
        payload: dict[str, object] = {
            "parity": parity,
            "invariants": invariants,
            "handoff_ticket_parity": {
                "counts": {
                    "handoffs_checked": handoff_parity.get("handoffs_checked", 0),
                    "missing_count": handoff_parity.get("missing_count", 0),
                    "duplicate_group_count": handoff_parity.get("duplicate_group_count", 0),
                },
                "parity_ok": handoff_parity.get("parity_ok"),
                "report": handoff_parity,
            },
        }
        if _optional_bool(args, "reconcile_preview", default=False):
            import handoff_ticket_bridge

            payload["reconcile_preview"] = handoff_ticket_bridge.reconcile_handoff_ticket_parity(
                limit=limit,
                dry_run=True,
            )
        return payload, None

    def _handle_memory_lifecycle_cleanup(
        args: dict[str, Any],
    ) -> tuple[dict[str, Any], int | None]:
        import memory_quality

        dry_run = not _optional_bool(args, "apply", default=False)
        return memory_quality.run_minimal_lifecycle_cleanup(dry_run=dry_run), None

    inspect_tools = [
        (
            "inspect.recent_ingests",
            "List recent portable terminal writeback ingests.",
            {"properties": {"limit": {"type": "integer"}}},
            _handle_inspect_recent_ingests,
        ),
        (
            "inspect.recent_updates",
            "List recently updated memory items.",
            {"properties": {"limit": {"type": "integer"}}},
            _handle_inspect_recent_updates,
        ),
        (
            "inspect.writeback_result",
            "Inspect writeback ingest result for a session receipt id.",
            {"required": ["session_receipt_id"], "properties": {"session_receipt_id": {"type": "integer"}}},
            _handle_inspect_writeback_result,
        ),
        (
            "memory.lineage",
            "Memory lineage including merge target and source session.",
            {"required": ["id"], "properties": {"id": {"type": "integer"}}},
            _handle_memory_lineage,
        ),
        (
            "memory.why_retrieved",
            "Explain why a memory appears in retrieval for a query.",
            {"required": ["id"], "properties": {"id": {"type": "integer"}, "q": {"type": "string"}}},
            _handle_memory_why_retrieved,
        ),
        (
            "inspect.audit_list",
            "List append-only write audit log entries (memory, tickets, handoffs).",
            {
                "properties": {
                    "entity_type": {"type": "string", "enum": ["memory_item", "ticket", "handoff"]},
                    "entity_id": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                }
            },
            _handle_inspect_audit_list,
        ),
        (
            "inspect.retrieval_observability",
            "Retrieval/chaining observability log for a session (tools called, depth, validation).",
            {
                "properties": {
                    "session_key": {"type": "string"},
                    "intent": {"type": "string"},
                    "limit": {"type": "integer"},
                }
            },
            _handle_inspect_retrieval_observability,
        ),
        (
            "inspect.invariant_checks",
            "Run system integrity invariant checks and state parity report.",
            {
                "properties": {
                    "context": {"type": "string", "enum": ["sync", "write", "qa", "dispatch"]},
                    "session_key": {"type": "string"},
                    "limit": {"type": "integer"},
                    "reconcile_preview": {"type": "boolean"},
                }
            },
            _handle_inspect_invariant_checks,
        ),
        (
            "memory.lifecycle_cleanup",
            "Minimal memory lifecycle cleanup — merge duplicates and mark stale (dry-run default).",
            {"properties": {"apply": {"type": "boolean"}}},
            _handle_memory_lifecycle_cleanup,
        ),
    ]
    for name, description, args_schema, handler in inspect_tools:
        register_tool(
            ToolDefinition(
                name=name,
                kind="read",
                description=description,
                args_schema={"type": "object", **args_schema},
                handler=handler,
            )
        )


def _register_planning_tools() -> None:
    def _handle_agent_sync(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        agent = _optional_str(args, "agent") or "chatgpt"
        limit = min(_optional_int(args, "limit", 20), 50)
        return crowley.build_agent_sync_bundle(agent=agent, limit=limit), None

    def _handle_agent_deep_sync(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        import agent_sync_envelope

        agent = _optional_str(args, "agent") or "chatgpt"
        section = _optional_str(args, "section")
        if not section:
            raise ValueError("section is required")
        cursor = _optional_str(args, "cursor")
        scope = _optional_str(args, "scope") or "open"
        limit = min(_optional_int(args, "limit", 20), 50)
        try:
            return (
                agent_sync_envelope.build_deep_sync_page(
                    agent,
                    section,
                    cursor=cursor,
                    limit=limit,
                    scope=scope,
                ),
                None,
            )
        except ValueError as exc:
            return {"status": "error", "error": str(exc)}, 400

    def _handle_planning_task_frame(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        project = crowley.get_active_project()
        project_id = int(project["id"]) if project is not None else None
        agent = _optional_str(args, "agent") or "chatgpt"
        return crowley.build_task_frame_context(project_id, agent), None

    def _handle_planning_ticket(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        bundle = crowley.build_planning_ticket_bundle(_require_id(args))
        if bundle is None:
            raise LookupError(f"ticket not found: {args['id']}")
        return bundle, None

    def _handle_planning_release(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        del args
        return crowley.build_release_planning_bundle(), None

    def _handle_qa_bundle(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        del args
        return crowley.build_qa_visibility_bundle(), None

    planning_tools = [
        (
            "agent.sync",
            "Agent sync bundle (Codex --before equivalent).",
            {"properties": {"agent": {"type": "string", "default": "chatgpt"}, "limit": {"type": "integer"}}},
            _handle_agent_sync,
        ),
        (
            "agent.deep_sync",
            "Paginated deep sync for one agent.sync section (handoffs, tickets, memory, ...).",
            {
                "required": ["section"],
                "properties": {
                    "agent": {"type": "string", "default": "chatgpt"},
                    "section": {"type": "string"},
                    "scope": {
                        "type": "string",
                        "description": "For section=tickets: open (default), history (all oldest-first), closed",
                        "enum": ["open", "history", "closed"],
                    },
                    "cursor": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
            _handle_agent_deep_sync,
        ),
        (
            "planning.task_frame",
            "Task frame brief for an agent.",
            {"properties": {"agent": {"type": "string", "default": "chatgpt"}}},
            _handle_planning_task_frame,
        ),
        (
            "planning.ticket",
            "Ticket planning bundle with task frame context.",
            {"required": ["id"], "properties": {"id": {"type": "integer"}}},
            _handle_planning_ticket,
        ),
        (
            "planning.release",
            "Bounded release/onboarding doc excerpts and live state.",
            {"properties": {}},
            _handle_planning_release,
        ),
        (
            "qa.bundle",
            "QA visibility: version, runtime, hygiene, ticket counts.",
            {"properties": {}},
            _handle_qa_bundle,
        ),
    ]
    for name, description, args_schema, handler in planning_tools:
        register_tool(
            ToolDefinition(
                name=name,
                kind="read",
                description=description,
                args_schema={"type": "object", **args_schema},
                handler=handler,
            )
        )


def _register_write_tools() -> None:
    def _handle_ticket_create(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        title = _optional_str(args, "title")
        if not title:
            raise ValueError("title is required")
        result = tickets.create_ticket(
            title,
            description=_optional_str(args, "description") or "",
            assignee=_optional_str(args, "assignee") or "cursor",
            priority=int(args.get("priority", 2)),
            parent_id=int(args["parent_id"]) if args.get("parent_id") is not None else None,
            source="chatgpt",
            actor="chatgpt",
        )
        return result, 201

    def _handle_ticket_update(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        ticket_id = _require_entity_id(args, aliases=("ticket_id",))
        result = tickets.update_ticket(
            ticket_id,
            actor="chatgpt",
            status=_optional_str(args, "status"),
            assignee=_optional_str(args, "assignee"),
            comment=_optional_str(args, "comment"),
            linked_memory_id=int(args["linked_memory_id"])
            if args.get("linked_memory_id") is not None
            else None,
        )
        return result, None

    def _handle_ticket_cancel(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        ticket_id = _require_entity_id(args, aliases=("ticket_id",))
        comment = _optional_str(args, "comment")
        if not comment:
            raise ValueError("comment is required")
        result = tickets.cancel_ticket(ticket_id, actor="chatgpt", comment=comment)
        return {"ok": True, **result}, None

    def _handle_handoff_ingest(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        import workflow

        content = _resolve_handoff_content(args)
        if not content:
            raise ValueError("content is required")
        handoff_type = (
            _optional_str(args, "handoff_type")
            or _optional_str(args, "type")
            or "architect_handoff"
        )
        if handoff_type not in {"architect_handoff", "note"}:
            raise ValueError("handoff_type must be architect_handoff or note")
        if handoff_type == "note" and workflow.is_low_signal_note(content):
            return {
                "status": "error",
                "error": "low_signal_note",
                "message": "Note rejected: too short or low-signal for memory ingest",
            }, 400
        project = _optional_str(args, "project") or "crowley"
        try:
            result = crowley.ingest_handoff(
                source="chatgpt",
                handoff_type=handoff_type,
                content=content,
                project=project,
            )
        except crowley.IngestHandoffError as exc:
            return {"status": "error", "error": exc.message}, 400
        return result, 201

    def _handle_audit_rollback(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        import write_audit

        audit_id = _require_id(args, "audit_id")
        agent = _optional_str(args, "agent_id") or "chatgpt"
        try:
            result = write_audit.rollback_write_audit(int(audit_id), agent_id=agent)
        except LookupError as exc:
            raise LookupError(str(exc)) from exc
        except ValueError as exc:
            return {"ok": False, "error": "rollback_failed", "message": str(exc)}, 400
        return result, None

    write_tools = [
        (
            "ticket.create",
            "Mint a ticket (Codex-parity planning write).",
            {
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "assignee": {"type": "string"},
                    "priority": {"type": "integer"},
                    "parent_id": {"type": "integer"},
                },
            },
            _handle_ticket_create,
        ),
        (
            "ticket.update",
            "Update ticket status, assignee, comment, or linked handoff.",
            {
                "properties": {
                    "id": {"type": "integer"},
                    "ticket_id": {"type": "integer", "description": "Alias for id"},
                    "status": {"type": "string"},
                    "assignee": {"type": "string"},
                    "comment": {"type": "string"},
                    "linked_memory_id": {"type": "integer"},
                },
            },
            _handle_ticket_update,
        ),
        (
            "ticket.cancel",
            "Cancel a ticket (requires comment).",
            {
                "properties": {
                    "id": {"type": "integer"},
                    "ticket_id": {"type": "integer", "description": "Alias for id"},
                    "comment": {"type": "string"},
                },
            },
            _handle_ticket_cancel,
        ),
        (
            "handoff.ingest",
            "Post architect handoff or note to Crowley memory.",
            {
                "properties": {
                    "content": {"type": "string", "description": "Handoff body (canonical)"},
                    "details": {"type": "string", "description": "Alias for content"},
                    "summary": {
                        "type": "string",
                        "description": "Short summary; used as body only when content/details omitted",
                    },
                    "handoff_type": {
                        "type": "string",
                        "enum": ["architect_handoff", "note"],
                    },
                    "type": {
                        "type": "string",
                        "description": "Alias for handoff_type",
                        "enum": ["architect_handoff", "note"],
                    },
                    "project": {"type": "string"},
                },
            },
            _handle_handoff_ingest,
        ),
        (
            "note.ingest",
            "Short planning note (alias for handoff.ingest with type note).",
            {
                "required": ["content"],
                "properties": {"content": {"type": "string"}, "project": {"type": "string"}},
            },
            lambda args: _handle_handoff_ingest({**args, "handoff_type": "note"}),
        ),
        (
            "audit.rollback",
            "Rollback a write_audit_log entry (restores before snapshot or cancels create).",
            {
                "required": ["audit_id"],
                "properties": {
                    "audit_id": {"type": "integer"},
                    "agent_id": {"type": "string"},
                },
            },
            _handle_audit_rollback,
        ),
    ]
    for name, description, args_schema, handler in write_tools:
        register_tool(
            ToolDefinition(
                name=name,
                kind="write",
                description=description,
                args_schema={"type": "object", **args_schema},
                handler=handler,
            )
        )


def _github_dispatch(call: Callable[[], Any], _args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
    try:
        result = call()
    except github_read.GitHubNotConfiguredError as exc:
        return {"ok": False, "error": "github_not_configured", "message": str(exc)}, 503
    except github_read.GitHubReadError as exc:
        return {
            "ok": False,
            "error": "github_read_failed",
            "message": str(exc)[:500],
        }, 200
    except RuntimeError as exc:
        return {
            "ok": False,
            "error": "github_read_failed",
            "message": str(exc)[:500],
        }, 200
    except Exception as exc:
        return {
            "ok": False,
            "error": "github_read_failed",
            "message": str(exc)[:500],
        }, 200
    if isinstance(result, dict):
        return result, None
    return {"result": result}, None


def _register_github_tools() -> None:
    def _handle_github_status(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        del args
        return _github_dispatch(lambda: github_read.github_status(), {})

    def _handle_github_file(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        path = _optional_str(args, "path")
        if not path:
            raise ValueError("path is required")
        return _github_dispatch(
            lambda: github_read.read_file(path=path, ref=_optional_str(args, "ref")),
            {},
        )

    def _handle_github_search_code(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        query = _optional_str(args, "q")
        if not query:
            raise ValueError("q is required")
        return _github_dispatch(
            lambda: github_read.search_code(query=query, ref=_optional_str(args, "ref")),
            {},
        )

    def _handle_github_branches(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        del args
        return _github_dispatch(lambda: github_read.list_branches(), {})

    def _handle_github_pulls(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        state = _optional_str(args, "state") or "open"
        return _github_dispatch(lambda: github_read.list_pulls(state=state), {})

    def _handle_github_pull(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        return _github_dispatch(lambda: github_read.get_pull(_require_id(args, "number")), {})

    def _handle_github_issues(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        state = _optional_str(args, "state") or "open"
        return _github_dispatch(lambda: github_read.list_issues(state=state), {})

    def _handle_github_issue(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        return _github_dispatch(lambda: github_read.get_issue(_require_id(args, "number")), {})

    def _handle_github_compare(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        base = _optional_str(args, "base")
        head = _optional_str(args, "head")
        if not base or not head:
            raise ValueError("base and head are required")
        return _github_dispatch(lambda: github_read.compare_refs(base=base, head=head), {})

    def _handle_github_commits(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        return _github_dispatch(
            lambda: github_read.list_commits(
                sha=_optional_str(args, "sha"),
                path=_optional_str(args, "path"),
            ),
            {},
        )

    def _handle_github_workflow_runs(args: dict[str, Any]) -> tuple[dict[str, Any], int | None]:
        return _github_dispatch(
            lambda: github_read.list_workflow_runs(branch=_optional_str(args, "branch")),
            {},
        )

    github_tools = [
        ("github.status", "GitHub repo connectivity status.", {}, _handle_github_status),
        (
            "github.file",
            "Read a file from the repo.",
            {"required": ["path"], "properties": {"path": {"type": "string"}, "ref": {"type": "string"}}},
            _handle_github_file,
        ),
        (
            "github.search_code",
            "Search code in the repo.",
            {"required": ["q"], "properties": {"q": {"type": "string"}, "ref": {"type": "string"}}},
            _handle_github_search_code,
        ),
        ("github.branches", "List repository branches.", {}, _handle_github_branches),
        (
            "github.pulls",
            "List pull requests.",
            {"properties": {"state": {"type": "string", "default": "open"}}},
            _handle_github_pulls,
        ),
        (
            "github.pull",
            "Get one pull request.",
            {"required": ["number"], "properties": {"number": {"type": "integer"}}},
            _handle_github_pull,
        ),
        (
            "github.issues",
            "List issues.",
            {"properties": {"state": {"type": "string", "default": "open"}}},
            _handle_github_issues,
        ),
        (
            "github.issue",
            "Get one issue.",
            {"required": ["number"], "properties": {"number": {"type": "integer"}}},
            _handle_github_issue,
        ),
        (
            "github.compare",
            "Compare two refs.",
            {"required": ["base", "head"], "properties": {"base": {"type": "string"}, "head": {"type": "string"}}},
            _handle_github_compare,
        ),
        (
            "github.commits",
            "List commits.",
            {"properties": {"sha": {"type": "string"}, "path": {"type": "string"}}},
            _handle_github_commits,
        ),
        (
            "github.workflow_runs",
            "List GitHub Actions workflow runs.",
            {"properties": {"branch": {"type": "string"}}},
            _handle_github_workflow_runs,
        ),
    ]
    for name, description, args_schema, handler in github_tools:
        register_tool(
            ToolDefinition(
                name=name,
                kind="read",
                description=description,
                args_schema={"type": "object", **args_schema},
                handler=handler,
            )
        )
