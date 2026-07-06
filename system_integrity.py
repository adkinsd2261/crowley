"""V3.9.18 patch — system integrity: invariants, gate orchestration, parity, guardrails."""

from __future__ import annotations

import threading
import time
from typing import Literal

CheckContext = Literal["sync", "write", "qa", "dispatch"]

MIN_AUTO_RESOLVE_CONFIDENCE = 0.75
WRITE_RATE_LIMIT_PER_MINUTE = 30
AUDIT_SAMPLE_EVERY = 10

_lock = threading.Lock()
_write_timestamps: dict[str, list[float]] = {}
_dispatch_counter = 0
_audit_counter = 0

GATE_ORDER: list[dict[str, str]] = [
    {"step": 1, "gate": "boot", "module": "workflow"},
    {"step": 2, "gate": "sync", "module": "agent_behavior"},
    {"step": 3, "gate": "domain_plan", "module": "system_integrity"},
    {"step": 4, "gate": "domain_retrieval", "module": "agent_behavior"},
    {"step": 5, "gate": "pre_response", "module": "agent_behavior"},
    {"step": 6, "gate": "automation_guardrails", "module": "system_integrity"},
]

INVARIANT_REGISTRY: list[dict[str, object]] = [
    {
        "id": "handoff_ticket_parity",
        "description": "Every recent handoff has exactly one linked ticket",
        "contexts": ["sync", "qa", "write", "dispatch"],
    },
    {
        "id": "context_before_response",
        "description": "No non-retrieval action when pre_response_validation.ready is false",
        "contexts": ["dispatch", "qa"],
    },
    {
        "id": "no_conflicting_canonical",
        "description": "No open memory conflicts involving canonical-tier items",
        "contexts": ["sync", "qa", "write"],
    },
    {
        "id": "observability_truth",
        "description": "Retrieval log matches tools_called state",
        "contexts": ["sync", "qa", "dispatch"],
    },
    {
        "id": "observability_chain_intact",
        "description": "Per-session observability hash chain is unbroken (tamper-evident)",
        "contexts": ["qa"],
    },
]


def _now() -> float:
    return time.time()


def next_dispatch_id() -> int:
    global _dispatch_counter
    with _lock:
        _dispatch_counter += 1
        return _dispatch_counter


def plan_retrieval_domains(query_text: str | None) -> dict[str, object]:
    """#145 — precompute all domains and required tools for a query."""
    return retrieval_planner(query_text)


def retrieval_planner(
    query_text: str | None,
    *,
    session_key: str | None = None,
) -> dict[str, object]:
    """#150 — sole planner source; gates must consume this output (no independent inference)."""
    import agent_behavior

    text = query_text
    if (not text or not str(text).strip()) and session_key:
        pending = agent_behavior._get_state(session_key).get("pending_query")  # noqa: SLF001
        if pending:
            text = str(pending)

    if not text or not str(text).strip():
        return {
            "domains": [],
            "required_tools": [],
            "tool_order": [],
            "single_pass": True,
            "complex": False,
            "query": None,
        }

    body = str(text)
    intent = agent_behavior.classify_intent(body)
    domains: list[str] = []
    if intent != "general":
        domains.append(intent)
    if agent_behavior.is_complex_query(body):
        for domain in ("recent_work", "code", "memory"):
            if domain not in domains:
                domains.append(domain)
        if "system" not in domains:
            domains.insert(0, "system")

    required: list[str] = []
    seen: set[str] = set()
    for domain in domains:
        for tool in agent_behavior.tools_for_intent(domain):
            if tool not in seen:
                seen.add(tool)
                required.append(tool)

    tool_order: list[str] = []
    if domains or agent_behavior.is_system_level_query(body):
        tool_order.append("agent.sync")
    for tool in required:
        if tool not in tool_order:
            tool_order.append(tool)

    return {
        "domains": domains,
        "required_tools": required,
        "tool_order": tool_order,
        "single_pass": True,
        "complex": agent_behavior.is_complex_query(body),
        "query": body,
    }


