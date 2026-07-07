"""V3.9.17+ agent behavior layer — retrieval policy, chaining, validation, observability."""

from __future__ import annotations

import os
import threading
import time
from typing import Literal

IntentDomain = Literal["tickets", "recent_work", "code", "memory", "system", "general"]

SYSTEM_QUERY_KEYWORDS: tuple[str, ...] = (
    "ticket",
    "tickets",
    "qa",
    "debug",
    "repo",
    "github",
    "recent work",
    "handoff",
    "what shipped",
    "what changed",
    "status",
    "focus",
    "version",
    "crowley",
)

RETRIEVAL_POLICY: list[dict[str, object]] = [
    {
        "intent": "tickets",
        "tools": ["ticket.list", "ticket.get", "planning.ticket"],
        "when": "Questions about open work, assignments, ticket detail",
    },
    {
        "intent": "recent_work",
        "tools": ["handoff.list", "handoff.get", "inspect.recent_updates"],
        "when": "Latest builder/architect activity, what Cursor/Codex shipped",
    },
    {
        "intent": "code",
        "tools": ["github.status", "github.file", "github.search_code", "github.compare"],
        "when": "Repository files, CI, diffs, code search",
    },
    {
        "intent": "memory",
        "tools": ["context.get", "retrieve.search", "memory.get", "memory.list"],
        "when": "Project memory, decisions, constraints, context",
    },
    {
        "intent": "system",
        "tools": ["agent.sync", "qa.bundle", "planning.release"],
        "when": "Orientation, version, health, phase, release state",
    },
]

CHAINING_POLICY: dict[str, object] = {
    "max_chain_depth": 3,
    "rule": "If initial read is incomplete or ambiguous, chain 1–2 additional read tools before answering",
    "examples": [
        "ticket.list → ticket.get for detail",
        "handoff.list → memory.get for linked handoff",
        "retrieve.search → memory.why_retrieved for explainability",
    ],
}

MANDATORY_RETRIEVAL_RULES: list[dict[str, object]] = [
    {
        "domain": "tickets",
        "required_tools": ["ticket.list", "ticket.get", "planning.ticket"],
        "rule": "Do not answer ticket questions without retrieving ticket data",
    },
    {
        "domain": "recent_work",
        "required_tools": ["handoff.list"],
        "rule": "Do not answer what-shipped questions without handoff feed",
    },
    {
        "domain": "code",
        "required_tools": ["github."],
        "prefix_match": True,
        "rule": "Do not answer repo questions without github.* read",
    },
    {
        "domain": "memory",
        "required_tools": ["context.get", "retrieve.search", "memory."],
        "prefix_match": True,
        "rule": "Do not answer memory questions without context/retrieve",
    },
]

PRE_RESPONSE_CHECKLIST: list[dict[str, object]] = [
    {"item": "agent.sync executed", "state_key": "synced"},
    {"item": "recent handoffs loaded", "state_key": "handoffs_loaded"},
    {"item": "relevant domain data retrieved", "state_key": "domain_retrieved"},
]

COMPLEX_QUERY_KEYWORDS: tuple[str, ...] = (
    "review system",
    "system-wide",
    "full arc",
    "end to end",
    "audit",
    "consistency",
    "cross-check",
    "holistic",
    "entire system",
)

PROACTIVE_CHAIN_POLICY: dict[str, object] = {
    "min_chain_depth": 2,
    "required_tool_groups": [
        ["handoff.list", "agent.sync"],
        ["github.status", "github.file", "github.search_code"],
        ["context.get", "retrieve.search"],
    ],
    "triggers": list(COMPLEX_QUERY_KEYWORDS),
}

GATE_EXEMPT_TOOLS = frozenset({
    "agent.sync",
    "inspect.retrieval_observability",
    "context.get",
    "portable.packet",
})

RETRIEVAL_TOOL_PREFIXES = (
    "ticket.",
    "handoff.",
    "github.",
    "memory.",
    "context.",
    "retrieve.",
    "inspect.recent",
    "agent.sync",
    "planning.ticket",
    "qa.bundle",
)

