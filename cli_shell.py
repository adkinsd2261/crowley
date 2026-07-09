"""Extracted V4.1 CLI shell implementation."""

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

def _debug_bus(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_bus, rt, *args, **kwargs)

def _parse_pipe_pair(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__parse_pipe_pair, rt, *args, **kwargs)

def _parse_state_set(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__parse_state_set, rt, *args, **kwargs)

def _print_state(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__print_state, rt, *args, **kwargs)

def _print_decisions(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__print_decisions, rt, *args, **kwargs)

def _print_loops(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__print_loops, rt, *args, **kwargs)

def _parse_remember(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__parse_remember, rt, *args, **kwargs)

def _parse_task_add(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__parse_task_add, rt, *args, **kwargs)

def _print_tasks(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__print_tasks, rt, *args, **kwargs)

def _print_world(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__print_world, rt, *args, **kwargs)

def _debug_extract(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_extract, rt, *args, **kwargs)

def _debug_memories(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_memories, rt, *args, **kwargs)

def _debug_sparks(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_sparks, rt, *args, **kwargs)

def _debug_tasks(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_tasks, rt, *args, **kwargs)

def _debug_brain(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_brain, rt, *args, **kwargs)

def _debug_memory_items(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_memory_items, rt, *args, **kwargs)

def _debug_retrieve(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_retrieve, rt, *args, **kwargs)

def _debug_knowledge(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_knowledge, rt, *args, **kwargs)

def _debug_consolidate(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_consolidate, rt, *args, **kwargs)

def _debug_prompt(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__debug_prompt, rt, *args, **kwargs)

def _handle_command(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__handle_command, rt, *args, **kwargs)

def _run_cli_consolidate(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__run_cli_consolidate, rt, *args, **kwargs)

def _run_cli_hygiene(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__run_cli_hygiene, rt, *args, **kwargs)

def main(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_main, rt, *args, **kwargs)

def _impl__debug_bus() -> None:
    """Print memory bus health (debug-only)."""
    health = bus_health()
    print(f"[debug] memory bus status: {health['status']}")
    print(f"[debug] version: {health['version']} ({health['release_label']})")
    print(f"[debug] db: {health['db']}")
    project = health.get("active_project")
    if project:
        print(
            f"[debug] active project: {project['name']} "
            f"(slug={project['slug']}, status={project['status']})"
        )
    else:
        print("[debug] active project: (none)")
    routes = health.get("routes") or {}
    print(
        "[debug] routes: "
        f"context={routes.get('context')} "
        f"retrieve={routes.get('retrieve')} "
        f"ingest={routes.get('ingest')}"
    )
    print(f"[debug] retrieval_mode: {health['retrieval_mode']}")
    print(f"[debug] provider: {health['provider']}")
    print(f"[debug] brain: {health['brain']}")

def _impl__parse_pipe_pair(args: str) -> tuple[str, str]:
    parts = [p.strip() for p in args.split("|", 1)]
    first = parts[0] if parts else ""
    second = parts[1] if len(parts) > 1 else ""
    return first, second

def _impl__parse_state_set(args: str) -> tuple[str, str] | None:
    """Parse 'set phase: V3 Phase 1' into (field, value)."""
    if not args.startswith("set "):
        return None
    rest = args[4:].strip()
    if ":" not in rest:
        return None
    field, _, value = rest.partition(":")
    field = field.strip().lower()
    value = value.strip()
    field = STATE_FIELD_ALIASES.get(field, field)
    if field not in STATE_FIELDS or not value:
        return None
    return field, value

def _impl__print_state() -> None:
    ctx = get_active_world_context()
    if ctx is None:
        print("No active project.")
        return
    project = ctx["project"]
    state = ctx["state"]
    print(f"Project: {project['name']} ({project['status']})  slug={project['slug']}")
    if state:
        print(f"Phase:        {_state_display(state['phase'])}")
        print(f"Focus:        {_state_display(state['focus'])}")
        print(f"Risk:         {_state_display(state['current_risk'])}")
        print(f"Next action:  {_state_display(state['next_action'])}")
        print(f"What changed: {_state_display(state['what_changed'])}")
        print(f"Updated:      {state['updated_at'][:19]} by {state['updated_by']}")