def apply_fallback_retrieval_plan(
    plan: dict[str, object],
    query_text: str | None,
) -> dict[str, object]:
    """#175 — inject minimal retrieval when planner would leave zero required tools."""
    query = str(query_text or plan.get("query") or "").strip()
    if not query:
        return plan
    required = list(plan.get("required_tools", []))
    if required:
        return plan
    import agent_behavior

    if (
        not agent_behavior.is_system_level_query(query)
        and agent_behavior.classify_intent(query) == "general"
    ):
        return plan
    fallback_tools = ["context.get", "retrieve.search"]
    domains = list(plan.get("domains", [])) or ["memory"]
    tool_order = list(plan.get("tool_order", []))
    for tool in ("agent.sync", *fallback_tools):
        if tool not in tool_order:
            tool_order.append(tool)
    return {
        **plan,
        "domains": domains,
        "required_tools": fallback_tools,
        "tool_order": tool_order,
        "fallback_retrieval": True,
    }


def _get_or_run_planner(
    session_key: str,
    query_text: str | None,
) -> tuple[dict[str, object], bool]:
    """Idempotent planner per request cycle; runs before domain gates."""
    import agent_behavior

    state = agent_behavior._get_state(session_key)  # noqa: SLF001
    if query_text and str(query_text).strip():
        agent_behavior._note_query_context(session_key, query_text)  # noqa: SLF001

    resolved = query_text or state.get("pending_query") or ""
    cache_key = str(resolved).strip()
    cached = state.get("execution_plan")
    if isinstance(cached, dict) and state.get("planner_query_key") == cache_key:
        return cached, False

    plan = retrieval_planner(query_text, session_key=session_key)
    plan = apply_fallback_retrieval_plan(plan, query_text)
    state["execution_plan"] = plan
    state["domain_plan"] = plan
    state["planner_query_key"] = cache_key
    state["planner_called_before_gates"] = True
    agent_behavior._persist_state(session_key, state)  # noqa: SLF001
    return plan, True


def _planner_missing_domains(session_key: str, plan: dict[str, object]) -> list[str]:
    """Domains from planner output still missing required reads."""
    import agent_behavior

    domains = list(plan.get("domains", []))
    if not domains:
        return []
    missing: list[str] = []
    for domain in domains:
        if not agent_behavior._domain_retrieval_satisfied(session_key, str(domain)):  # noqa: SLF001
            missing.append(str(domain))
    return missing


def _check_handoff_ticket_parity() -> dict[str, object] | None:
    import handoff_ticket_bridge

    report = handoff_ticket_bridge.verify_handoff_ticket_parity(limit=20)
    if report.get("parity_ok"):
        return None
    return {
        "invariant": "handoff_ticket_parity",
        "severity": "error",
        "missing": report.get("missing_tickets", []),
        "duplicates": report.get("duplicate_links", []),
    }


def _check_no_conflicting_canonical() -> dict[str, object] | None:
    import conflict_engine
    import memory_tiers

    open_conflicts = conflict_engine.list_memory_conflicts(status="open", limit=50)
    if not open_conflicts:
        return None

    import crowley

    canonical_conflicts: list[int] = []
    conn = crowley.connect_db()
    try:
        for conflict in open_conflicts:
            for key in ("left_memory_id", "right_memory_id"):
                mem_id = conflict.get(key)
                if mem_id is None:
                    continue
                row = conn.execute(
                    "SELECT metadata_json FROM memory_items WHERE id = ?",
                    (int(mem_id),),
                ).fetchone()
                if row is None:
                    continue
                tier = memory_tiers.tier_from_metadata_json(
                    str(row["metadata_json"]) if row["metadata_json"] else None
                )
                if tier == "canonical":
                    canonical_conflicts.append(int(conflict["id"]))
                    break
    finally:
        conn.close()

    if not canonical_conflicts:
        return None
    return {
        "invariant": "no_conflicting_canonical",
        "severity": "error",
        "open_canonical_conflicts": canonical_conflicts,
    }