PRE_RESPONSE_ENFORCED = True

QA_CROWLEY_CONTEXT_VALIDATION: dict[str, object] = {
    "required_checks": [
        "verify against recent handoffs (handoff.list or sync bundle feed)",
        "consistency with memory and prior system state",
        "detection of contradictions vs tickets/agent_activity",
    ],
    "must_reference": [
        "actual Crowley retrievals from this session",
        "handoff.list or agent.sync recent_handoffs block",
        "not isolated code assumptions",
    ],
}

_lock = threading.Lock()
_session_state: dict[str, dict[str, object]] = {}
_retrieval_log: dict[str, list[dict[str, object]]] = {}
_current_dispatch_id: dict[str, int] = {}
_REQUEST_CYCLE_TTL = 300


def _now() -> float:
    return time.time()


def _session_persist_enabled() -> bool:
    return os.environ.get("CROWLEY_TEST_MODE") != "1"


def _persist_state(session_key: str, state: dict[str, object]) -> None:
    if not _session_persist_enabled():
        return
    try:
        import observability_store

        observability_store.save_session_state(session_key, state)
    except Exception:
        pass


def _get_state(session_key: str) -> dict[str, object]:
    with _lock:
        state = _session_state.get(session_key)
        if state is None or _now() - float(state.get("_ts", 0)) > _REQUEST_CYCLE_TTL:
            state = {
                "_ts": _now(),
                "synced": False,
                "sync_count": 0,
                "handoffs_loaded": False,
                "domain_retrieved": False,
                "tools_called": [],
                "chain_depth": 0,
                "intents_seen": [],
                "pending_query": None,
                "complex_query": False,
                "planner_attempts": 0,
            }
            try:
                import observability_store

                if _session_persist_enabled():
                    loaded = observability_store.load_session_state(session_key)
                    if loaded:
                        state.update(loaded)
            except Exception:
                pass
            _session_state[session_key] = state
        state["_ts"] = _now()
        return state


def reset_request_cycle(session_key: str) -> None:
    with _lock:
        _session_state.pop(session_key, None)
        _retrieval_log.pop(session_key, None)
        _current_dispatch_id.pop(session_key, None)
    try:
        import observability_store

        if _session_persist_enabled():
            observability_store.delete_session_state(session_key)
    except Exception:
        pass


def begin_dispatch(session_key: str, dispatch_id: int) -> None:
    """#166 — bind observability reads to the active dispatch for this session."""
    with _lock:
        _current_dispatch_id[session_key] = int(dispatch_id)
    state = _get_state(session_key)
    state["current_dispatch_id"] = int(dispatch_id)


def current_dispatch_id(session_key: str) -> int | None:
    with _lock:
        active = _current_dispatch_id.get(session_key)
    if active is not None:
        return int(active)
    state = _get_state(session_key)
    raw = state.get("current_dispatch_id")
    return int(raw) if raw is not None else None


def _tools_from_log(session_key: str, *, dispatch_id: int | None = None) -> list[str]:
    with _lock:
        log = list(_retrieval_log.get(session_key, []))
    tools: list[str] = []
    for entry in log:
        if not isinstance(entry, dict):
            continue
        if dispatch_id is not None and entry.get("dispatch_id") != dispatch_id:
            continue
        tool = str(entry.get("tool_called") or entry.get("tool") or "").strip()
        if tool:
            tools.append(tool)
    return tools


def mark_synced(session_key: str) -> None:
    apply_agent_sync_completion(session_key)


def apply_agent_sync_completion(session_key: str, *, dispatch_id: int | None = None) -> None:
    """Legacy helper — prefer record_agent_sync_dispatch after #166."""
    record_tool_call(
        session_key,
        "agent.sync",
        triggering_rule="sync",
        dispatch_id=dispatch_id,
    )


