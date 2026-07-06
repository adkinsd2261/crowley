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
        "contexts": ["sync", "qa", "write"],
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
    import agent_behavior

    if not query_text or not str(query_text).strip():
        return {"domains": [], "required_tools": [], "single_pass": True}

    text = str(query_text)
    domains: list[str] = []
    if agent_behavior.classify_intent(text) != "general":
        domains.append(agent_behavior.classify_intent(text))
    if agent_behavior.is_complex_query(text):
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

    return {
        "domains": domains,
        "required_tools": required,
        "single_pass": True,
        "complex": agent_behavior.is_complex_query(text),
    }


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


def _check_observability_truth(session_key: str) -> dict[str, object] | None:
    import agent_behavior

    obs = agent_behavior.retrieval_observability(session_key, limit=50)
    tools_state = list(obs.get("tools_called", []))
    tools_log = [str(e.get("tool_called", e.get("tool", ""))) for e in obs.get("log", [])]
    if tools_state == tools_log:
        return None
    if len(tools_log) < len(tools_state):
        return {
            "invariant": "observability_truth",
            "severity": "error",
            "tools_called": tools_state,
            "log_tools": tools_log,
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
        v = _check_observability_truth(session_key)
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


def check_state_parity(*, session_key: str | None = None, limit: int = 20) -> dict[str, object]:
    """#147 — cross-layer parity: handoffs, observability, conflicts."""
    import handoff_ticket_bridge

    handoff_report = handoff_ticket_bridge.verify_handoff_ticket_parity(limit=limit)
    invariants = run_invariant_checks("qa", session_key=session_key)
    obs_ok = True
    if session_key:
        obs_ok = _check_observability_truth(session_key) is None

    return {
        "handoff_ticket_parity": handoff_report,
        "invariants": invariants,
        "observability_matches_dispatch": obs_ok,
        "parity_ok": bool(handoff_report.get("parity_ok")) and invariants.get("ok") and obs_ok,
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

    plan = plan_retrieval_domains(query_text)
    extra["domain_plan"] = plan
    state = agent_behavior._get_state(session_key)  # noqa: SLF001
    state["domain_plan"] = plan

    if agent_behavior.is_retrieval_tool(tool_name):
        pass
    else:
        domains = list(plan.get("domains", []))
        if domains:
            missing_domains = [
                d
                for d in domains
                if agent_behavior.validate_retrieval_state(session_key, intent=str(d)).get(
                    "missing_requirements"
                )
            ]
            if missing_domains:
                required = list(plan.get("required_tools", []))
                return (
                    False,
                    "domain_retrieval_required",
                    428,
                    {
                        **extra,
                        "message": (
                            f"multi-domain plan requires retrieval before {tool_name}: "
                            f"{', '.join(missing_domains)}"
                        ),
                        "required_tools": required,
                        "missing_domains": missing_domains,
                        "triggering_rule": "domain_plan",
                    },
                )
        else:
            domain_ok, domain_msg, domain_extra = agent_behavior.check_domain_retrieval_gate(
                session_key,
                tool_name,
                query_text=query_text,
            )
            if not domain_ok and domain_msg:
                merged = {**extra, **domain_extra, "message": domain_msg}
                return False, "domain_retrieval_required", 428, merged

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

    return True, None, 200, extra


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
    )
    entry["dispatch_id"] = dispatch_id
    entry["http_status"] = http_status
    entry["bound_to_dispatch"] = True
    with agent_behavior._lock:  # noqa: SLF001
        log = agent_behavior._retrieval_log.get(session_key, [])  # noqa: SLF001
        if log:
            log[-1] = entry
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