def _impl__print_decisions() -> None:
    project = get_active_project()
    if project is None:
        print("No active project.")
        return
    rows = list_decisions(int(project["id"]))
    if not rows:
        print("No decisions logged.")
        return
    print(f"{'ID':<4} {'WHEN':<20} SUMMARY")
    print("-" * 70)
    for d in reversed(rows):
        when = d["timestamp"][:19]
        print(f"{d['id']:<4} {when:<20} {d['summary']}")
        if d["detail"]:
            print(f"     {d['detail']}")

def _impl__print_loops() -> None:
    project = get_active_project()
    if project is None:
        print("No active project.")
        return
    rows = list_open_loops(int(project["id"]))
    if not rows:
        print("No open loops.")
        return
    print(f"{'ID':<4} {'PRI':<4} DESCRIPTION")
    print("-" * 60)
    for loop in rows:
        print(f"{loop['id']:<4} {loop['priority']:<4} {loop['description']}")

def _impl__parse_remember(args: str) -> tuple[str, int, str] | None:
    parts = [p.strip() for p in args.split("|")]
    if len(parts) != 3:
        return None
    memory_type, importance_str, content = parts
    try:
        importance = int(importance_str)
    except ValueError:
        return None
    if not memory_type or not content:
        return None
    if importance < 1 or importance > 5:
        return None
    return memory_type, importance, content

def _impl__parse_task_add(args: str) -> tuple[str, str | None, str | None]:
    parts = [p.strip() for p in args.split("|")]
    title = parts[0] if parts else ""
    due_date = parts[1] if len(parts) > 1 and parts[1] else None
    project = parts[2] if len(parts) > 2 and parts[2] else None
    return title, due_date, project

def _impl__print_tasks(status: str | None) -> None:
    tasks = list_tasks(status=status)
    if not tasks:
        label = status or "all"
        print(f"No {label} tasks.")
        return
    print(f"{'ID':<4} {'STATUS':<8} {'DUE':<12} {'PROJECT':<12} TITLE")
    print("-" * 60)
    for t in tasks:
        due = t["due_date"] or "-"
        project = t["project"] or "-"
        print(f"{t['id']:<4} {t['status']:<8} {due:<12} {project:<12} {t['title']}")

def _impl__print_world() -> None:
    """Read-only world model summary."""
    project = get_active_project()
    if project is None:
        print("No active project.")
        return
    pid = int(project["id"])
    state = get_project_state(pid)
    print(f"Project: {project['name']} ({project['status']})  slug={project['slug']}")
    if state:
        print(f"Phase:        {_state_display(state['phase'])}")
        print(f"Focus:        {_state_display(state['focus'])}")
        print(f"Risk:         {_state_display(state['current_risk'])}")
        print(f"Next action:  {_state_display(state['next_action'])}")
        print(f"What changed: {_state_display(state['what_changed'])}")
    print("\nRecent decisions:")
    decisions = list_decisions(pid, limit=5)
    if not decisions:
        print("  (none)")
    else:
        for d in reversed(decisions):
            print(f"  [{d['id']}] {d['summary']}")
    print("\nOpen loops:")
    loops = list_open_loops(pid)
    if not loops:
        print("  (none)")
    else:
        for loop in loops:
            print(f"  #{loop['id']} [p{loop['priority']}] {loop['description']}")
    print("\nOpen tasks:")
    tasks = list_tasks(status="open")[:5]
    if not tasks:
        print("  (none)")
    else:
        for t in tasks:
            print(f"  #{t['id']} {t['title']}")

def _impl__debug_extract(message: str) -> None:
    """Dry-run extraction proposal without applying changes."""
    attempt = should_attempt_state_extract(message)
    print(f"[debug] would attempt extraction: {'yes' if attempt else 'no'}")
    if not attempt:
        return
    recent = get_recent_extraction_context()
    world = get_active_world_context()
    proposals = propose_state_updates(message, recent, world)
    print("[debug] raw proposal JSON:")
    if proposals:
        print(json.dumps(proposals, indent=2))
    else:
        print("(none or parse failed)")
    validation = apply_state_proposals(
        proposals, dry_run=True, world_context=world, grounding_message=message
    )
    print("[debug] validation result:")
    print(json.dumps(validation, indent=2))