def record_agent_sync_dispatch(
    session_key: str,
    dispatch_id: int,
    *,
    reason: str | None = None,
) -> dict[str, object]:
    """Register agent.sync in the shared observability buffer for this dispatch."""
    import system_integrity

    return system_integrity.record_dispatch_observability(
        session_key,
        "agent.sync",
        dispatch_id=dispatch_id,
        query_text=reason,
        triggering_rule="sync",
        http_status=200,
    )


def attach_agent_sync_runtime(
    session_key: str,
    dispatch_id: int,
    bundle: dict[str, object],
    *,
    tool_names: list[str] | None = None,
) -> dict[str, object]:
    """Attach runtime validation after agent.sync is registered in observability."""
    import memory_quality
    import system_integrity
    import workflow

    bundle["agent_behavior"] = behavior_payload()
    bundle["pre_response_validation"] = validate_retrieval_state(
        session_key,
        dispatch_id=dispatch_id,
    )
    bundle["system_integrity"] = system_integrity.integrity_payload()
    bundle["memory_quality"] = memory_quality.quality_payload()
    bundle["invariant_checks"] = system_integrity.run_invariant_checks(
        "sync",
        session_key=session_key,
    )
    if tool_names is not None:
        bundle["workflow"] = workflow.workflow_enforcement_payload(tool_names=tool_names)
    bundle["dispatch_id"] = dispatch_id
    bundle["session_key"] = session_key
    return bundle


def _observed_tools(session_key: str, dispatch_id: int | None = None) -> list[str]:
    """#162/#166 — session cycle tools; optional dispatch filter for log fallback."""
    from_log = _tools_from_log(session_key)
    if dispatch_id is not None:
        dispatch_log_tools = _tools_from_log(session_key, dispatch_id=dispatch_id)
        if dispatch_log_tools:
            from_log = dispatch_log_tools + [t for t in from_log if t not in dispatch_log_tools]
    state = _get_state(session_key)
    from_state: list[str] = list(state.get("tools_called", []))  # type: ignore[arg-type]
    merged: list[str] = []
    seen: set[str] = set()
    for tool in from_log + from_state:
        if tool and tool not in seen:
            seen.add(tool)
            merged.append(tool)
    return merged


def _checklist_from_observed_tools(tools: list[str]) -> dict[str, bool]:
    """Derive pre-response checklist from observed tool calls (#162)."""
    synced = "agent.sync" in tools
    handoffs_loaded = synced or "handoff.list" in tools or "inspect.recent_updates" in tools
    domain_retrieved = any(
        t.startswith(("ticket.", "github.", "memory.", "context.", "retrieve.", "handoff."))
        or t in {"planning.ticket", "qa.bundle", "agent.sync"}
        for t in tools
    )
    return {
        "synced": synced,
        "handoffs_loaded": handoffs_loaded,
        "domain_retrieved": domain_retrieved,
    }


def _refresh_checklist_from_tools(session_key: str, *, dispatch_id: int | None = None) -> None:
    """Sync legacy state flags from observed execution trace."""
    tools = _observed_tools(session_key, dispatch_id=dispatch_id)
    observed = _checklist_from_observed_tools(tools)
    state = _get_state(session_key)
    state["tools_called"] = tools
    if observed["synced"] or int(state.get("sync_count", 0)) > 0:
        state["synced"] = True
    else:
        state["synced"] = observed["synced"]
    state["handoffs_loaded"] = observed["handoffs_loaded"]
    state["domain_retrieved"] = observed["domain_retrieved"]
    if "agent.sync" in tools:
        state["sync_count"] = max(int(state.get("sync_count", 0)), 1)


