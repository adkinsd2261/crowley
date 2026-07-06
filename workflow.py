"""V3.9.16 — Workflow enforcement: boot, truth hierarchy, core tools, QA pipeline."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Literal

ToolTier = Literal["core", "secondary"]
BootStatus = Literal["pending", "synced"]

TRUTH_HIERARCHY: list[dict[str, object]] = [
    {"rank": 1, "layer": "filesystem", "source": "VERSIONS.md, WHERE_WE_ARE, PROJECT_STATE"},
    {"rank": 2, "layer": "tickets", "source": "/api/tickets, sync tickets block"},
    {
        "rank": 3,
        "layer": "agent_activity",
        "source": "last_by_source handoff timestamps",
        "precedence": "Overrides stale project_state and memory for what changed / what now",
    },
    {"rank": 4, "layer": "project_state", "source": "SQLite project_state"},
    {"rank": 5, "layer": "canon", "source": "pinned Canon: memory_items"},
    {"rank": 6, "layer": "retrieval", "source": "/api/retrieve hybrid search"},
    {"rank": 7, "layer": "chat", "source": "current thread window"},
]

CANONICAL_WORKFLOW_LOOP: list[dict[str, object]] = [
    {"step": 1, "phase": "sync", "action": "agent.sync or agent sync script --before"},
    {"step": 2, "phase": "read", "action": "Pull tickets, task frame, agent activity, constraints"},
    {"step": 3, "phase": "decide", "action": "Reconcile ticket intent with latest activity; surface gaps"},
    {"step": 4, "phase": "write", "action": "Implement / mint / handoff via allowed tools"},
    {
        "step": 5,
        "phase": "state_update",
        "action": "builder_handoff with Build Complete + Context Basis sections",
    },
]

CORE_TOOL_NAMES: frozenset[str] = frozenset({
    "agent.sync",
    "context.get",
    "retrieve.search",
    "memory.get",
    "memory.list",
    "ticket.get",
    "ticket.list",
    "ticket.create",
    "ticket.update",
    "ticket.cancel",
    "handoff.ingest",
    "note.ingest",
})

BOOT_EXEMPT_TOOLS: frozenset[str] = frozenset({
    "agent.sync",
    "context.get",
    "portable.packet",
})

SECONDARY_TOOL_PREFIXES: tuple[str, ...] = (
    "inspect.",
    "planning.",
    "qa.",
    "github.",
    "session.",
    "spark.",
    "decision.",
    "handoff.get",
    "handoff.list",
    "writeback.",
    "portable.",
    "memory.lineage",
    "memory.why_retrieved",
)

QA_PIPELINE_SCHEMA: dict[str, object] = {
    "stages": ["cursor_build", "codex_qa", "approval"],
    "builder_handoff_sections": [
        "Summary",
        "Context Basis",
        "Build Complete",
        "QA Results",
        "Approval",
        "Next Action",
    ],
    "build_complete_fields": [
        "files_changed",
        "self_check",
        "confidence",
        "approval_rationale",
    ],
    "codex_qa_fields": ["qa_result", "issues", "suggested_fixes", "confidence"],
    "rules": [
        "No commit/merge before Codex qa_result pass and approval",
        "Codex must not pass with known blocking issues",
        "Revision loops back to Cursor with suggested_fixes",
    ],
}

REDUNDANCY_AUDIT: list[dict[str, object]] = [
    {
        "tools": ["agent.sync", "context.get", "portable.packet"],
        "overlap": "session orientation",
        "guidance": "Fresh chat: agent.sync first; context.get for targeted query; portable.packet for full markdown export",
    },
    {
        "tools": ["planning.ticket", "ticket.get", "planning.task_frame"],
        "overlap": "ticket context",
        "guidance": "ticket.get for detail; planning.ticket adds task-frame; planning.task_frame for in-progress brief",
    },
    {
        "tools": ["handoff.ingest", "note.ingest", "writeback.ingest"],
        "overlap": "memory writes",
        "guidance": "handoff.ingest for architect slices; note.ingest for short planning notes; writeback.ingest for terminal session receipts",
    },
    {
        "tools": ["session.list", "handoff.list", "inspect.recent_ingests"],
        "overlap": "recent activity history",
        "guidance": "handoff.list for agent events; session.list for portable receipts; inspect.recent_ingests for writeback audit",
    },
]

SESSION_TTL_SECONDS = 4 * 3600
_session_boot: dict[str, float] = {}
_session_lock = threading.Lock()


def normalize_session_key(raw: str | None, *, bearer_token: str | None = None) -> str:
    text = (raw or "").strip()
    if text:
        return text[:128]
    if bearer_token:
        digest = hashlib.sha256(bearer_token.encode("utf-8")).hexdigest()[:16]
        return f"token:{digest}"
    return "default"


def record_boot_sync(session_key: str) -> None:
    with _session_lock:
        _session_boot[session_key] = time.time()


def boot_status(session_key: str) -> BootStatus:
    with _session_lock:
        synced_at = _session_boot.get(session_key)
    if synced_at is None:
        return "pending"
    if time.time() - synced_at > SESSION_TTL_SECONDS:
        return "pending"
    return "synced"


def check_boot_gate(session_key: str, tool_name: str) -> tuple[bool, str | None]:
    name = tool_name.strip()
    if name in BOOT_EXEMPT_TOOLS:
        if name == "agent.sync":
            record_boot_sync(session_key)
        return True, None
    if boot_status(session_key) == "synced":
        return True, None
    return (
        False,
        "boot_required: call agent.sync before other tools in a fresh Actions session",
    )


def tool_tier(tool_name: str) -> ToolTier:
    name = tool_name.strip()
    if name in CORE_TOOL_NAMES:
        return "core"
    for prefix in SECONDARY_TOOL_PREFIXES:
        if name.startswith(prefix) or name == prefix.rstrip("."):
            return "secondary"
    return "secondary"


def core_tool_names(all_tools: list[str]) -> list[str]:
    return sorted(name for name in all_tools if tool_tier(name) == "core")


def secondary_tool_names(all_tools: list[str]) -> list[str]:
    return sorted(name for name in all_tools if tool_tier(name) == "secondary")


def workflow_enforcement_payload(*, tool_names: list[str] | None = None) -> dict[str, object]:
    names = tool_names or []
    return {
        "version": "3.9.16",
        "truth_hierarchy": TRUTH_HIERARCHY,
        "canonical_loop": CANONICAL_WORKFLOW_LOOP,
        "boot_sequence": {
            "required_first_tool": "agent.sync",
            "exempt_tools": sorted(BOOT_EXEMPT_TOOLS),
            "enforcement": "runtime gate on POST /api/actions/read and /write",
            "session_header": "X-Crowley-Session (optional; falls back to bearer hash)",
        },
        "core_tools": core_tool_names(names) if names else sorted(CORE_TOOL_NAMES),
        "secondary_tools": secondary_tool_names(names) if names else [],
        "redundancy_audit": REDUNDANCY_AUDIT,
        "qa_pipeline": QA_PIPELINE_SCHEMA,
    }


def truth_precedence_prompt_block() -> str:
    return (
        "Truth precedence (V3.9.16): for what changed and what now, "
        "agent activity timestamps beat project_state and beat supporting memory. "
        "Filesystem and tickets still win for version and assigned work facts."
    )


def is_low_signal_note(content: str) -> bool:
    """Reject chatty low-value notes before ingest (#107)."""
    trimmed = " ".join(content.split())
    if len(trimmed) < 24:
        return True
    lower = trimmed.lower()
    noise_markers = (
        "test note",
        "hello",
        "checking",
        "just testing",
        "ping",
        "ok",
        "thanks",
    )
    if any(lower == marker or lower.startswith(f"{marker} ") for marker in noise_markers):
        return True
    if trimmed.endswith("?") and len(trimmed) < 40:
        return True
    return False