def _impl__debug_memories(limit: int = 20) -> None:
    """Print recent memory rows (debug-only)."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT id, type, importance, substr(timestamp,1,19), substr(content,1,80) "
            "FROM memories ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("[debug] no memories")
        return
    print(f"{'ID':<4} {'TYPE':<8} {'IMP':<4} {'TS':<20} CONTENT")
    print("-" * 70)
    for r in reversed(rows):
        print(f"{r[0]:<4} {r[1]:<8} {r[2]:<4} {r[3]:<20} {r[4]}")

def _impl__debug_sparks() -> None:
    """Print spark-specific stats (debug-only)."""
    conn = connect_db()
    try:
        trim = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE type='spark' AND importance = ?",
            (SPARK_IMPORTANCE_TRIM,),
        ).fetchone()[0]
        summary = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE type='spark' AND importance >= ?",
            (SPARK_IMPORTANCE_SUMMARY,),
        ).fetchone()[0]
        since = _last_summary_spark_timestamp(conn)
        pending = _count_messages_since_last_spark(conn)
        last = conn.execute(
            "SELECT id, importance, substr(content,1,100) FROM memories "
            "WHERE type='spark' ORDER BY id DESC LIMIT 3"
        ).fetchall()
    finally:
        conn.close()
    print(f"[debug] trim sparks: {trim}, summary sparks: {summary}")
    print(f"[debug] last summary spark ts: {since or '(none)'}")
    print(f"[debug] messages since last summary: {pending} (threshold {SPARK_MESSAGES_PER_SUMMARY})")
    if last:
        print("[debug] recent sparks:")
        for row in reversed(last):
            print(f"  #{row[0]} imp={row[1]} {row[2]}")

def _impl__debug_tasks() -> None:
    """Print all tasks (debug-only)."""
    _print_tasks(status=None)

def _impl__debug_brain() -> None:
    """Print model provider configuration (debug-only)."""
    print(f"[debug] Crowley version: {CROWLEY_VERSION}")
    print(f"[debug] configured provider: {get_model_provider_setting()}")
    print(f"[debug] resolved provider: {get_model_provider()}")
    print(f"[debug] OpenAI key present: {'yes' if _has_openai_key() else 'no'}")
    print(f"[debug] OpenAI model: {OPENAI_MODEL}")
    print(f"[debug] Ollama model: {OLLAMA_MODEL}")

def _impl__debug_memory_items(limit: int = 20) -> None:
    """Print recent memory_items rows (debug-only)."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM memory_items ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("[debug] no memory_items")
        return

    for row in rows:
        preview = _memory_display_text(row)
        if len(preview) > 100:
            preview = preview[:97] + "..."
        has_embedding = "yes" if row["embedding_blob"] else "no"
        confidence = row["confidence"] if "confidence" in row.keys() else 1.0
        print(
            f"[debug] #{row['id']} {row['memory_type']} "
            f"src={row['source']} imp={row['importance']} "
            f"conf={confidence} pinned={bool(row['pinned'])} "
            f"status={row['status']} project_id={row['project_id']}"
        )
        print(f"  preview: {preview}")
        print(f"  has_embedding: {has_embedding}")

def _impl__debug_retrieve(query: str) -> None:
    """Print hybrid retrieval results with score breakdown (debug-only)."""
    project = get_active_project()
    project_id = int(project["id"]) if project else None
    results = retrieve_memories(query, limit=10, project_id=project_id)
    print(f"Hybrid retrieval mode: {get_last_retrieval_mode()}")
    if not results:
        print("[debug] no memory_items matched")
        return
    for item in results:
        explanation = item.get("explanation") or {}
        print(
            f"[debug] #{item['id']} {item['memory_type']} "
            f"score={item['score']} pinned={item['pinned']} "
            f"status={item.get('status')} is_canon={item.get('is_canon')}"
        )
        print(f"  content: {item['content']}")
        breakdown = item["score_breakdown"]
        print(
            "  breakdown: "
            f"semantic={breakdown['semantic']} "
            f"keyword={breakdown['keyword']} "
            f"recency={breakdown['recency']} "
            f"importance={breakdown['importance']} "
            f"type_match={breakdown['type_match']} "
            f"project_match={breakdown['project_match']} "
            f"pinned_bonus={breakdown['pinned_bonus']}"
        )
        print(
            f"  source={item['source']} project_id={item['project_id']} "
            f"created_at={item['created_at']}"
        )
        if isinstance(explanation, dict):
            print(f"  retrieval_mode={explanation.get('retrieval_mode')}")
            print(f"  provenance_available={explanation.get('provenance_available')}")