def _check_observability_truth(
    session_key: str,
    *,
    check_db: bool = False,
) -> dict[str, object] | None:
    import agent_behavior

    dispatch_id = agent_behavior.current_dispatch_id(session_key) if check_db else None

    with agent_behavior._lock:  # noqa: SLF001
        memory_log = [
            entry
            for entry in agent_behavior._retrieval_log.get(session_key, [])  # noqa: SLF001
            if isinstance(entry, dict)
        ]
    if dispatch_id is not None:
        memory_log = [
            entry for entry in memory_log if entry.get("dispatch_id") == dispatch_id
        ]
        memory_tools = agent_behavior._tools_from_log(session_key, dispatch_id=dispatch_id)
        tools_state = memory_tools
    else:
        memory_tools = [
            str(entry.get("tool_called", entry.get("tool", ""))) for entry in memory_log
        ]
        state = agent_behavior._get_state(session_key)  # noqa: SLF001
        tools_state = list(state.get("tools_called", []))  # type: ignore[arg-type]

    # Persisted observability log — survives bus restarts and is the authoritative
    # record when the in-memory log is cold. The in-memory _retrieval_log is
    # process-local and wiped on restart, while session_state.tools_called persists,
    # so comparing state directly against in-memory alone yields false positives for
    # long-lived sessions (e.g. the ChatGPT bearer-token session) after a restart.
    db_log: list[dict[str, object]] = []
    try:
        import observability_store

        db_log = [
            entry
            for entry in observability_store.get_observability_logs(session_key, limit=200)
            if isinstance(entry, dict)
        ]
    except Exception:
        db_log = []
    if dispatch_id is not None:
        db_log = [entry for entry in db_log if entry.get("dispatch_id") == dispatch_id]
    db_tools = [str(entry.get("tool_called", entry.get("tool", ""))) for entry in db_log]

    # State claims tools that appear in NO observability sink (memory or DB) —
    # this is genuine silent execution and always blocks.
    observed_count = max(len(memory_tools), len(db_tools))
    if observed_count < len(tools_state):
        return {
            "invariant": "observability_truth",
            "severity": "error",
            "mismatch": "state_not_observed",
            "tools_called": tools_state,
            "memory_tools": memory_tools,
            "db_tools": db_tools,
        }

    # Strict live divergence: in-memory log present but disagrees with the DB.
    # Restricted to qa/sync so dispatch is not blocked by write-behind persistence lag.
    if check_db and memory_tools:
        if len(db_tools) < len(memory_tools) or db_tools[-len(memory_tools) :] != memory_tools:
            return {
                "invariant": "observability_truth",
                "severity": "error",
                "mismatch": "memory_vs_db",
                "memory_tools": memory_tools,
                "db_tools": db_tools,
                "dispatch_id": dispatch_id,
            }

    return None


def _check_context_before_response(session_key: str) -> dict[str, object] | None:
    import agent_behavior

    state = agent_behavior._get_state(session_key)  # noqa: SLF001 — integrity layer
    if not state.get("pending_query"):
        return None
    validation = agent_behavior.validate_retrieval_state(session_key)
    if validation.get("ready"):
        return None
    tools = list(state.get("tools_called", []))
    if not tools or all(agent_behavior.is_retrieval_tool(t) for t in tools):
        return None
    return {
        "invariant": "context_before_response",
        "severity": "warning",
        "validation": validation,
    }


