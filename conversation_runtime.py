"""Extracted V4.1 conversation runtime implementation."""

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

def classify_conversation_mode(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_classify_conversation_mode, rt, *args, **kwargs)

def conversation_mode_answer_shape(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_conversation_mode_answer_shape, rt, *args, **kwargs)

def _format_conversation_mode_prompt_section(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__format_conversation_mode_prompt_section, rt, *args, **kwargs)

def classify_response_depth(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_classify_response_depth, rt, *args, **kwargs)

def response_depth_expectation(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_response_depth_expectation, rt, *args, **kwargs)

def _format_response_depth_prompt_section(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__format_response_depth_prompt_section, rt, *args, **kwargs)

def _personality_prompt(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__personality_prompt, rt, *args, **kwargs)

def _ground_truth_prompt(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__ground_truth_prompt, rt, *args, **kwargs)

def _greeting_behavior_prompt(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl__greeting_behavior_prompt, rt, *args, **kwargs)

def build_prompt(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_build_prompt, rt, *args, **kwargs)

def chat_turn(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_chat_turn, rt, *args, **kwargs)

def ask_crowley(rt: Any = _MISSING, *args: Any, **kwargs: Any) -> Any:
    return _dispatch(_impl_ask_crowley, rt, *args, **kwargs)

def _impl_classify_conversation_mode(message: str) -> str:
    """Infer conversation mode from user phrasing — deterministic, no model call."""
    trimmed = _normalize_text(message)
    if not trimmed:
        return "casual"

    lower = trimmed.lower()

    if is_diagnostics_request(trimmed):
        return "diagnostics"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bdebug\b",
            r"root cause",
            r"\btrace\b",
            r"investigate why",
            r"why (is|are|does|did|won't|isn't|wasn't)",
            r"figure out why",
        )
    ):
        return "debug"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bbug\b",
            r"\bbroken\b",
            r"doesn't work",
            r"does not work",
            r"\bnot working\b",
            r"\bcrash",
            r"\bfails?\b",
            r"\bregression\b",
            r"something broke",
            r"\bhanging\b",
            r"\bhangs\b",
            r"\bhang\b(?!\s+out)",
            r"\bstuck\b",
            r"something(?:'s| is|s) up",
            r"\b(?:is|are|was|were|keeps?|still)\s+struggling\b",
            r"\bstruggling\s+to\s+(?:load|stream|respond|connect|sync|start|finish|complete)\b",
        )
    ):
        return "bug"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bstatus\b",
            r"quick status",
            r"what changed",
            r"any update",
            r"where are we",
            r"what(?:'s| is) open",
            r"what tickets are open",
            r"which tickets are open",
            r"last heard from",
            r"when (?:did|was).{0,24}(?:cursor|codex)",
            r"update from (?:cursor|codex)",
            r"catch me up",
            r"what shipped",
        )
    ):
        return "status"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bplan(?:ning)?\b",
            r"\broadmap\b",
            r"next step",
            r"break (?:this )?down",
            r"how should we",
            r"\bprioritize\b",
            r"ticket slice",
            r"mint ticket",
            r"strategy for",
        )
    ):
        return "planning"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"thoughts on",
            r"what if",
            r"\bexplore\b",
            r"brainstorm",
            r"ideas for",
            r"long[- ]horizon",
            r"long[- ]term",
            r"\beventually\b",
            r"your opinion",
            r"walk me through",
        )
    ):
        return "exploration"

    return "casual"

def _impl_conversation_mode_answer_shape(mode: str) -> str:
    """Expected answer shape for an inferred conversation mode."""
    return _CONVERSATION_MODE_SHAPES.get(mode, _CONVERSATION_MODE_SHAPES["casual"])

def _impl__format_conversation_mode_prompt_section(mode: str) -> str:
    shape = conversation_mode_answer_shape(mode)
    return f"Conversation mode (inferred): {mode}\nExpected answer shape: {shape}"

