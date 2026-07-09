"""Extracted V4.1 world/sync/portable runtime implementation."""

from __future__ import annotations

from typing import Any

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

def build_agent_sync_bundle(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_agent_sync_bundle, rt, *args, **kwargs)

def finalize_agent_sync_bundle(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_finalize_agent_sync_bundle, rt, *args, **kwargs)

def _impl_build_agent_sync_bundle(agent: str, limit: int = 20) -> dict[str, object]:
    """Read-only slim sync snapshot for agents communicating through Crowley (V3.9.9)."""
    import agent_sync_envelope

    normalized_agent = agent.strip().lower()
    if normalized_agent not in {"cursor", "codex", "chatgpt"}:
        raise ValueError(f"unsupported agent: {agent}")

    sync_limit = agent_sync_envelope.normalize_agent_sync_limit(limit)
    caps = agent_sync_envelope.section_caps(sync_limit)
    memory_limit = caps["memories"]
    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    state_payload = _state_payload_for_api(state)

    raw_events = [
        _memory_item_api_dict(row)
        for row in list_recent_agent_events(
            limit=max(sync_limit, caps["events_other"]),
            project_id=project_id,
        )
    ]
    events_from_this_agent = [
        _agent_sync_event_dict(event)
        for event in raw_events
        if str(event.get("source", "")).lower() == normalized_agent
    ][: caps["events_own"]]
    events_from_other_agents = [
        _agent_sync_event_dict(event)
        for event in raw_events
        if str(event.get("source", "")).lower() != normalized_agent
    ][: caps["events_other"]]

    recent_decisions: list[dict[str, object]] = []
    if project_id is not None:
        recent_decisions = [
            row_to_dict(row)
            for row in list_decisions(project_id, limit=caps["decisions"])
        ]

    constraint_memories = _list_constraint_memories(
        project_id, limit=caps["constraints"]
    )
    retrieval_context = retrieve_work_context_memories(
        project_id,
        normalized_agent,
        limit=memory_limit,
    )
    relevant_memories = retrieval_context["memories"]
    supporting_memories = relevant_memories
    recommended = _state_display(state["next_action"]) if state is not None else "(unset)"
    tickets = build_tickets_summary(
        project_id,
        normalized_agent,
        open_limit=caps["tickets_open"],
        closed_limit=caps["tickets_closed"],
    )
    task_frame = build_task_frame_context(
        project_id,
        normalized_agent,
        sync_limit=sync_limit,
    )
    activity_wire = _slim_activity_wire_for_agent(
        build_activity_wire(project_id, limit=ACTIVITY_WIRE_WORLD_CAP),
        normalized_agent,
        limit=caps["activity_wire"],
    )

    import agent_behavior

    recent_handoffs = agent_behavior.build_auto_handoff_feed(limit=caps["handoffs"])

    bundle = {
        "agent": normalized_agent,
        "role": get_agent_role(normalized_agent),
        "permissions": _agent_permissions_payload(normalized_agent),
        "boot_sequence": {
            "required_first_tool": "agent.sync",
            "status": "complete",
            "message": "This bundle satisfies fresh-session boot when agent.sync is the first tool call.",
        },
        "pipeline": {
            "hub": "crowley",
            "crowley": "running local OS — memory, world model, extraction, bus, this chat",
            "codex": "architect — plans and decides; posts to Crowley memory",
            "cursor": "builder — ships code; posts to Crowley memory",
            "rule": "agents do not message each other; truth flows through Crowley only",
        },
        "bus_health": bus_health(),
        "project": row_to_dict(project) if project is not None else None,
        "state": state_payload,
        "recommended_next_action": recommended,
        "agent_activity": _agent_activity_summary(project_id),
        "tickets": tickets,
        "task_frame": task_frame,
        "activity_wire": activity_wire,
        "recent_handoffs": recent_handoffs,
        "recent_decisions": recent_decisions,
        "constraint_memories": constraint_memories,
        "events_from_this_agent": events_from_this_agent,
        "events_from_other_agents": events_from_other_agents,
        "relevant_memories_query": retrieval_context["query"],
        "relevant_memories": relevant_memories,
        "supporting_memories": supporting_memories,
        "relevant_memories_tickets": retrieval_context["tickets"],
        "bundle_shape": AGENT_SYNC_BUNDLE_SHAPE,
        "sync_limit": sync_limit,
        "bundle_caps": {
            "sync_limit": sync_limit,
            "recent_decisions": caps["decisions"],
            "constraint_memories": caps["constraints"],
            "events_from_other_agents": caps["events_other"],
            "events_from_this_agent": caps["events_own"],
            "supporting_memories": memory_limit,
            "relevant_memories": memory_limit,
            "task_frame_working_on": caps["task_frame_working"],
            "activity_wire": caps["activity_wire"],
            "handoffs": caps["handoffs"],
            "tickets_open": caps["tickets_open"],
        },
    }
    return bundle

def _impl_finalize_agent_sync_bundle(bundle: dict[str, object]) -> dict[str, object]:
    """Apply ASE byte bounding to a sync bundle (#229)."""
    import agent_sync_envelope

    return agent_sync_envelope.apply_adaptive_sync_envelope(bundle)