def run_invariant_checks(
    context: CheckContext,
    *,
    session_key: str | None = None,
) -> dict[str, object]:
    """#143 — run applicable invariants; violations emit failure signal."""
    try:
        violations: list[dict[str, object]] = []
        applicable = {inv["id"] for inv in INVARIANT_REGISTRY if context in inv.get("contexts", [])}

        if "handoff_ticket_parity" in applicable:
            v = _check_handoff_ticket_parity()
            if v:
                violations.append(v)

        if "no_conflicting_canonical" in applicable:
            v = _check_no_conflicting_canonical()
            if v:
                violations.append(v)

        if "observability_truth" in applicable and session_key:
            v = _check_observability_truth(
                session_key,
                check_db=context in ("sync", "qa"),
            )
            if v:
                violations.append(v)

        if "observability_chain_intact" in applicable and session_key:
            v = _check_observability_chain(session_key)
            if v:
                violations.append(v)

        if "context_before_response" in applicable and session_key:
            v = _check_context_before_response(session_key)
            if v:
                violations.append(v)

        return {
            "context": context,
            "ok": not violations,
            "violations": violations,
            "registry": INVARIANT_REGISTRY,
        }
    except Exception as exc:
        return {
            "context": context,
            "ok": False,
            "violations": [
                {
                    "invariant": "invariant_system",
                    "severity": "error",
                    "detail": str(exc)[:500],
                }
            ],
            "registry": INVARIANT_REGISTRY,
            "system_error": True,
        }


def _check_observability_chain(session_key: str) -> dict[str, object] | None:
    """#201 — flag a broken observability hash chain (tamper-evidence).

    Warning severity: this is detection, not a dispatch blocker. Historical
    tamper does not affect current-execution correctness, so it must not gate
    live dispatch (which would reintroduce the cold-state false-positive class).
    """
    try:
        import observability_store

        report = observability_store.verify_observability_chain(session_key)
    except Exception:
        return None
    if report.get("ok"):
        return None
    return {
        "invariant": "observability_chain_intact",
        "severity": "warning",
        "break_at_id": report.get("break_at_id"),
        "reason": report.get("reason"),
        "checked": report.get("checked"),
    }


def check_state_parity(*, session_key: str | None = None, limit: int = 20) -> dict[str, object]:
    """#147 — cross-layer parity: handoffs, observability, conflicts."""
    import handoff_ticket_bridge

    handoff_report = handoff_ticket_bridge.verify_handoff_ticket_parity(limit=limit)
    invariants = run_invariant_checks("qa", session_key=session_key)
    obs_ok = True
    chain_report: dict[str, object] | None = None
    if session_key:
        obs_ok = _check_observability_truth(session_key, check_db=True) is None
        import observability_store

        chain_report = observability_store.verify_observability_chain(session_key)

    chain_ok = chain_report.get("ok", True) if chain_report else True
    return {
        "handoff_ticket_parity": handoff_report,
        "invariants": invariants,
        "observability_matches_dispatch": obs_ok,
        "observability_chain": chain_report,
        "parity_ok": (
            bool(handoff_report.get("parity_ok"))
            and invariants.get("ok")
            and obs_ok
            and bool(chain_ok)
        ),
    }


def can_auto_resolve_conflict(
    left_confidence: float,
    right_confidence: float,
    *,
    left_tier: str,
    right_tier: str,
) -> tuple[bool, str]:
    """#146 — block low-confidence or dual-canonical auto-resolution."""
    if left_tier == "canonical" and right_tier == "canonical":
        return False, "escalate: dual canonical conflict requires manual resolution"
    low = min(float(left_confidence), float(right_confidence))
    if low < MIN_AUTO_RESOLVE_CONFIDENCE:
        return False, f"escalate: confidence {low:.2f} below threshold {MIN_AUTO_RESOLVE_CONFIDENCE}"
    return True, "auto_resolve_allowed"


