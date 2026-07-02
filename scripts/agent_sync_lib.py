#!/usr/bin/env python3
"""Shared helpers for codex_sync.py and cursor_sync.py."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SESSION_MARKER = ROOT / ".crowley" / ".cursor-session-pending-handoff"
BUS_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT = 8


def url(path: str, params: dict[str, object] | None = None) -> str:
    base = f"{BUS_URL}{path}"
    if not params:
        return base
    return f"{base}?{urllib.parse.urlencode(params)}"


def fetch_json(
    target: str, *, timeout: int = DEFAULT_TIMEOUT
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return None, str(exc.reason)
    except TimeoutError:
        return None, "request timed out"
    except OSError as exc:
        return None, str(exc)

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None, "invalid JSON response"
    if not isinstance(data, dict):
        return None, "unexpected JSON response"
    return data, None


def send_json(
    path: str,
    payload: dict[str, Any],
    *,
    method: str = "POST",
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any] | None, str | None]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url(path),
        data=body,
        method=method.upper(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, f"HTTP {exc.code}: {detail or exc.reason}"
    except urllib.error.URLError as exc:
        return None, str(exc.reason)
    except (TimeoutError, OSError) as exc:
        return None, str(exc)

    if not raw.strip():
        return {}, None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid JSON response"
    if not isinstance(data, dict):
        return None, "unexpected JSON response"
    return data, None


def create_ticket_api(
    *,
    title: str,
    description: str = "",
    assignee: str = "unassigned",
    priority: int = 2,
    parent_id: int | None = None,
    source: str = "manual",
    actor: str = "system",
) -> tuple[int | None, str | None]:
    payload: dict[str, Any] = {
        "title": title,
        "description": description,
        "assignee": assignee,
        "priority": priority,
        "source": source,
        "actor": actor,
    }
    if parent_id is not None:
        payload["parent_id"] = parent_id
    result, error = send_json(
        "/api/tickets",
        payload,
    )
    if error or result is None:
        return None, error or "ticket create failed"
    ticket = result.get("ticket")
    if not isinstance(ticket, dict):
        return None, "ticket create returned no ticket"
    ticket_id = ticket.get("id")
    if ticket_id is None:
        return None, "ticket create returned no id"
    return int(ticket_id), None


def update_ticket_api(
    ticket_id: int,
    *,
    actor: str,
    status: str | None = None,
    assignee: str | None = None,
    comment: str | None = None,
    linked_memory_id: int | None = None,
) -> tuple[bool, str | None]:
    payload: dict[str, Any] = {"actor": actor}
    if status is not None:
        payload["status"] = status
    if assignee is not None:
        payload["assignee"] = assignee
    if comment is not None:
        payload["comment"] = comment
    if linked_memory_id is not None:
        payload["linked_memory_id"] = linked_memory_id
    result, error = send_json(
        f"/api/tickets/{ticket_id}",
        payload,
        method="PATCH",
    )
    if error or result is None:
        return False, error or "ticket update failed"
    return True, None


def complete_ticket_api(
    ticket_id: int,
    *,
    actor: str,
    linked_memory_id: int | None = None,
) -> tuple[bool, str | None]:
    if linked_memory_id is not None:
        return update_ticket_api(
            ticket_id,
            actor=actor,
            status="done",
            linked_memory_id=linked_memory_id,
        )
    result, error = send_json(
        f"/api/tickets/{ticket_id}/done?actor={urllib.parse.quote(actor)}",
        {},
        method="POST",
    )
    if error or result is None:
        return False, error or "ticket complete failed"
    return True, None


def cancel_ticket_api(
    ticket_id: int,
    *,
    actor: str,
    comment: str,
) -> tuple[bool, str | None]:
    result, error = send_json(
        f"/api/tickets/{ticket_id}/cancel",
        {"actor": actor, "comment": comment},
    )
    if error or result is None:
        return False, error or "ticket cancel failed"
    return True, None


def last_handoff_memory_id(agent: str) -> int | None:
    sync, _ = fetch_json(url("/api/agent/sync", {"agent": agent, "limit": 5}))
    if not sync:
        return None
    activity = sync.get("agent_activity")
    if not isinstance(activity, dict):
        return None
    entry = (activity.get("last_by_source") or {}).get(agent)
    if not isinstance(entry, dict):
        return None
    mem_id = entry.get("memory_id")
    return int(mem_id) if mem_id is not None else None


def print_tickets_summary(sync: dict[str, Any], *, agent: str) -> None:
    tickets = sync.get("tickets")
    if not isinstance(tickets, dict):
        return
    assigned = as_list(tickets.get("assigned_to_agent"))
    print("tickets assigned to you:")
    if not assigned:
        print("  - (none)")
    else:
        for item in assigned[:10]:
            if isinstance(item, dict):
                parent = item.get("parent_id")
                parent_note = f" child of #{parent}" if parent is not None else ""
                print(
                    f"  - #{item.get('id')} [{item.get('status')}] P{item.get('priority')} "
                    f"{clip(str(item.get('title', '')))}{parent_note}"
                )
    print("")
    grouped = as_list(tickets.get("grouped_open"))
    if grouped:
        print("open initiatives:")
        for group in grouped[:8]:
            if not isinstance(group, dict):
                continue
            ticket = group.get("ticket")
            if not isinstance(ticket, dict):
                continue
            label = "initiative" if group.get("is_initiative") else "ticket"
            print(
                f"  - {label} #{ticket.get('id')} [{ticket.get('status')}] P{ticket.get('priority')} "
                f"{clip(str(ticket.get('title', '')))}"
            )
            for child in as_list(group.get("children"))[:5]:
                if isinstance(child, dict):
                    print(
                        f"    - child #{child.get('id')} [{child.get('status')}] P{child.get('priority')} "
                        f"{clip(str(child.get('title', '')))}"
                    )
        print("")
    blocked = as_list(tickets.get("blocked"))
    print("blocked tickets:")
    if not blocked:
        print("  - (none)")
    else:
        for item in blocked[:5]:
            if isinstance(item, dict):
                print(f"  - #{item.get('id')} {clip(str(item.get('title', '')))}")
    print("")


def clip(text: str, limit: int = 180) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def handoff_summary_line(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return "(empty)"
    in_summary = False
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("## summary"):
            in_summary = True
            continue
        if in_summary:
            if lower.startswith("##"):
                break
            if stripped.startswith("- "):
                return stripped[2:].strip()
            if stripped:
                return stripped
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return clip(first, 160)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def state_value(state: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "(unset)"


def event_display_line(item: Any) -> str:
    """One-line event for CLI — no bare None prefixes."""
    if isinstance(item, str):
        return clip(item)
    if not isinstance(item, dict):
        return clip(str(item))

    created = item.get("created_at")
    created_short = ""
    if isinstance(created, str) and created.strip():
        created_short = created.strip()[:19].replace("T", " ")

    source = item.get("source")
    source_text = source.strip() if isinstance(source, str) and source.strip() else ""

    summary = item.get("summary")
    if isinstance(summary, str) and summary.strip():
        body = summary.strip()
    else:
        content = item.get("content") or item.get("display") or ""
        body = handoff_summary_line(str(content))

    parts = [part for part in (created_short, source_text, body) if part]
    return clip(" · ".join(parts) if parts else str(item))


def print_agent_activity(sync: dict[str, Any]) -> None:
    activity = sync.get("agent_activity")
    if not isinstance(activity, dict):
        return
    last_by_source = activity.get("last_by_source")
    if not isinstance(last_by_source, dict) or not last_by_source:
        return
    print("last contact:")
    for source in ("cursor", "codex", "chatgpt"):
        entry = last_by_source.get(source)
        if not isinstance(entry, dict):
            continue
        last_at = entry.get("last_at", "?")
        summary = entry.get("summary", "")
        mem_id = entry.get("memory_id", "?")
        print(f"  - {source}: {last_at} (#{mem_id}) — {clip(str(summary), 120)}")
    print("")


def print_agent_sync_bundle(sync: dict[str, Any], *, agent: str) -> None:
    state = sync.get("state")
    if not isinstance(state, dict):
        state = {}
    health = sync.get("bus_health")
    if not isinstance(health, dict):
        health = {}

    role = sync.get("role")
    if isinstance(role, str) and role.strip():
        print("Your role")
        print("---------")
        print(role.strip())
        print("")

    print("Crowley agent sync")
    print("==================")
    print(f"agent: {sync.get('agent', agent)}")
    print(f"version: {health.get('version', '(unknown)')}")
    print(f"phase: {state_value(state, 'phase', 'current_phase')}")
    print(f"focus: {state_value(state, 'focus', 'current_focus')}")
    print(f"risk: {state_value(state, 'risk', 'current_risk')}")
    print(
        "next action: "
        f"{sync.get('recommended_next_action') or state_value(state, 'next_action')}"
    )
    print("")
    print_agent_activity(sync)

    print("events from this agent:")
    own = as_list(sync.get("events_from_this_agent"))
    if not own:
        print("  - (none)")
    else:
        for item in own[:5]:
            print(f"  - {event_display_line(item)}")

    print("")
    print("events from other agents:")
    other = as_list(sync.get("events_from_other_agents"))
    if not other:
        print("  - (none)")
    else:
        for item in other[:5]:
            print(f"  - {event_display_line(item)}")

    print("")
    print_tickets_summary(sync, agent=agent)

    print("open tasks:")
    tasks = as_list(sync.get("open_tasks"))
    if not tasks:
        print("  - (none)")
    else:
        for item in tasks[:5]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("task") or item.get("content")
                tid = item.get("id", "?")
                print(f"  - #{tid} {clip(str(title or item))}")
            else:
                print(f"  - {clip(str(item))}")


def verify_agent_handoff(agent: str) -> tuple[bool, str]:
    """Confirm latest handoff via agent_activity (not fuzzy retrieve)."""
    sync, error = fetch_json(url("/api/agent/sync", {"agent": agent, "limit": 5}))
    if error or sync is None:
        return False, error or "agent sync unavailable"

    activity = sync.get("agent_activity")
    if not isinstance(activity, dict):
        return False, "agent_activity missing from sync bundle"

    last_by_source = activity.get("last_by_source")
    if not isinstance(last_by_source, dict):
        return False, "no last_by_source in agent_activity"

    entry = last_by_source.get(agent)
    if not isinstance(entry, dict):
        return False, f"no ingested handoff for {agent}"

    last_at = str(entry.get("last_at", ""))
    mem_id = entry.get("memory_id", "?")
    summary = clip(str(entry.get("summary", "")), 100)
    return True, f"last {agent} at {last_at} (memory #{mem_id}) — {summary}"


def touch_session_marker() -> None:
    SESSION_MARKER.parent.mkdir(parents=True, exist_ok=True)
    SESSION_MARKER.write_text(
        datetime.now(timezone.utc).isoformat(),
        encoding="utf-8",
    )


def clear_session_marker() -> None:
    try:
        SESSION_MARKER.unlink(missing_ok=True)
    except OSError:
        pass


def session_marker_age_seconds() -> float | None:
    if not SESSION_MARKER.is_file():
        return None
    try:
        started = datetime.fromisoformat(SESSION_MARKER.read_text(encoding="utf-8").strip())
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - started).total_seconds()
    except (OSError, ValueError):
        return None


def handoff_since_session(agent: str) -> bool:
    """True if agent posted after session marker was set."""
    if not SESSION_MARKER.is_file():
        return True
    sync, _ = fetch_json(url("/api/agent/sync", {"agent": agent, "limit": 5}))
    if not sync:
        return False
    activity = sync.get("agent_activity")
    if not isinstance(activity, dict):
        return False
    entry = (activity.get("last_by_source") or {}).get(agent)
    if not isinstance(entry, dict):
        return False
    last_at = entry.get("last_at")
    if not isinstance(last_at, str):
        return False
    try:
        marker_text = SESSION_MARKER.read_text(encoding="utf-8").strip()
        marker_dt = datetime.fromisoformat(marker_text)
        handoff_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
        if marker_dt.tzinfo is None:
            marker_dt = marker_dt.replace(tzinfo=timezone.utc)
        return handoff_dt >= marker_dt
    except (OSError, ValueError):
        return False


def print_sync_extras(sync: dict[str, Any], *, agent: str) -> None:
    """Decisions, loops, tickets, and retrieved memories."""
    decisions = as_list(sync.get("recent_decisions"))
    print("recent decisions:")
    if not decisions:
        print("  - (none)")
    else:
        for item in decisions[:5]:
            if isinstance(item, dict):
                text = (
                    item.get("decision")
                    or item.get("title")
                    or item.get("content")
                    or item.get("summary")
                )
                print(f"  - {clip(str(text or item))}")
            else:
                print(f"  - {clip(str(item))}")

    print("")
    loops = as_list(sync.get("open_loops"))
    print("open loops:")
    if not loops:
        print("  - (none)")
    else:
        for item in loops[:5]:
            if isinstance(item, dict):
                text = (
                    item.get("loop")
                    or item.get("title")
                    or item.get("content")
                    or item.get("summary")
                )
                print(f"  - {clip(str(text or item))}")
            else:
                print(f"  - {clip(str(item))}")

    print("")
    print_tickets_summary(sync, agent=agent)

    print("")
    memories = as_list(sync.get("relevant_memories"))
    print("top retrieved memories:")
    if not memories:
        print("  - (none)")
    else:
        for item in memories[:5]:
            print(f"  - {event_display_line(item)}")


def import_crowley():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import crowley  # noqa: WPS433

    return crowley