def _impl_classify_response_depth(message: str, *, mode: str | None = None) -> str:
    """Infer response depth from user phrasing and conversation mode."""
    trimmed = _normalize_text(message)
    if mode is None:
        mode = classify_conversation_mode(trimmed)

    if mode in ("planning", "exploration"):
        return "deep"
    if mode in ("status", "diagnostics"):
        return "brief"

    lower = trimmed.lower()
    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bcheck\b",
            r"any update",
            r"what changed",
            r"quick status",
            r"catch me up",
            r"what shipped",
        )
    ):
        return "brief"

    return "standard"

def _impl_response_depth_expectation(depth: str) -> str:
    """Expected answer length for a response depth."""
    return _RESPONSE_DEPTH_EXPECTATIONS.get(
        depth, _RESPONSE_DEPTH_EXPECTATIONS["standard"]
    )

def _impl__format_response_depth_prompt_section(depth: str) -> str:
    expectation = response_depth_expectation(depth)
    return f"Response depth (inferred): {depth}\nAnswer length: {expectation}"

def _impl__personality_prompt() -> str:
    return f"""You are Crowley — not an assistant talking about Crowley, but the running system on this machine: SQLite memory, world model, hybrid retrieval, passive extraction, the context bridge at 127.0.0.1:8765, and the chat {USER_NAME} is in right now. The readout blocks below are your own state.

In the pipeline: Codex architects (plans, decisions). Cursor builds (ships code). They post handoffs into your memory — you hold truth and speak from the cockpit with {USER_NAME}. You don't code in Cursor's lane or plan in Codex's lane unless {USER_NAME} is working with you directly on Crowley internals.

Voice: project co-founder — warm, direct, useful, willing to have a point of view. Partner to {USER_NAME} without subservience. Match the moment; skip filler and performance. Address {USER_NAME} by name; an occasional "{USER_NAME_PERSONALITY}" is fine when the moment calls for warmth or personality — default to {USER_NAME}.

Read the message before you respond. Notice what kind of moment it is and let that set the shape of your reply.

When they're loose or incomplete on purpose, meet them there. Wondering out loud and "thoughts?" are invitations to think with them.

When they're executing, be concrete. When they're exploring, explore. When they're stuck, help them move.

Honor the inferred Response depth and Conversation mode in this prompt — when depth is brief, stay tight; when depth is deep, give room to think with them.

When the conversation touches facts — version, what shipped, what's stored, what the system is doing — speak from the filesystem readout first, then live DB state, then memory below.

You're allowed to prefer one path, push back, or say you don't like something when that's what the moment needs."""

def _impl__ground_truth_prompt() -> str:
    return f"""When {USER_NAME} asks when you last heard from Codex or Cursor, answer from the Agent activity timestamps — never from chat memory or vague recency like "yesterday" unless the timestamp supports it.

When asked what work is open, assigned, or blocked, answer from the Tickets block — not from hybrid memory alone.

When a fact about the project matters:
1. Filesystem truth first — then tickets — then agent activity — then live DB state — then canon — then supporting memory (hybrid retrieval).
2. On conflict: filesystem and source-of-truth files win; then tickets; then agent activity timestamps; then live DB state; then canon; then hybrid retrieval.
3. For what changed and what now: agent activity beats project_state and beats supporting memory — never answer from stale memory when fresher handoff timestamps exist.
4. Use what you find. If it isn't there, say you don't have it stored — then stay in the conversation.

Do not invent project history, release versions, or personal details."""

def _impl__greeting_behavior_prompt() -> str:
    """Session-aware cue — ongoing vs fresh thread."""
    recent = list_chat_context_messages(limit=CHAT_CONTEXT_LIMIT)
    has_prior_assistant = any(str(row["role"]) == "assistant" for row in recent)
    if has_prior_assistant:
        return "Session: ongoing thread — continue from context, don't reset the room."
    return "Session: first reply in this thread."