def check_automation_guardrails(agent_id: str, action: str) -> tuple[bool, str | None, dict[str, object]]:
    """#149 — rate limit writes and audit sampling."""
    global _audit_counter
    agent = agent_id.strip().lower() or "system"
    now = _now()
    extra: dict[str, object] = {"action": action, "agent_id": agent}

    with _lock:
        _audit_counter += 1
        extra["audit_sample"] = _audit_counter % AUDIT_SAMPLE_EVERY == 0
        stamps = _write_timestamps.setdefault(agent, [])
        stamps[:] = [t for t in stamps if now - t < 60]
        if action.startswith(("write", "ticket.", "handoff.", "memory.", "audit.")):
            if len(stamps) >= WRITE_RATE_LIMIT_PER_MINUTE:
                return (
                    False,
                    f"automation_guardrail: write rate limit exceeded ({WRITE_RATE_LIMIT_PER_MINUTE}/min)",
                    extra,
                )
            stamps.append(now)

    if extra.get("audit_sample"):
        extra["rollback_trigger"] = "audit_sample_due"
    return True, None, extra


def run_enforcement_gates(
    session_key: str,
    tool_name: str,
    *,
    query_text: str | None = None,
    kind: str = "read",
    agent_id: str | None = None,
    boot_allowed: bool = True,
    boot_message: str | None = None,
) -> tuple[bool, str | None, int, dict[str, object]]:
    """
    #144 — unified gate orchestration in fixed order.
    Returns (ok, error_code, http_status, extra_payload).
    """
    import agent_behavior

    extra: dict[str, object] = {"gate_order": [g["gate"] for g in GATE_ORDER]}

    if not boot_allowed and boot_message:
        return False, "boot_required", 428, {"message": boot_message, **extra}

    sync_ok, sync_msg = agent_behavior.check_sync_for_system_query(
        session_key,
        query_text=query_text,
        tool_name=tool_name,
    )
    if not sync_ok and sync_msg:
        return False, "sync_required", 428, {"message": sync_msg, **extra}

    plan, planner_cached = _get_or_run_planner(session_key, query_text)
    extra.update(
        {
            "domain_plan": plan,
            "planner_output": plan,
            "planner_called_before_gates": True,
            "gates_use_planner_output": True,
            "planner_cached": not planner_cached,
            "execution_plan": plan,
        }
    )
    state = agent_behavior._get_state(session_key)  # noqa: SLF001

    tools_called: list[str] = list(state.get("tools_called", []))  # type: ignore[arg-type]
    if agent_behavior.is_retrieval_tool(tool_name):
        pass
    elif tool_name in tools_called:
        pass
    else:
        missing_domains = _planner_missing_domains(session_key, plan)
        if missing_domains:
            attempts = int(state.get("planner_attempts", 0))
            if attempts < 1:
                state["planner_attempts"] = attempts + 1
                state.pop("execution_plan", None)
                state.pop("planner_query_key", None)
                plan, planner_cached = _get_or_run_planner(session_key, query_text)
                extra.update(
                    {
                        "domain_plan": plan,
                        "planner_output": plan,
                        "planner_cached": not planner_cached,
                        "execution_plan": plan,
                        "planner_refinement_attempt": attempts + 1,
                    }
                )
                missing_domains = _planner_missing_domains(session_key, plan)
        if missing_domains:
            required = list(plan.get("required_tools", []))
            tool_order = list(plan.get("tool_order", []))
            return (
                False,
                "domain_retrieval_required",
                428,
                {
                    **extra,
                    "message": (
                        f"execution plan requires retrieval before {tool_name}: "
                        f"{', '.join(missing_domains)}"
                    ),
                    "required_tools": required,
                    "tool_order": tool_order,
                    "missing_domains": missing_domains,
                    "triggering_rule": "execution_plan",
                },
            )

    gate_ok, gate_msg, gate_extra = agent_behavior.check_pre_response_gate(
        session_key,
        tool_name,
        query_text=query_text,
        kind=kind,
    )
    if not gate_ok and gate_msg:
        merged = {**extra, **gate_extra, "message": gate_msg}
        return False, "context_not_ready", 428, merged

    if kind == "write" and agent_id:
        guard_ok, guard_msg, guard_extra = check_automation_guardrails(agent_id, tool_name)
        extra["automation_guardrails"] = guard_extra
        if not guard_ok and guard_msg:
            return False, "automation_guardrail", 429, {"message": guard_msg, **extra}

    invariant_result = run_invariant_checks("dispatch", session_key=session_key)
    extra["invariant_checks"] = invariant_result
    blocking = _blocking_violations(invariant_result)
    if blocking:
        _record_dispatch_blocked(tool_name, session_key, blocking)
        return (
            False,
            "invariant_violation",
            428,
            {
                **extra,
                "message": "dispatch blocked by invariant violation",
                "violations": blocking,
            },
        )

    return True, None, 200, extra