def classify_intent(text: str | None) -> IntentDomain:
    if not text or not str(text).strip():
        return "general"
    lower = str(text).lower()
    if any(kw in lower for kw in ("ticket", "assignee", "blocked", "#")):
        return "tickets"
    if any(kw in lower for kw in ("handoff", "shipped", "cursor", "codex", "recent work")):
        return "recent_work"
    if any(kw in lower for kw in ("github", "repo", "file", "diff", "ci", "commit")):
        return "code"
    if any(kw in lower for kw in ("memory", "retrieve", "context", "decision", "constraint")):
        return "memory"
    if any(kw in lower for kw in SYSTEM_QUERY_KEYWORDS):
        return "system"
    return "general"


def is_system_level_query(text: str | None) -> bool:
    if not text:
        return False
    lower = str(text).lower()
    return any(kw in lower for kw in SYSTEM_QUERY_KEYWORDS)


def is_complex_query(text: str | None) -> bool:
    """#134 — heuristic for proactive multi-step retrieval."""
    if not text:
        return False
    lower = str(text).lower()
    return any(kw in lower for kw in COMPLEX_QUERY_KEYWORDS)


def is_retrieval_tool(tool_name: str) -> bool:
    if tool_name in GATE_EXEMPT_TOOLS:
        return True
    return any(
        tool_name == prefix.rstrip(".") or tool_name.startswith(prefix.rstrip("."))
        for prefix in RETRIEVAL_TOOL_PREFIXES
    )


def _note_query_context(session_key: str, query_text: str | None) -> IntentDomain:
    state = _get_state(session_key)
    if query_text and str(query_text).strip():
        intent = classify_intent(query_text)
        state["pending_query"] = str(query_text).strip()
        state["complex_query"] = is_complex_query(query_text)
        intents: list[str] = list(state.get("intents_seen", []))  # type: ignore[arg-type]
        if intent not in intents:
            intents.append(intent)
        state["intents_seen"] = intents
        return intent
    pending = state.get("pending_query")
    if pending:
        return classify_intent(str(pending))
    intents = state.get("intents_seen", [])
    if intents:
        return str(intents[0])  # type: ignore[return-value]
    return "general"


def _domain_retrieval_satisfied(session_key: str, domain: str) -> bool:
    validation = validate_retrieval_state(session_key, intent=domain)
    return not validation.get("missing_requirements")


def tool_satisfies_intent(tool_name: str, intent: str) -> bool:
    for required in tools_for_intent(intent):
        if tool_name == required:
            return True
        if required.endswith(".") and tool_name.startswith(required.rstrip(".")):
            return True
    if intent == "code" and tool_name.startswith("github."):
        return True
    if intent == "memory" and tool_name.startswith(("memory.", "context.", "retrieve.")):
        return True
    return False


def check_domain_retrieval_gate(
    session_key: str,
    tool_name: str,
    *,
    query_text: str | None = None,
) -> tuple[bool, str | None, dict[str, object]]:
    """#133 — deterministic domain triggers; block until required reads fire."""
    intent = _note_query_context(session_key, query_text)
    if intent == "general":
        return True, None, {}
    if tool_name in GATE_EXEMPT_TOOLS or tool_name == "agent.sync":
        return True, None, {}
    if tool_satisfies_intent(tool_name, intent):
        return True, None, {"intent": intent, "trigger": "domain_retrieval"}
    if _domain_retrieval_satisfied(session_key, intent):
        return True, None, {"intent": intent}
    required = tools_for_intent(intent)
    return (
        False,
        f"domain_retrieval_required: {intent} queries require {required[0]} before {tool_name}",
        {
            "intent": intent,
            "required_tools": required,
            "triggering_rule": "domain_trigger",
        },
    )