def _impl_build_prompt(
    user_message: str,
    *,
    exclude_message_id: int | None = None,
) -> list[dict[str, str]]:
    """Compose system prompt with memories, tasks, and recent chat context."""
    project = get_active_project()
    active_project_id = int(project["id"]) if project else None
    memories = retrieve_memories(
        user_message, limit=MEMORY_LIMIT, project_id=active_project_id
    )
    canon_rows = list_canon_memory_items(active_project_id)
    tasks = list_tasks(status="open")[:TASK_LIMIT]

    memory_lines = []
    for m in memories:
        reason = m.get("inclusion_reason")
        reason_suffix = f" — {reason}" if reason else ""
        line = (
            f"[{m['memory_type']} | score {m['score']:.2f} | importance {m['importance']}] "
            f"{m['content']}{reason_suffix}"
        )
        if len(line) > MEMORY_LINE_MAX:
            line = line[: MEMORY_LINE_MAX - 3] + "..."
        memory_lines.append(line)

    task_lines = []
    for t in tasks:
        due = t["due_date"] or "no due date"
        project = t["project"] or "general"
        task_lines.append(f"- #{t['id']} {t['title']} (due: {due}, project: {project})")

    system_parts = [_personality_prompt(), _greeting_behavior_prompt()]

    mode = classify_conversation_mode(user_message)
    system_parts.append(_format_conversation_mode_prompt_section(mode))

    depth = classify_response_depth(user_message, mode=mode)
    system_parts.append(_format_response_depth_prompt_section(depth))

    knowledge_entries = load_knowledge_files_context(user_message)
    system_parts.append(_format_knowledge_files_prompt_section(knowledge_entries))

    system_parts.append(_format_tickets_prompt_section(active_project_id))

    system_parts.append(_format_agent_activity_prompt_section(active_project_id))

    world_ctx = get_active_world_context()
    if world_ctx:
        system_parts.append(_format_world_context_section(world_ctx))

    task_frame_section = _format_task_frame_prompt_section(active_project_id)
    if task_frame_section:
        system_parts.append(task_frame_section)

    system_parts.append(_format_canon_prompt_section(canon_rows))

    if memory_lines:
        system_parts.append(
            "Supporting memory (hybrid retrieval — lower authority than filesystem truth):\n"
            + "\n".join(memory_lines)
        )
    else:
        system_parts.append(
            "Supporting memory (hybrid retrieval — lower authority than filesystem truth): (none retrieved)"
        )

    if task_lines:
        system_parts.append("Open tasks:\n" + "\n".join(task_lines))

    system_parts.append(_ground_truth_prompt())

    prompt_messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
    ]

    for row in list_chat_context_messages(
        limit=CHAT_CONTEXT_LIMIT,
        exclude_message_id=exclude_message_id,
    ):
        prompt_messages.append(
            {
                "role": str(row["role"]),
                "content": _cap_chat_context_content(str(row["content"])),
            }
        )

    prompt_messages.append({"role": "user", "content": user_message})
    return prompt_messages

def _impl_chat_turn(
    user_message: str,
    on_token: Callable[[str], None] | None = None,
    *,
    quiet_errors: bool = False,
) -> ChatTurnResult:
    """
    Shared chat pipeline: save user message, infer reply, save assistant,
    then passive spark and world-model extraction hooks.
    """
    user_message_id = save_message("user", user_message)
    messages = build_prompt(user_message, exclude_message_id=user_message_id)
    reply = call_model(
        messages, stream=True, quiet=quiet_errors, on_token=on_token
    )
    if reply is None:
        return ChatTurnResult(
            user_message_id=user_message_id,
            assistant_message_id=None,
            reply=None,
            error="model unavailable",
        )
    if not reply:
        return ChatTurnResult(
            user_message_id=user_message_id,
            assistant_message_id=None,
            reply=None,
            error="empty response",
        )

    assistant_message_id = save_message("assistant", reply)
    maybe_create_spark()
    maybe_extract_state(user_message, user_message_id)
    return ChatTurnResult(
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        reply=reply,
    )

def _impl_ask_crowley(user_message: str) -> None:
    """Retrieve context, stream the model reply, save the exchange, spark, and extract."""
    print("Crowley: thinking...", flush=True)
    started = False

    def on_token(token: str) -> None:
        nonlocal started
        started = _print_stream_token(token, started)

    result = chat_turn(user_message, on_token=on_token, quiet_errors=False)
    if result.reply is None and not started:
        return
    if started:
        print(flush=True)
