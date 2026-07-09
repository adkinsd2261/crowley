"""Extracted V4.1 world/sync/portable runtime implementation."""

from __future__ import annotations

from typing import Any

DECISIONS_LIMIT = 10
LOOPS_LIMIT = 10
AGENT_SYNC_CONSTRAINTS_CAP = 5
ACTIVITY_PULSE_WINDOW_MINUTES = 45
CONTEXT_DEFAULT_QUERY = "current project state"
MEMORY_LIMIT = 8
SUPPORTING_MEMORIES_CAP = 4

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

def get_active_project(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_get_active_project, rt, *args, **kwargs)

def get_project_by_slug(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_get_project_by_slug, rt, *args, **kwargs)

def get_project_state(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_get_project_state, rt, *args, **kwargs)

def update_project_state_field(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_update_project_state_field, rt, *args, **kwargs)

def save_decision(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_save_decision, rt, *args, **kwargs)

def list_decisions(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_list_decisions, rt, *args, **kwargs)

def save_open_loop(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_save_open_loop, rt, *args, **kwargs)

def list_open_loops(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_list_open_loops, rt, *args, **kwargs)

def close_open_loop(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_close_open_loop, rt, *args, **kwargs)

def get_active_world_context(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_get_active_world_context, rt, *args, **kwargs)

def list_tasks(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_list_tasks, rt, *args, **kwargs)

def update_task_status(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_update_task_status, rt, *args, **kwargs)

def _state_payload_for_api(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__state_payload_for_api, rt, *args, **kwargs)

def parse_phase_progress(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_parse_phase_progress, rt, *args, **kwargs)

def _memory_counts_payload(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__memory_counts_payload, rt, *args, **kwargs)

def _canon_api_items(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__canon_api_items, rt, *args, **kwargs)

def _list_constraint_memories(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__list_constraint_memories, rt, *args, **kwargs)

def _agent_sync_event_dict(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__agent_sync_event_dict, rt, *args, **kwargs)

def _format_canon_prompt_section(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__format_canon_prompt_section, rt, *args, **kwargs)

def build_world_dashboard(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_world_dashboard, rt, *args, **kwargs)

def record_system_metric(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_record_system_metric, rt, *args, **kwargs)

def record_activity_pulse(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_record_activity_pulse, rt, *args, **kwargs)

def list_activity_pulses(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_list_activity_pulses, rt, *args, **kwargs)

def build_activity_wire(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_activity_wire, rt, *args, **kwargs)

def get_metrics_summary_24h(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_get_metrics_summary_24h, rt, *args, **kwargs)

def build_context_bundle(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_context_bundle, rt, *args, **kwargs)

def retrieve_work_context_memories(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_retrieve_work_context_memories, rt, *args, **kwargs)

def build_task_frame_context(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_task_frame_context, rt, *args, **kwargs)