def _impl__debug_knowledge(query: str) -> None:
    """Print scored knowledge file excerpts for a query (debug-only)."""
    entries = load_knowledge_files_context(query)
    print(f"[debug] knowledge files for: {query!r}")
    if not entries:
        print("[debug] (no files selected)")
        return
    for entry in entries:
        print(
            f"[debug] {entry['path']} | score={entry['score']} | "
            f"modified {entry['mtime']}"
        )
        excerpt = str(entry["excerpt"])
        preview = excerpt if len(excerpt) <= 400 else excerpt[:397] + "..."
        print(preview)
        print()

def _impl__debug_consolidate(args: str) -> None:
    """Run consolidation jobs (debug-only)."""
    parts = args.split()
    if not parts:
        print(
            "Usage: /debug consolidate <session|duplicates|stale|daily|all> [dry]"
        )
        return
    run_type = parts[0]
    dry_run = len(parts) > 1 and parts[1].lower() in ("dry", "dry-run")
    try:
        result = consolidate_memories(run_type, dry_run=dry_run)
    except ValueError as exc:
        print(f"[debug] {exc}")
        return
    print("[debug] consolidation result:")
    print(json.dumps(result, indent=2))

def _impl__debug_prompt(user_message: str) -> None:
    """Print the prompt Crowley would send (debug-only)."""
    prompt = build_prompt(user_message)
    print("[debug] system prompt:")
    print(prompt[0]["content"])
    if len(prompt) > 2:
        print(f"[debug] chat context ({len(prompt) - 2} prior turn(s)):")
        for msg in prompt[1:-1]:
            print(f"  [{msg['role']}] {msg['content'][:120]}")
    print("[debug] user message:")
    print(prompt[-1]["content"])

def _impl__handle_command(line: str) -> bool:
    """Handle slash commands. Return True if handled (don't call model)."""
    if line.startswith("/debug"):
        args = line[len("/debug") :].strip()
        if args == "memories":
            _debug_memories()
        elif args == "memory-items" or args == "memory_items":
            _debug_memory_items()
        elif args == "sparks":
            _debug_sparks()
        elif args == "tasks":
            _debug_tasks()
        elif args == "brain":
            _debug_brain()
        elif args.startswith("retrieve"):
            msg = args[len("retrieve") :].strip()
            if not msg:
                print("Usage: /debug retrieve <query>")
                return True
            _debug_retrieve(msg)
        elif args.startswith("knowledge"):
            msg = args[len("knowledge") :].strip()
            if not msg:
                print("Usage: /debug knowledge <query>")
                return True
            _debug_knowledge(msg)
        elif args.startswith("prompt"):
            msg = args[6:].strip() or "diagnostics"
            _debug_prompt(msg)
        elif args.startswith("extract"):
            msg = args[7:].strip()
            if not msg:
                print("Usage: /debug extract <message>")
                return True
            _debug_extract(msg)
        elif args == "world":
            _print_world()
        elif args == "bus":
            _debug_bus()
        elif args.startswith("consolidate"):
            _debug_consolidate(args[len("consolidate") :].strip())
        else:
            print(
                "[debug] commands: memories, memory-items, sparks, tasks, brain, "
                "world, bus, consolidate <type> [dry], retrieve <query>, "
                "knowledge <query>, prompt [message], extract <message>"
            )
        return True

    if line == "/world":
        _print_world()
        return True

    if line.startswith("/remember"):
        args = line[len("/remember") :].strip()
        parsed = _parse_remember(args)
        if not parsed:
            print("Usage: /remember type | importance | content  (importance 1–5)")
            return True
        memory_type, importance, content = parsed
        save_memory(
            memory_type,
            content,
            importance,
            source="manual",
            pinned=True,
            confidence=1.0,
        )
        print(f"Remembered [{memory_type}|{importance}]: {content}")
        return True

    if line.startswith("/task"):
        args = line[len("/task") :].strip()
        if args.startswith("add "):
            title, due_date, project = _parse_task_add(args[4:].strip())
            if not title:
                print("Usage: /task add title | due_date | project")
                return True
            task_id = save_task(title, due_date=due_date, project=project)
            print(f"Task #{task_id} added: {title}")
            return True
        if args == "list" or args == "list all":
            status = None if args == "list all" else "open"
            _print_tasks(status)
            return True
        if args.startswith("done "):
            id_text = args[5:].strip()
            try:
                task_id = int(id_text)
            except ValueError:
                print("Usage: /task done <id>")
                return True
            task = get_task_by_id(task_id)
            if task is None:
                print(f"Task #{task_id} not found.")
                return True
            if complete_task(task_id):
                print(f"Task #{task_id} done: {task['title']}")
            else:
                print(f"Task #{task_id} already done.")
            return True
        print("Usage: /task add title | due_date | project")
        print("       /task list [all]")
        print("       /task done <id>")
        return True

    if line.startswith("/state"):
        args = line[len("/state") :].strip()
        project = get_active_project()
        if project is None:
            print("No active project.")
            return True
        pid = int(project["id"])
        if not args:
            _print_state()
            return True
        if args.startswith("set "):
            parsed = _parse_state_set(args)
            if not parsed:
                print("Usage: /state set phase: <value>")
                print("       /state set focus: <value>")
                print("       /state set risk: <value>")
                print("       /state set next_action: <value>")
                print("       /state set what_changed: <value>")
                return True
            field, value = parsed
            update_project_state_field(pid, field, value)
            print(f"State updated — {field}: {value}")
            return True
        print("Usage: /state")
        print("       /state set <field>: <value>")
        return True

    if line.startswith("/decisions"):
        args = line[len("/decisions") :].strip()
        project = get_active_project()
        if project is None:
            print("No active project.")
            return True
        pid = int(project["id"])
        if args.startswith("add "):
            summary, detail = _parse_pipe_pair(args[4:].strip())
            if not summary:
                print("Usage: /decisions add summary | detail")
                return True
            dec_id = save_decision(pid, summary, detail or None)
            print(f"Decision #{dec_id} logged: {summary}")
            return True
        if not args:
            _print_decisions()
            return True
        print("Usage: /decisions")
        print("       /decisions add summary | detail")
        return True

    if line.startswith("/loops"):
        args = line[len("/loops") :].strip()
        project = get_active_project()
        if project is None:
            print("No active project.")
            return True
        pid = int(project["id"])
        if args.startswith("add "):
            description, priority_str = _parse_pipe_pair(args[4:].strip())
            if not description:
                print("Usage: /loops add description | priority")
                return True
            priority = 3
            if priority_str:
                try:
                    priority = int(priority_str)
                except ValueError:
                    print("Priority must be an integer 1–5.")
                    return True
                if priority < 1 or priority > 5:
                    print("Priority must be 1–5.")
                    return True
            loop_id = save_open_loop(pid, description, priority=priority)
            print(f"Open loop #{loop_id} added: {description}")
            return True
        if args.startswith("done "):
            loop_id_str = args[5:].strip()
            try:
                loop_id = int(loop_id_str)
            except ValueError:
                print("Usage: /loops done <id>")
                return True
            if close_open_loop(loop_id):
                print(f"Open loop #{loop_id} closed.")
            else:
                print(f"Open loop #{loop_id} not found or already closed.")
            return True
        if not args:
            _print_loops()
            return True
        print("Usage: /loops")
        print("       /loops add description | priority")
        print("       /loops done <id>")
        return True

    if line.startswith("/diagnostics"):
        args = line[len("/diagnostics") :].strip()
        if args:
            print("Usage: /diagnostics")
            return True
        run_diagnostics()
        return True

    return False

