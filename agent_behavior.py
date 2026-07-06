"""V3.9.17+ agent behavior layer — retrieval policy, chaining, validation, observability."""

from __future__ import annotations

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
_REQUEST_CYCLE_TTL = 300


def _now() -> float:
    return time.time()


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
            }
            _session_state[session_key] = state
        return state


def reset_request_cycle(session_key: str) -> None:
    with _lock:
        _session_state.pop(session_key, None)
        _retrieval_log.pop(session_key, None)


def mark_synced(session_key: str) -> None:
    state = _get_state(session_key)
    state["synced"] = True


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
) -> dict[str, object]:
    """#130 — log retrieval/chaining decisions per session."""
    state = _get_state(session_key)
    tools: list[str] = list(state.get("tools_called", []))  # type: ignore[arg-type]
    chain_depth = 0
    if tool_name != "agent.sync" and tools:
        chain_depth = min(len([t for t in tools if t != "agent.sync"]), 3)

    entry = {
        "tool": tool_name,
        "chain_depth": chain_depth,
        "reason": reason or f"intent:{intent or classify_intent(reason)}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

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

    return entry


def validate_retrieval_state(session_key: str, *, intent: str | None = None) -> dict[str, object]:
    """#127/#128 — state-based validation before answering."""
    state = _get_state(session_key)
    tools: list[str] = list(state.get("tools_called", []))  # type: ignore[arg-type]
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
                "passed": bool(state.get(key)),
            }
        )

    return {
        "ready": not missing and all(c["passed"] for c in checklist if c["item"] != "relevant domain data retrieved" or domain != "general"),
        "domain": domain,
        "tools_called": tools,
        "chain_depth": state.get("chain_depth", 0),
        "missing_requirements": missing,
        "checklist": checklist,
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

    limit = max(5, min(int(limit), 10))
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
        "version": "3.9.17",
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
        "qa_crowley_context": QA_CROWLEY_CONTEXT_VALIDATION,
    }


def retrieval_observability(session_key: str, *, limit: int = 20) -> dict[str, object]:
    """#130 — expose retrieval log for debugging."""
    with _lock:
        log = list(_retrieval_log.get(session_key, [])[-limit:])
    state = _get_state(session_key)
    return {
        "session_key": session_key[:16] + "..." if len(session_key) > 16 else session_key,
        "tools_called": state.get("tools_called", []),
        "chain_depth": state.get("chain_depth", 0),
        "log": log,
        "validation": validate_retrieval_state(session_key),
    }