def check_pre_response_gate(
    session_key: str,
    tool_name: str,
    *,
    query_text: str | None = None,
    kind: str = "read",
) -> tuple[bool, str | None, dict[str, object]]:
    """#132 — enforced pre-response gating with explicit retry path."""
    if not PRE_RESPONSE_ENFORCED:
        return True, None, {}
    if tool_name in GATE_EXEMPT_TOOLS or tool_name == "agent.sync":
        return True, None, {}
    if tool_name in {"handoff.ingest", "writeback.ingest", "writeback.parse", "audit.rollback"}:
        return True, None, {}
    if is_retrieval_tool(tool_name):
        return True, None, {}

    state = _get_state(session_key)
    plan = state.get("execution_plan") or state.get("domain_plan")
    plan_domains = list(plan.get("domains", [])) if isinstance(plan, dict) else []

    if plan_domains:
        missing_all: list[str] = []
        validations: list[dict[str, object]] = []
        retry_path: list[str] = []
        seen_retry: set[str] = set()
        for domain in plan_domains:
            validation = validate_retrieval_state(session_key, intent=str(domain))
            validations.append(validation)
            missing_all.extend(str(m) for m in validation.get("missing_requirements", []))
            for tool in tools_for_intent(str(domain)):
                if tool not in seen_retry:
                    seen_retry.add(tool)
                    retry_path.append(tool)
        if isinstance(plan, dict):
            for tool in plan.get("tool_order", []):
                if str(tool) not in seen_retry:
                    seen_retry.add(str(tool))
                    retry_path.insert(0, str(tool))
        ready = all(bool(v.get("ready")) for v in validations)
        if ready:
            return True, None, {"gates_use_planner_output": True, "execution_plan": plan}
        if not any(v.get("checklist", [{}])[0].get("passed") for v in validations if v.get("checklist")):
            if "agent.sync" not in retry_path:
                retry_path.insert(0, "agent.sync")
        return (
            False,
            "context_not_ready: complete execution plan retrieval before this action",
            {
                "pre_response_validation": validations[-1] if validations else {},
                "validations": validations,
                "retry_path": retry_path,
                "execution_plan": plan,
                "gates_use_planner_output": True,
                "triggering_rule": "pre_response_gate",
            },
        )

    intent = _note_query_context(session_key, query_text)
    validation = validate_retrieval_state(session_key, intent=intent)
    if validation.get("ready"):
        return True, None, {}

    retry_path = list(tools_for_intent(intent))
    if not validation.get("checklist", [{}])[0].get("passed"):
        retry_path.insert(0, "agent.sync")
    if not any(c.get("passed") for c in validation.get("checklist", []) if c.get("item") == "recent handoffs loaded"):
        if "handoff.list" not in retry_path:
            retry_path.append("handoff.list")

    return (
        False,
        "context_not_ready: complete required retrieval before this action",
        {
            "pre_response_validation": validation,
            "retry_path": retry_path,
            "triggering_rule": "pre_response_gate",
        },
    )


def check_sync_for_system_query(
    session_key: str,
    *,
    query_text: str | None = None,
    tool_name: str | None = None,
) -> tuple[bool, str | None]:
    """#123 — system queries require sync; dedupe sync within request cycle."""
    state = _get_state(session_key)
    if tool_name == "agent.sync":
        sync_count = int(state.get("sync_count", 0))
        if sync_count >= 1:
            return True, "sync_deduped: agent.sync already called this request cycle"
        state["sync_count"] = sync_count + 1
        state["synced"] = True
        return True, None

    needs_sync = is_system_level_query(query_text) or classify_intent(query_text) != "general"
    if needs_sync and not state.get("synced"):
        return (
            False,
            "sync_required: system-level query requires agent.sync before reasoning",
        )
    return True, None