def _impl__run_cli_consolidate() -> bool:
    """Non-interactive consolidation entrypoint: python crowley.py --consolidate [type]."""
    import sys

    argv = sys.argv[1:]
    if not argv or argv[0] != "--consolidate":
        return False
    run_type = "all"
    dry_run = False
    for token in argv[1:]:
        if token == "--dry-run":
            dry_run = True
        elif not token.startswith("-"):
            run_type = token
    setup_db()
    try:
        result = consolidate_memories(run_type, dry_run=dry_run)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2))
    return True

def _impl__run_cli_hygiene() -> bool:
    """Non-interactive hygiene report: python crowley.py --hygiene."""
    import sys

    argv = sys.argv[1:]
    if not argv or argv[0] != "--hygiene":
        return False
    setup_db()
    print(json.dumps(memory_hygiene_report(), indent=2))
    return True

def _impl_main() -> None:
    """Set up the DB and run the interactive CLI loop."""
    setup_db()
    start_spark_timer()
    print("Crowley online.\n")
    print(f"Morning, {USER_NAME}.\n")
    print("Memory: online")
    print("Tasks: online")
    print(f"Brain: {_brain_banner_label()}\n")
    print("Type 'exit' to quit.")

    while True:
        try:
            line = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not line:
            continue

        if line.lower() in ("exit", "/exit"):
            break

        if _handle_command(line):
            continue

        if is_diagnostics_request(line):
            run_diagnostics()
            continue

        ask_crowley(line)