def _impl_get_active_project() -> sqlite3.Row | None:
    """Return the active project row, if any."""
    conn = connect_db()
    try:
        return conn.execute(
            "SELECT * FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

def _impl_get_project_by_slug(slug: str) -> sqlite3.Row | None:
    """Return a project row by slug (case-insensitive), if any."""
    normalized = slug.strip()
    if not normalized:
        return None
    conn = connect_db()
    try:
        return conn.execute(
            "SELECT * FROM projects WHERE LOWER(slug) = LOWER(?) LIMIT 1",
            (normalized,),
        ).fetchone()
    finally:
        conn.close()

def _impl_get_project_state(project_id: int) -> sqlite3.Row | None:
    """Return current state for a project."""
    conn = connect_db()
    try:
        return conn.execute(
            "SELECT * FROM project_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()

def _impl_update_project_state_field(
    project_id: int, field: str, value: str, updated_by: str = "user"
) -> None:
    """Update one project_state column."""
    if field not in STATE_FIELDS:
        raise ValueError(f"invalid state field: {field}")
    now = _now_iso()
    conn = connect_db()
    try:
        conn.execute(
            f"UPDATE project_state SET {field} = ?, updated_at = ?, updated_by = ? WHERE project_id = ?",
            (value, now, updated_by, project_id),
        )
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (now, project_id),
        )
        conn.commit()
    finally:
        conn.close()

def _impl_save_decision(
    project_id: int,
    summary: str,
    detail: str | None = None,
    source: str = "command",
    message_id: int | None = None,
) -> int:
    """Append a decision and return its id."""
    conn = connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO decisions (project_id, timestamp, summary, detail, source, message_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, _now_iso(), summary, detail, source, message_id),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()

def _impl_list_decisions(project_id: int, limit: int = DECISIONS_LIMIT) -> list[sqlite3.Row]:
    """Return recent decisions for a project."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM decisions WHERE project_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()

def _impl_save_open_loop(
    project_id: int,
    description: str,
    priority: int = 3,
    source: str = "command",
) -> int:
    """Create an open loop and return its id."""
    conn = connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO open_loops (project_id, timestamp, description, status, priority, source)
            VALUES (?, ?, ?, 'open', ?, ?)
            """,
            (project_id, _now_iso(), description, priority, source),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()

def _impl_list_open_loops(
    project_id: int, status: str = "open", limit: int = LOOPS_LIMIT
) -> list[sqlite3.Row]:
    """Return open loops for a project."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM open_loops WHERE project_id = ? AND status = ?
            ORDER BY priority DESC, id ASC LIMIT ?
            """,
            (project_id, status, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()

def _impl_close_open_loop(loop_id: int) -> bool:
    """Mark an open loop closed. Returns False if not found."""
    conn = connect_db()
    try:
        cur = conn.execute(
            "UPDATE open_loops SET status = 'closed' WHERE id = ? AND status = 'open'",
            (loop_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def _impl_get_active_world_context() -> dict[str, object] | None:
    """Structured active project context for prompts and display."""
    project = get_active_project()
    if project is None:
        return None
    state = get_project_state(int(project["id"]))
    pid = int(project["id"])
    return {
        "project": project,
        "state": state,
        "decisions": list_decisions(pid, limit=WORLD_DECISIONS_IN_PROMPT),
        "open_loops": list_open_loops(pid, status="open", limit=WORLD_LOOPS_IN_PROMPT),
    }

def _impl_list_tasks(status: str | None = None) -> list[sqlite3.Row]:
    """Return tasks ordered by due date (nulls last), then id."""
    conn = connect_db()
    try:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY (due_date IS NULL), due_date ASC, id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY (due_date IS NULL), due_date ASC, id ASC",
                (status,),
            ).fetchall()
        return list(rows)
    finally:
        conn.close()

def _impl_update_task_status(task_id: int, status: str) -> bool:
    """Update task status (e.g. open → done). Returns True if a row changed."""
    if status not in ("open", "done"):
        raise ValueError(f"invalid task status: {status}")
    conn = connect_db()
    try:
        cur = conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ? AND status != ?",
            (status, task_id, status),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def _impl__state_payload_for_api(state: sqlite3.Row | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "phase": _state_display(state["phase"]),
        "focus": _state_display(state["focus"]),
        "current_risk": _state_display(state["current_risk"]),
        "next_action": _state_display(state["next_action"]),
        "what_changed": _state_display(state["what_changed"]),
        "updated_at": state["updated_at"],
        "updated_by": state["updated_by"],
    }

def _impl_parse_phase_progress(phase: str | None) -> dict[str, object] | None:
    """Parse 'Phase 1/6' or 'Phase 2 of 6' from project_state.phase text."""
    if not phase or not str(phase).strip():
        return None
    text = str(phase).strip()
    match = _PHASE_PROGRESS_RE.search(text)
    if not match:
        return None
    current = int(match.group(1))
    total = int(match.group(2))
    if total < 1 or current < 1 or current > total:
        return None
    return {
        "current": current,
        "total": total,
        "fraction": round(current / total, 3),
        "label": text,
    }

def _impl__memory_counts_payload(displayed: int) -> dict[str, object]:
    by_status = count_memory_items_by_status()
    active = int(by_status.get("active", 0))
    total = sum(int(value) for value in by_status.values())
    return {
        "memory": active,
        "memory_active": active,
        "memory_total": total,
        "memory_displayed": displayed,
        "memory_by_status": by_status,
    }

def _impl__canon_api_items(project_id: int | None = None) -> list[dict[str, object]]:
    return [_memory_item_api_dict(row) for row in list_canon_memory_items(project_id)]

def _impl__list_constraint_memories(
    project_id: int | None,
    *,
    limit: int = AGENT_SYNC_CONSTRAINTS_CAP,
) -> list[dict[str, object]]:
    if project_id is None:
        return []
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE status = 'active' AND memory_type = 'constraint'
              AND project_id = ?
            ORDER BY importance DESC, created_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [_memory_item_api_dict(row) for row in rows]
    finally:
        conn.close()

def _impl__agent_sync_event_dict(event: dict[str, object]) -> dict[str, object]:
    content = event.get("content") or event.get("display") or ""
    return {
        **event,
        "summary": _handoff_summary_line(str(content)),
    }

def _impl__format_canon_prompt_section(canon_rows: list[sqlite3.Row]) -> str:
    lines = [
        "Canonical memory trail:",
        (
            "Always-on continuity — not top authority. Filesystem truth, tickets, "
            "agent activity, and live DB state outrank canon; canon outranks hybrid "
            "retrieval and recent chat."
        ),
    ]
    if not canon_rows:
        lines.append("(no canon rows stored)")
        return "\n".join(lines)
    for row in canon_rows:
        content = _memory_display_text(row)
        if len(content) > MEMORY_LINE_MAX * 2:
            content = content[: MEMORY_LINE_MAX * 2 - 3] + "..."
        lines.append(f"[canon:{row['id']} | importance {row['importance']}] {content}")
    return "\n".join(lines)

def _impl_build_world_dashboard() -> dict[str, object]:
    """Single read-only snapshot for live UI sync (project + intelligence panels)."""
    project = get_active_project()
    if project is None:
        return {
            "project": None,
            "state": None,
            "phase_progress": None,
            "version": CROWLEY_VERSION,
            "release_label": CROWLEY_RELEASE_LABEL,
            "counts": {
                "tasks_open": 0,
                "loops_open": 0,
                "decisions": 0,
                "tickets_open": 0,
                "tickets_in_progress": 0,
                "tickets_blocked": 0,
                "agent_feed": 0,
                "recent_changes": 0,
                **_memory_counts_payload(0),
            },
            "tasks": [],
            "tickets": [],
            "ticket_groups": [],
            "loops": [],
            "decisions": [],
            "memory_items": [],
            "recent_changes": [],
            "agent_activity": {"last_by_source": {}, "latest_contact": None, "recent": []},
            "activity_wire": {
                "pinned_focus": None,
                "active_agents": [],
                "items": [],
                "cap": ACTIVITY_WIRE_WORLD_CAP,
            },
            "task_frame": build_task_frame_context(None),
            "operator_metrics": get_metrics_summary_24h(),
            "synced_at": _now_iso(),
        }

    project_id = int(project["id"])
    state = get_project_state(project_id)
    state_payload = _state_payload_for_api(state)
    phase_progress = None
    if state_payload and state_payload.get("phase"):
        phase_progress = parse_phase_progress(str(state_payload["phase"]))

    tasks = list_tasks(status="open")
    ticket_summary = build_tickets_summary(project_id)
    loops = list_open_loops(project_id, status="open", limit=50)
    loops_sorted = sorted(loops, key=lambda row: (int(row["priority"]), int(row["id"])))
    decisions = list_decisions(project_id, limit=10)
    memory_rows = list_recent_memory_items(10)
    memory_counts = _memory_counts_payload(len(memory_rows))
    agent_activity = _agent_activity_summary(project_id)
    recent_activity = agent_activity.get("recent") or []
    recent_changes = build_recent_changes_feed(project_id)
    recent_change_items = recent_changes.get("items") or []
    retrieval_context = retrieve_work_context_memories(project_id, agent=None)
    task_frame = build_task_frame_context(project_id, agent=None)
    activity_wire_full = build_activity_wire(project_id, limit=ACTIVITY_WIRE_WORLD_CAP)
    activity_wire = {
        "pinned_focus": activity_wire_full.get("pinned_focus"),
        "active_agents": activity_wire_full.get("active_agents") or [],
        "items": (activity_wire_full.get("items") or [])[:ACTIVITY_WIRE_WORLD_CAP],
        "cap": ACTIVITY_WIRE_WORLD_CAP,
    }

    return {
        "project": row_to_dict(project),
        "state": state_payload,
        "phase_progress": phase_progress,
        "version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "counts": {
            "tasks_open": len(tasks),
            "loops_open": len(loops_sorted),
            "decisions": len(decisions),
            "tickets_open": int((ticket_summary.get("counts") or {}).get("open", 0)),
            "tickets_in_progress": int(
                (ticket_summary.get("counts") or {}).get("in_progress", 0)
            ),
            "tickets_blocked": int((ticket_summary.get("counts") or {}).get("blocked", 0)),
            "tickets_open_total": int(
                (ticket_summary.get("counts") or {}).get("open_total", 0)
            ),
            "agent_feed": len(recent_activity),
            "recent_changes": len(recent_change_items),
            **memory_counts,
        },
        "tasks": [row_to_dict(row) for row in tasks],
        "tickets": ticket_summary.get("open", []),
        "ticket_groups": ticket_summary.get("grouped_open", []),
        "loops": [row_to_dict(row) for row in loops_sorted],
        "decisions": [row_to_dict(row) for row in decisions],
        "memory_items": [_memory_item_api_dict(row) for row in memory_rows],
        "recent_changes": recent_change_items,
        "filesystem": build_filesystem_dashboard(),
        "project_files": get_project_files_context(),
        "agent_activity": agent_activity,
        "activity_wire": activity_wire,
        "task_frame": task_frame,
        "relevant_memories": retrieval_context["memories"],
        "relevant_memories_query": retrieval_context["query"],
        "relevant_memories_tickets": retrieval_context["tickets"],
        "operator_metrics": get_metrics_summary_24h(),
        "synced_at": _now_iso(),
    }

def _impl_record_system_metric(
    metric_type: str,
    *,
    value: float = 1.0,
    label: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    """Append one operator metric row. Never raises."""
    try:
        conn = connect_db()
        try:
            conn.execute(
                """
                INSERT INTO system_metrics (
                    recorded_at, metric_type, value, label, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    metric_type.strip().lower(),
                    float(value),
                    label,
                    json.dumps(payload or {}),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

def _impl_record_activity_pulse(
    agent: str,
    verb: str,
    *,
    project_id: int | None = None,
    ticket_id: int | None = None,
    summary: str | None = None,
) -> dict[str, object] | None:
    """Append one live-wire pulse row. Never raises (V3.9.11 #70)."""
    try:
        agent_norm = str(agent).strip().lower()
        verb_norm = str(verb).strip().lower()
        if agent_norm not in ACTIVITY_PULSE_AGENTS or verb_norm not in ACTIVITY_PULSE_VERBS:
            return None
        pid = project_id
        if pid is None:
            project = get_active_project()
            if project is None:
                return None
            pid = int(project["id"])
        summary_text = str(summary).strip() if summary is not None else None
        if summary_text == "":
            summary_text = None
        now = _now_iso()
        conn = connect_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO activity_pulses (
                    project_id, agent, verb, ticket_id, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pid, agent_norm, verb_norm, ticket_id, summary_text, now),
            )
            conn.commit()
            pulse_id = int(cur.lastrowid)
        finally:
            conn.close()
        return {
            "id": pulse_id,
            "project_id": pid,
            "agent": agent_norm,
            "verb": verb_norm,
            "ticket_id": ticket_id,
            "summary": summary_text,
            "created_at": now,
        }
    except Exception:
        return None

def _impl_list_activity_pulses(
    project_id: int,
    *,
    window_minutes: int = ACTIVITY_PULSE_WINDOW_MINUTES,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Recent activity pulses within window for live wire (V3.9.11 #70)."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT id, project_id, agent, verb, ticket_id, summary, created_at
            FROM activity_pulses
            WHERE project_id = ? AND datetime(created_at) >= datetime(?)
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (project_id, since, limit),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "project_id": int(row["project_id"]),
                "agent": str(row["agent"]),
                "verb": str(row["verb"]),
                "ticket_id": int(row["ticket_id"]) if row["ticket_id"] is not None else None,
                "summary": row["summary"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
    finally:
        conn.close()

def _impl_build_activity_wire(
    project_id: int | None,
    *,
    limit: int = 30,
    window_minutes: int = ACTIVITY_PULSE_WINDOW_MINUTES,
) -> dict[str, object]:
    """Compose live activity wire from pulses, changes feed, and ambient fallbacks (#72)."""
    if project_id is None:
        return {"items": [], "pinned_focus": None, "active_agents": []}

    limit = max(1, min(int(limit), 50))
    real_items: list[dict[str, object]] = []

    for pulse in list_activity_pulses(project_id, window_minutes=window_minutes, limit=limit):
        real_items.append(_pulse_to_wire_item(pulse))

    changes = build_recent_changes_feed(project_id, limit=limit)
    for raw in changes.get("items") or []:
        if isinstance(raw, dict):
            real_items.append(_changes_item_to_wire_item(raw))

    real_items.sort(
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")),
        reverse=True,
    )
    real_items = _dedupe_activity_wire_items(real_items)

    items = list(real_items)
    if _wire_needs_ambient(real_items):
        items.extend(_ambient_activity_wire_items(project_id))
        items.sort(
            key=lambda row: (
                0 if row.get("is_ambient") else 1,
                str(row.get("created_at") or ""),
                str(row.get("id") or ""),
            ),
            reverse=True,
        )

    active_agents = sorted(
        {
            str(row["agent"])
            for row in real_items
            if not row.get("is_ambient") and str(row.get("agent") or "")
        }
    )
    pinned_focus = None
    state = get_project_state(project_id)
    if state is not None and state["focus"]:
        pinned_focus = str(state["focus"])

    return {
        "items": items[:limit],
        "pinned_focus": pinned_focus,
        "active_agents": active_agents,
    }

def _impl_get_metrics_summary_24h() -> dict[str, object]:
    """Return 24h rollups for operator surfaces — no PII."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT metric_type, COUNT(*) AS n
            FROM system_metrics
            WHERE datetime(recorded_at) >= datetime(?)
            GROUP BY metric_type
            ORDER BY metric_type ASC
            """,
            (since,),
        ).fetchall()
        by_type = {str(row["metric_type"]): int(row["n"]) for row in rows}
        retrieval_rows = conn.execute(
            """
            SELECT label, COUNT(*) AS n
            FROM system_metrics
            WHERE metric_type = 'retrieval'
              AND datetime(recorded_at) >= datetime(?)
            GROUP BY label
            """,
            (since,),
        ).fetchall()
        retrieval_modes = {
            str(row["label"] or "unknown"): int(row["n"]) for row in retrieval_rows
        }
    finally:
        conn.close()
    return {
        "window_hours": 24,
        "since": since,
        "counts": by_type,
        "retrieval_modes": retrieval_modes,
        "chat_errors": int(by_type.get("chat_error", 0)),
        "ingest_ok": int(by_type.get("ingest_ok", 0)),
        "ingest_error": int(by_type.get("ingest_error", 0)),
        "ticket_events": int(by_type.get("ticket_created", 0))
        + int(by_type.get("ticket_closed", 0))
        + int(by_type.get("ticket_cancelled", 0)),
    }

def _impl_build_context_bundle(
    q: str = CONTEXT_DEFAULT_QUERY,
    limit: int = MEMORY_LIMIT,
    project_slug: str | None = None,
    depth: str | None = None,
    debug: bool = False,
) -> dict[str, object]:
    """
    Read-only working context for external agents (V3.7 memory bus).
    No writes.
    """
    import context_resolution

    if project_slug is not None:
        project = get_project_by_slug(project_slug)
        if project is None:
            raise ValueError(f"project not found: {project_slug}")
    else:
        project = get_active_project()

    project_id: int | None = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    state_payload = _state_payload_for_api(state)

    recent_decisions: list[dict[str, object]] = []
    open_loops: list[dict[str, object]] = []
    if project_id is not None:
        recent_decisions = [
            row_to_dict(row)
            for row in list_decisions(project_id, limit=DIAGNOSTICS_DECISIONS_LIMIT)
        ]
        open_loops = [
            row_to_dict(row)
            for row in list_open_loops(project_id, status="open", limit=LOOPS_LIMIT)
        ]

    open_tasks = [
        row_to_dict(row) for row in list_tasks(status="open")[:DIAGNOSTICS_TASKS_LIMIT]
    ]
    canon = _canon_api_items(project_id)
    resolved_depth = context_resolution.normalize_depth(depth)
    fetch_limit = max(limit * 3, 16) if resolved_depth else limit
    relevant_memories = retrieve_memories(q, limit=fetch_limit, project_id=project_id)
    matched_tickets: list[dict[str, object]] = []
    trace: dict[str, object] = {}
    if resolved_depth is not None:
        tickets_summary = build_tickets_summary(project_id)
        open_tickets = tickets_summary.get("open")
        candidate_tickets = (
            [dict(item) for item in open_tickets]
            if isinstance(open_tickets, list)
            else []
        )
        resolved, matched_tickets, trace = context_resolution.cross_source_resolve(
            [dict(item) for item in relevant_memories],
            matched_tickets=candidate_tickets,
            query=q,
            depth=resolved_depth,
            debug=debug,
        )
        relevant_memories = resolved[:limit]
        conn = connect_db()
        try:
            active_spark_count = context_resolution.count_active_sparks(
                conn,
                project_id=project_id,
            )
        finally:
            conn.close()
        trace = context_resolution.apply_memory_fallback_trace(
            trace,
            active_spark_count=active_spark_count,
            fallback_used=active_spark_count
            < context_resolution.COLD_START_ACTIVE_SPARK_THRESHOLD,
        )

    if state is not None and state["next_action"]:
        recommended = _state_display(state["next_action"])
    else:
        recommended = "(unset)"

    bundle: dict[str, object] = {
        "project": row_to_dict(project) if project is not None else None,
        "state": state_payload,
        "recent_decisions": recent_decisions,
        "open_loops": open_loops,
        "open_tasks": open_tasks,
        "canon": canon,
        "relevant_memories": relevant_memories,
        "agent_activity": _agent_activity_summary(project_id),
        "tickets": build_tickets_summary(project_id),
        "system_health": _context_system_health(),
        "project_files": get_project_files_context(),
        "knowledge_files": load_knowledge_files_context(q),
        "recommended_next_action": recommended,
    }
    if resolved_depth is not None:
        bundle["depth"] = resolved_depth
        bundle["matched_tickets"] = matched_tickets
        bundle["trace"] = trace
    return bundle

def _impl_retrieve_work_context_memories(
    project_id: int | None,
    agent: str | None = None,
    *,
    limit: int = SUPPORTING_MEMORIES_CAP,
) -> dict[str, object]:
    """Ticket-narrative supporting retrieval for dashboard and agent sync (V3.9.10 #65)."""
    query, tickets = build_ticket_aware_retrieval_query(project_id, agent)
    effective_limit = min(max(1, int(limit)), SUPPORTING_MEMORIES_CAP)
    handoff_ids = _recent_handoff_memory_ids(project_id)
    fetch_limit = max(effective_limit * 4, 16)
    memories = retrieve_memories(query, limit=fetch_limit, project_id=project_id)
    memories = [
        item for item in memories if int(item["id"]) not in handoff_ids
    ]
    memories = _rank_supporting_memories(memories)
    anchors = _ticket_anchor_memories(project_id, tickets)
    if anchors:
        merged: list[dict[str, object]] = []
        seen: set[int] = set()
        for item in anchors + memories:
            memory_id = int(item["id"])
            if memory_id in seen or memory_id in handoff_ids:
                continue
            seen.add(memory_id)
            merged.append(item)
            if len(merged) >= effective_limit:
                break
        memories = merged[:effective_limit]
    else:
        memories = memories[:effective_limit]
    return {
        "query": query,
        "tickets": [
            {
                "id": int(ticket["id"]),
                "title": str(ticket.get("title") or ""),
                "status": str(ticket.get("status") or "open"),
                "assignee": str(ticket.get("assignee") or ""),
            }
            for ticket in tickets
        ],
        "memories": memories,
    }

def _impl_build_task_frame_context(
    project_id: int | None,
    agent: str | None = None,
    *,
    sync_limit: int | None = None,
) -> dict[str, object]:
    """Structured task brief: working tickets, handoff, guardrails (V3.9.10 #64)."""
    import agent_sync_envelope

    normalized_agent = (
        agent.strip().lower() if isinstance(agent, str) and agent.strip() else None
    )
    role = get_agent_role(normalized_agent) if normalized_agent else None
    section_caps = (
        agent_sync_envelope.section_caps(sync_limit)
        if sync_limit is not None
        else {
            "task_frame_working": TASK_FRAME_WORKING_ON_CAP,
            "decisions": AGENT_SYNC_DECISIONS_CAP,
            "constraints": AGENT_SYNC_CONSTRAINTS_CAP,
            "tickets_open": 50,
        }
    )
    empty_guardrails = {"recent_decisions": [], "constraint_memories": []}
    caps = {
        "working_on": section_caps["task_frame_working"],
        "recent_decisions": section_caps["decisions"],
        "constraint_memories": section_caps["constraints"],
    }
    if project_id is None:
        return {
            "agent": normalized_agent,
            "role": role,
            "working_on": [],
            "blockers": [],
            "last_handoff": None,
            "guardrails": empty_guardrails,
            "caps": caps,
        }

    summary = build_tickets_summary(
        project_id,
        normalized_agent,
        open_limit=section_caps["tickets_open"],
        closed_limit=min(5, section_caps["tickets_open"]),
    )
    working_on: list[dict[str, object]] = []
    seen_work_ids: set[int] = set()

    def add_work(ticket: object) -> None:
        if not isinstance(ticket, dict) or ticket.get("id") is None:
            return
        ticket_id = int(ticket["id"])
        if ticket_id in seen_work_ids:
            return
        status = str(ticket.get("status") or "")
        if status not in {"in_progress", "open", "claimed"}:
            return
        seen_work_ids.add(ticket_id)
        working_on.append(_task_frame_ticket_payload(ticket))

    if normalized_agent:
        assigned = summary.get("assigned_to_agent") or []
        if isinstance(assigned, list):
            for ticket in sorted(
                assigned,
                key=lambda row: (int(row.get("priority", 4)), int(row.get("id", 0))),
            ):
                add_work(ticket)
    else:
        open_rows = summary.get("open") or []
        if isinstance(open_rows, list):
            for ticket in sorted(
                [
                    row
                    for row in open_rows
                    if isinstance(row, dict) and str(row.get("status")) == "in_progress"
                ],
                key=lambda row: (int(row.get("priority", 4)), int(row.get("id", 0))),
            ):
                add_work(ticket)

    blockers: list[dict[str, object]] = []
    blocked_rows = summary.get("blocked") or []
    if isinstance(blocked_rows, list):
        for ticket in blocked_rows:
            if not isinstance(ticket, dict):
                continue
            if normalized_agent and str(ticket.get("assignee", "")).lower() != normalized_agent:
                continue
            blockers.append(_task_frame_ticket_payload(ticket))

    activity = _agent_activity_summary(project_id)
    last_by_source = activity.get("last_by_source")
    last_handoff: dict[str, object] | None = None
    if normalized_agent and isinstance(last_by_source, dict):
        entry = last_by_source.get(normalized_agent)
        if isinstance(entry, dict):
            last_handoff = dict(entry)

    recent_decisions = [
        row_to_dict(row)
        for row in list_decisions(project_id, limit=section_caps["decisions"])
    ]
    constraint_memories = _list_constraint_memories(
        project_id, limit=section_caps["constraints"]
    )

    return {
        "agent": normalized_agent,
        "role": role,
        "working_on": working_on[: section_caps["task_frame_working"]],
        "blockers": blockers[: section_caps["task_frame_working"]],
        "last_handoff": last_handoff,
        "guardrails": {
            "recent_decisions": recent_decisions,
            "constraint_memories": constraint_memories,
        },
        "caps": caps,
    }