def record_tool_call(
    session_key: str,
    tool_name: str,
    *,
    reason: str | None = None,
    intent: str | None = None,
    triggering_rule: str | None = None,
    dispatch_id: int | None = None,
) -> dict[str, object]:
    """#130/#135 — structured retrieval observability log."""
    state = _get_state(session_key)
    resolved_dispatch = dispatch_id if dispatch_id is not None else current_dispatch_id(session_key)
    tools: list[str] = list(state.get("tools_called", []))  # type: ignore[arg-type]
    chain_depth = 0
    if tool_name != "agent.sync" and tools:
        chain_depth = min(len([t for t in tools if t != "agent.sync"]), 3)

    rule = triggering_rule or "manual"
    if tool_name == "agent.sync":
        rule = "sync"
    elif tool_satisfies_intent(tool_name, str(intent or _note_query_context(session_key, reason))):
        rule = "domain_trigger"
    elif chain_depth > 0:
        rule = "chaining"

    reason_for_call = reason or f"intent:{intent or classify_intent(reason)}"
    entry: dict[str, object] = {
        "tool_called": tool_name,
        "tool": tool_name,
        "chain_depth": chain_depth,
        "reason_for_call": reason_for_call,
        "reason": reason_for_call,
        "triggering_rule": rule,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_key": session_key,
    }
    if resolved_dispatch is not None:
        entry["dispatch_id"] = resolved_dispatch

    if tool_name == "agent.sync":
        state["synced"] = True
        state["sync_count"] = int(state.get("sync_count", 0)) + 1
        state["handoffs_loaded"] = True  # recent_handoffs auto-loaded in sync bundle (#124)
    if tool_name == "handoff.list":
        state["handoffs_loaded"] = True
    if tool_name.startswith(("ticket.", "github.", "memory.", "context.", "retrieve.")):
        state["domain_retrieved"] = True
    if intent:
        intents: list[str] = list(state.get("intents_seen", []))  # type: ignore[arg-type]
        if intent not in intents:
            intents.append(intent)
        state["intents_seen"] = intents

    tools.append(tool_name)
    state["tools_called"] = tools
    state["chain_depth"] = chain_depth

    with _lock:
        log = _retrieval_log.setdefault(session_key, [])
        log.append(entry)
        if len(log) > 100:
            _retrieval_log[session_key] = log[-100:]

    try:
        import observability_store

        observability_store.append_observability_log(session_key, entry)
    except Exception:
        pass

    _persist_state(session_key, state)
    return entry


def validate_retrieval_state(
    session_key: str,
    *,
    intent: str | None = None,
    dispatch_id: int | None = None,
) -> dict[str, object]:
    """#127/#128/#162/#166 — validation from observability trace before answering."""
    resolved_dispatch = dispatch_id if dispatch_id is not None else current_dispatch_id(session_key)
    cycle_tools = _observed_tools(session_key)
    dispatch_tools = (
        _tools_from_log(session_key, dispatch_id=resolved_dispatch)
        if resolved_dispatch is not None
        else []
    )
    tools = cycle_tools
    _refresh_checklist_from_tools(session_key, dispatch_id=resolved_dispatch)
    state = _get_state(session_key)
    observed = _checklist_from_observed_tools(tools)
    domain = intent or (state.get("intents_seen", ["general"])[0] if state.get("intents_seen") else "general")

    missing: list[str] = []
    for rule in MANDATORY_RETRIEVAL_RULES:
        if rule["domain"] != domain:
            continue
        required = rule.get("required_tools", [])
        prefix = bool(rule.get("prefix_match"))
        satisfied = False
        for req in required:
            req_s = str(req)
            if prefix:
                if any(t.startswith(req_s.rstrip(".")) for t in tools):
                    satisfied = True
                    break
            elif req_s in tools:
                satisfied = True
                break
        if not satisfied:
            missing.append(str(rule["rule"]))

    checklist: list[dict[str, object]] = []
    for item in PRE_RESPONSE_CHECKLIST:
        key = str(item["state_key"])
        checklist.append(
            {
                "item": item["item"],
                "passed": bool(observed.get(key)),
                "source": "observability",
            }
        )

    checklist_ready = all(
        c["passed"]
        for c in checklist
        if c["item"] != "relevant domain data retrieved" or domain != "general"
    )
    ready = not missing and checklist_ready

    if state.get("complex_query"):
        min_depth = int(PROACTIVE_CHAIN_POLICY.get("min_chain_depth", 2))
        chain_depth = int(state.get("chain_depth", 0))
        if chain_depth < min_depth:
            missing.append(
                f"Complex query requires proactive chaining (min depth {min_depth})"
            )
            ready = False
        has_feed = observed["handoffs_loaded"]
        has_repo = any(t.startswith("github.") for t in tools)
        has_memory = any(t.startswith(("context.", "retrieve.", "memory.")) for t in tools)
        if not (has_feed and (has_repo or has_memory)):
            missing.append(
                "Complex query requires handoff feed plus repo or memory retrieval"
            )
            ready = False

    with _lock:
        log_len = len(_retrieval_log.get(session_key, []))

    return {
        "ready": ready,
        "domain": domain,
        "tools_called": dispatch_tools or tools,
        "cycle_tools_called": tools,
        "chain_depth": state.get("chain_depth", 0),
        "missing_requirements": missing,
        "checklist": checklist,
        "observability": {
            "log_entries": log_len,
            "source": "retrieval_log",
            "session_key": session_key,
            "dispatch_id": resolved_dispatch,
            "dispatch_tools_called": dispatch_tools,
        },
    }


