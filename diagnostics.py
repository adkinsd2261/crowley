"""Crowley diagnostics domain — read-only factual briefings."""

from __future__ import annotations

from collections.abc import Iterator

import sqlite3

import crowley


def _diag_val(value: str | None) -> str:
    if value is None or value == "":
        return "Unknown"
    return value


def gather_diagnostics_context() -> dict[str, object]:
    """Gather structured facts from SQLite only. No inference, no writes."""
    project = crowley.get_active_project()
    state = None
    decisions: list[sqlite3.Row] = []
    open_loops: list[sqlite3.Row] = []
    if project is not None:
        pid = int(project["id"])
        state = crowley.get_project_state(pid)
        decisions = crowley.list_decisions(pid, limit=crowley.DIAGNOSTICS_DECISIONS_LIMIT)
        open_loops = crowley.list_open_loops(pid, status="open", limit=crowley.LOOPS_LIMIT)

    open_tasks = crowley.list_tasks(status="open")[:crowley.DIAGNOSTICS_TASKS_LIMIT]
    recent_summary_sparks = crowley.list_recent_summary_sparks()

    resolved = crowley.get_model_provider()
    brain_label = "OpenAI" if resolved == "openai" else "Ollama"

    return {
        "project": project,
        "state": state,
        "decisions": decisions,
        "open_loops": open_loops,
        "open_tasks": open_tasks,
        "recent_summary_sparks": recent_summary_sparks,
        "system_health": {
            "brain": brain_label,
            "memory": "online",
            "tasks": "online",
            "world_model": "online",
            "version": crowley.CROWLEY_RELEASE_LABEL,
        },
    }


def _serialize_diagnostics_facts(context: dict[str, object]) -> str:
    """Render diagnostics context as plain text ground truth for the model."""
    lines: list[str] = []
    project = context.get("project")
    state = context.get("state")

    if project is None:
        lines.append("Current Project: Unknown")
        lines.append("Current Phase: Unknown")
        lines.append("Current Focus: Unknown")
        lines.append("What Changed Recently: Unknown")
        lines.append("Current Risk: Unknown")
        lines.append("Recommended Next Action: Unknown")
    else:
        lines.append(f"Current Project: {project['name']} ({project['status']})")
        if state is None:
            lines.append("Current Phase: Unknown")
            lines.append("Current Focus: Unknown")
            lines.append("What Changed Recently: Unknown")
            lines.append("Current Risk: Unknown")
            lines.append("Recommended Next Action: Unknown")
        else:
            lines.append(f"Current Phase: {_diag_val(state['phase'])}")
            lines.append(f"Current Focus: {_diag_val(state['focus'])}")
            lines.append(f"What Changed Recently: {_diag_val(state['what_changed'])}")
            lines.append(f"Current Risk: {_diag_val(state['current_risk'])}")
            lines.append(f"Recommended Next Action: {_diag_val(state['next_action'])}")

    lines.append("")
    lines.append("Open Tasks:")
    tasks = context.get("open_tasks") or []
    if not tasks:
        lines.append("- None")
    else:
        for t in tasks:
            due = t["due_date"] or "no due date"
            proj = t["project"] or "general"
            lines.append(f"- #{t['id']} {t['title']} (due: {due}, project: {proj})")

    lines.append("")
    lines.append("Open Loops:")
    loops = context.get("open_loops") or []
    if not loops:
        lines.append("- None")
    else:
        for loop in loops:
            lines.append(f"- #{loop['id']} [priority {loop['priority']}] {loop['description']}")

    lines.append("")
    lines.append("Recent Decisions:")
    decisions = context.get("decisions") or []
    if not decisions:
        lines.append("- None")
    else:
        for d in reversed(decisions):
            entry = f"- [{d['id']}] {d['summary']}"
            if d["detail"]:
                entry += f" — {d['detail']}"
            lines.append(entry)

    lines.append("")
    lines.append("Recent Summary Sparks:")
    sparks = context.get("recent_summary_sparks") or []
    if not sparks:
        lines.append("- None")
    else:
        for s in reversed(sparks):
            lines.append(f"- [{s['id']}] {s['content']}")

    health = context["system_health"]
    lines.append("")
    lines.append("System Health:")
    lines.append(f"- Brain: {health['brain']}")
    lines.append(f"- Memory: {health['memory']}")
    lines.append(f"- Tasks: {health['tasks']}")
    lines.append(f"- World Model: {health['world_model']}")
    lines.append(f"- Version: {health['version']}")

    return "\n".join(lines)


def _diagnostics_system_prompt(facts: str) -> str:
    """Factual diagnostics briefing — separate from chat personality/mode/depth."""
    return f"""You are Crowley producing a read-only operating-system diagnostic report for {crowley.USER_NAME}.

This path is separate from chat. Do not use co-founder voice, exploration tone, inferred conversation mode, or response depth rules from the chat prompt.

Output rules:
- Start immediately with the first section heading — no greeting, sign-off, preamble, or conversational opener.
- Do not write salutations such as "Good morning", "Hello", "Hi", or "Hey".
- Do not use co-founder phrasing, warmth, filler, banter, or chat personality.
- Use headings or bullet lists only — report-like, not conversational.
- Everything inside GROUND TRUTH CONTEXT is authoritative SQL/system output.
- Never invent missing information.
- If a field is Unknown or listed as None, explicitly say Unknown in the report.
- Do not speculate.
- Do not modify state.
- Do not recommend work unless it is supported by open tasks, open loops, project state, or recent decisions in the context.

Tone: factual, structured, systems-minded. Mention {crowley.USER_NAME} only inside factual sentences — never as a salutation.

Produce a briefing with these sections in order (each line is a section heading):

Current Project
Current Phase
Current Focus
What Changed Recently
Open Tasks
Open Loops
Recent Decisions
Recent Summary Sparks
Current Risk
Recommended Next Action
System Health

For System Health, report exactly:
Brain: (from context)
Memory: Online
Tasks: Online
World Model: Online
Version: {crowley.CROWLEY_RELEASE_LABEL}

GROUND TRUTH CONTEXT:
{facts}"""


def format_diagnostics_prompt(context: dict[str, object]) -> list[dict[str, str]]:
    """Build the diagnostics-only prompt from structured facts."""
    facts = _serialize_diagnostics_facts(context)
    return [
        {"role": "system", "content": _diagnostics_system_prompt(facts)},
        {"role": "user", "content": "Produce the diagnostic briefing now. Begin with the Current Project heading — no greeting or conversational opener."},
    ]


def run_diagnostics() -> str | None:
    """Read-only diagnostics pipeline: gather facts, stream briefing, no writes."""
    print("Crowley: thinking...", flush=True)
    started = False
    parts: list[str] = []
    for token in iter_diagnostics_tokens():
        started = crowley._print_stream_token(token, started)
        parts.append(token)
    if not started:
        print("\rCrowley: (no response)", flush=True)
        return None
    print(flush=True)
    reply = "".join(parts).strip()
    return reply if reply else None


def iter_diagnostics_tokens() -> Iterator[str]:
    """Yield diagnostics briefing tokens. Read-only — no DB writes."""
    context = gather_diagnostics_context()
    messages = format_diagnostics_prompt(context)
    yield from crowley.iter_model_tokens(messages, quiet=True)
