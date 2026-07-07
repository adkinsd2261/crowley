"""V3.9.17 #112 — Agent identity and write attribution."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

AgentPermissionRole = Literal["read_only", "writer", "architect"]

ATTRIBUTION_VERSION = "1"
ATTRIBUTION_KEY = "write_attribution"

PERMISSION_ROLES: tuple[AgentPermissionRole, ...] = (
    "read_only",
    "writer",
    "architect",
)

ROLE_RANK: dict[AgentPermissionRole, int] = {
    "read_only": 0,
    "writer": 1,
    "architect": 2,
}

AGENT_PERMISSION_ROLES: dict[str, AgentPermissionRole] = {
    "cursor": "writer",
    "codex": "architect",
    "chatgpt": "architect",
    "crowley": "writer",
    "mr_go": "architect",
    "manual": "writer",
    "system": "architect",
    "extract": "writer",
    "extract_guard": "read_only",
    "implicit": "read_only",
    "user": "writer",
    "portable_terminal": "writer",
    "ingest": "writer",
}

TOOL_MIN_ROLE: dict[str, AgentPermissionRole] = {
    "ticket.create": "architect",
    "ticket.cancel": "architect",
    "ticket.update": "writer",
    "handoff.ingest": "writer",
    "note.ingest": "writer",
    "writeback.ingest": "writer",
    "cognitive.ingest": "writer",
    "writeback.parse": "read_only",
    "memory.pin": "architect",
    "memory.promote_canonical": "architect",
    "audit.rollback": "architect",
}

DOMAIN_ACTION_MIN_ROLE: dict[str, AgentPermissionRole] = {
    "ticket.create": "architect",
    "ticket.cancel": "architect",
    "ticket.update": "writer",
    "ticket.claim": "writer",
    "ticket.done": "writer",
    "memory.pin": "architect",
    "handoff.ingest": "writer",
    "audit.rollback": "architect",
}

KNOWN_AGENT_IDS = frozenset({
    "cursor",
    "codex",
    "chatgpt",
    "crowley",
    "mr_go",
    "manual",
    "system",
    "extract",
    "extract_guard",
    "implicit",
    "portable_terminal",
    "ingest",
    "user",
})

SOURCE_TO_AGENT: dict[str, str] = {
    "cursor": "cursor",
    "codex": "codex",
    "chatgpt": "chatgpt",
    "crowley": "crowley",
    "manual": "manual",
    "system": "system",
    "extract": "extract",
    "extract_guard": "extract_guard",
    "implicit": "implicit",
    "portable_terminal": "chatgpt",
    "ingest": "crowley",
    "session_summary": "crowley",
}


def normalize_agent_id(
    agent_id: str | None,
    *,
    fallback_source: str | None = None,
) -> str:
    if agent_id and str(agent_id).strip():
        normalized = str(agent_id).strip().lower()
        if normalized in KNOWN_AGENT_IDS:
            return normalized
        return normalized
    if fallback_source and str(fallback_source).strip():
        src = str(fallback_source).strip().lower()
        return SOURCE_TO_AGENT.get(src, src)
    return "system"


def sign_attribution(
    agent_id: str,
    source: str,
    timestamp: str,
    *,
    content_hint: str = "",
) -> str:
    payload = (
        f"{ATTRIBUTION_VERSION}|{agent_id}|{source}|{timestamp}|"
        f"{content_hint[:120]}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def build_write_attribution(
    agent_id: str,
    source: str,
    *,
    timestamp: str,
    action: str | None = None,
    content_hint: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, object]:
    agent = normalize_agent_id(agent_id, fallback_source=source)
    src = (source or agent).strip().lower()
    attr: dict[str, object] = {
        "attribution_version": ATTRIBUTION_VERSION,
        "agent_id": agent,
        "source": src,
        "timestamp": timestamp,
        "signature": sign_attribution(agent, src, timestamp, content_hint=content_hint),
    }
    if action:
        attr["action"] = action
    if extra:
        attr["extra"] = extra
    return attr


def merge_attribution_into_metadata(
    metadata: dict[str, object] | None,
    attribution: dict[str, object],
) -> dict[str, object]:
    merged = dict(metadata or {})
    merged[ATTRIBUTION_KEY] = attribution
    return merged


def permission_role_for_agent(agent_id: str | None) -> AgentPermissionRole:
    agent = normalize_agent_id(agent_id)
    return AGENT_PERMISSION_ROLES.get(agent, "writer")


def role_meets_minimum(
    agent_role: AgentPermissionRole,
    required_role: AgentPermissionRole,
) -> bool:
    return ROLE_RANK[agent_role] >= ROLE_RANK[required_role]


def check_write_permission(
    agent_id: str | None,
    tool_name: str,
) -> tuple[bool, str | None]:
    agent_role = permission_role_for_agent(agent_id)
    required = TOOL_MIN_ROLE.get(tool_name.strip())
    if required is None:
        if agent_role == "read_only":
            return False, f"permission_denied: {agent_role} cannot invoke write tool {tool_name}"
        return True, None
    if role_meets_minimum(agent_role, required):
        return True, None
    return (
        False,
        f"permission_denied: {agent_role} cannot invoke {tool_name} (requires {required})",
    )


def check_domain_permission(
    agent_id: str | None,
    action: str,
) -> tuple[bool, str | None]:
    agent_role = permission_role_for_agent(agent_id)
    required = DOMAIN_ACTION_MIN_ROLE.get(action.strip())
    if required is None:
        if agent_role == "read_only":
            return False, f"permission_denied: {agent_role} cannot perform {action}"
        return True, None
    if role_meets_minimum(agent_role, required):
        return True, None
    return (
        False,
        f"permission_denied: {agent_role} cannot perform {action} (requires {required})",
    )


def permissions_for_agent(agent_id: str | None) -> dict[str, object]:
    role = permission_role_for_agent(agent_id)
    agent = normalize_agent_id(agent_id)
    allowed_writes = sorted(
        tool for tool, min_role in TOOL_MIN_ROLE.items() if role_meets_minimum(role, min_role)
    )
    return {
        "agent_id": agent,
        "role": role,
        "roles": list(PERMISSION_ROLES),
        "role_map": dict(AGENT_PERMISSION_ROLES),
        "allowed_write_tools": allowed_writes,
        "restricted_actions": sorted(
            action
            for action, min_role in DOMAIN_ACTION_MIN_ROLE.items()
            if not role_meets_minimum(role, min_role)
        ),
    }


def parse_attribution_from_metadata_json(metadata_json: str | None) -> dict[str, object] | None:
    if not metadata_json or not str(metadata_json).strip():
        return None
    try:
        meta = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(meta, dict):
        return None
    attr = meta.get(ATTRIBUTION_KEY)
    return attr if isinstance(attr, dict) else None


def parse_attribution_from_payload(payload: dict[str, object] | str | None) -> dict[str, object] | None:
    if payload is None:
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    attr = payload.get(ATTRIBUTION_KEY)
    return attr if isinstance(attr, dict) else None


def attribution_for_memory_row(metadata_json: str | None) -> dict[str, object] | None:
    attr = parse_attribution_from_metadata_json(metadata_json)
    if attr is not None:
        return attr
    return None


def attribution_for_ticket_event(payload: dict[str, object] | str | None) -> dict[str, object] | None:
    return parse_attribution_from_payload(payload)


def enrich_event_payload(
    payload: dict[str, object] | None,
    *,
    agent_id: str,
    source: str,
    timestamp: str,
    action: str,
    content_hint: str = "",
) -> dict[str, object]:
    merged = dict(payload or {})
    merged[ATTRIBUTION_KEY] = build_write_attribution(
        agent_id,
        source,
        timestamp=timestamp,
        action=action,
        content_hint=content_hint,
    )
    return merged