def _blocking_violations(invariant_result: dict[str, object]) -> list[dict[str, object]]:
    """Error-severity violations that must halt execution."""
    return [
        violation
        for violation in invariant_result.get("violations", [])  # type: ignore[union-attr]
        if isinstance(violation, dict) and violation.get("severity") == "error"
    ]


def _record_dispatch_blocked(
    tool_name: str,
    session_key: str,
    blocking: list[dict[str, object]],
) -> None:
    """Emit a dispatch_blocked metric with violation details (#190)."""
    try:
        import crowley

        crowley.record_system_metric(
            "dispatch_blocked",
            label="invariant_violation",
            payload={
                "tool": tool_name,
                "session_key": (session_key or "direct")[:32],
                "violations": [
                    str(v.get("invariant"))
                    for v in blocking
                    if isinstance(v, dict) and v.get("invariant")
                ],
            },
        )
    except Exception:
        pass


def enforce_dispatch_invariants(
    tool_name: str,
    *,
    session_key: str | None = None,
) -> tuple[bool, dict[str, object]]:
    """
    #196 — standalone dispatch invariant gate for non-gateway write entrypoints.

    The Actions gateway enforces invariants inside run_enforcement_gates, but direct
    localhost mutation endpoints (e.g. POST /api/ingest) bypass that path. This closes
    the coverage gap so no write path proceeds under an error-severity violation.

    Returns (ok, payload). When blocked, payload carries the structured error.
    """
    invariant_result = run_invariant_checks("dispatch", session_key=session_key)
    blocking = _blocking_violations(invariant_result)
    if not blocking:
        return True, {"invariant_checks": invariant_result}
    _record_dispatch_blocked(tool_name, session_key or "direct", blocking)
    return False, {
        "status": "error",
        "error": "invariant_violation",
        "message": "execution blocked by invariant violation",
        "violations": blocking,
        "invariant_checks": invariant_result,
    }


def record_dispatch_observability(
    session_key: str,
    tool_name: str,
    *,
    dispatch_id: int,
    query_text: str | None = None,
    intent: str | None = None,
    triggering_rule: str | None = None,
    http_status: int = 200,
) -> dict[str, object]:
    """#148 — bind observability log entry to dispatch event."""
    import agent_behavior

    entry = agent_behavior.record_tool_call(
        session_key,
        tool_name,
        reason=query_text,
        intent=intent,
        triggering_rule=triggering_rule or "dispatch",
        dispatch_id=dispatch_id,
    )
    entry["http_status"] = http_status
    entry["bound_to_dispatch"] = True
    with agent_behavior._lock:  # noqa: SLF001
        log = agent_behavior._retrieval_log.get(session_key, [])  # noqa: SLF001
        if log:
            log[-1] = entry
    try:
        import observability_store

        observability_store.update_observability_log_dispatch(
            session_key,
            int(dispatch_id),
            entry,
        )
    except Exception:
        pass
    return entry


def integrity_payload() -> dict[str, object]:
    """Expose integrity config in sync/catalog."""
    return {
        "version": "3.9.18-integrity",
        "gate_order": GATE_ORDER,
        "invariants": INVARIANT_REGISTRY,
        "min_auto_resolve_confidence": MIN_AUTO_RESOLVE_CONFIDENCE,
        "write_rate_limit_per_minute": WRITE_RATE_LIMIT_PER_MINUTE,
        "audit_sample_every": AUDIT_SAMPLE_EVERY,
    }