def tools_for_intent(intent: str) -> list[str]:
    """#125 — domain-aware tool mapping."""
    for entry in RETRIEVAL_POLICY:
        if entry["intent"] == intent:
            return list(entry["tools"])  # type: ignore[arg-type]
    return ["context.get", "retrieve.search"]


def build_auto_handoff_feed(*, limit: int = 8) -> dict[str, object]:
    """#124 — auto-load handoff.list after sync."""
    import crowley

    limit = max(1, min(int(limit), 50))
    rows = crowley.list_recent_agent_events(limit=limit)
    items = [crowley._memory_item_api_dict(row) for row in rows]
    handoffs = [
        item
        for item in items
        if str(item.get("memory_type", "")) in {"project_update", "summary", "lesson"}
        or "handoff" in str(item.get("display", "")).lower()
    ]
    return {
        "source": "handoff.list",
        "limit": limit,
        "items": handoffs or items,
        "total": len(handoffs or items),
        "auto_loaded": True,
    }


def behavior_payload() -> dict[str, object]:
    """Full agent behavior instructions for sync/catalog."""
    return {
        "version": "3.9.19",
        "system_query_policy": {
            "requires_agent_sync": True,
            "dedupe_sync_per_request_cycle": True,
            "keywords": list(SYSTEM_QUERY_KEYWORDS),
        },
        "auto_handoff_feed": {
            "after_agent_sync": True,
            "tool": "handoff.list",
            "limit": "5-10",
        },
        "retrieval_policy": RETRIEVAL_POLICY,
        "chaining_policy": CHAINING_POLICY,
        "mandatory_retrieval": MANDATORY_RETRIEVAL_RULES,
        "pre_response_checklist": PRE_RESPONSE_CHECKLIST,
        "pre_response_enforced": PRE_RESPONSE_ENFORCED,
        "domain_retrieval_triggers": MANDATORY_RETRIEVAL_RULES,
        "proactive_chaining": PROACTIVE_CHAIN_POLICY,
        "qa_crowley_context": QA_CROWLEY_CONTEXT_VALIDATION,
        "observability_schema": {
            "fields": ["tool_called", "reason_for_call", "chain_depth", "triggering_rule", "timestamp"],
        },
    }


def retrieval_observability(session_key: str, *, limit: int = 20) -> dict[str, object]:
    """#130 — expose retrieval log for debugging."""
    with _lock:
        memory_log = list(_retrieval_log.get(session_key, [])[-limit:])
    try:
        import observability_store

        db_log = observability_store.get_observability_logs(session_key, limit=limit)
    except Exception:
        db_log = []
    log = memory_log if memory_log else db_log
    state = _get_state(session_key)
    return {
        "session_key": session_key[:16] + "..." if len(session_key) > 16 else session_key,
        "tools_called": state.get("tools_called", []),
        "chain_depth": state.get("chain_depth", 0),
        "log": log,
        "persisted_count": len(db_log),
        "validation": validate_retrieval_state(session_key),
    }
