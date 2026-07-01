#!/usr/bin/env python3
"""One-shot state lock-in: project_state, loop hygiene, canon seed, next tickets, Codex handoff."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402

INBOX = ROOT / ".crowley" / "inbox"
PYTHON = ROOT / "venv" / "bin" / "python3"

# Open loops that describe shipped work — close on lock-in
SHIPPED_LOOP_SNIPPETS = (
    "v3.6 phase 4 memory consolidation",
    "v3.8 planning",
    "v3.8 agent feed",
    "memory trail",
    "multi-agent sync",
    "agent parity",
    "concurrent ticketing",
    "live ui reflects cursor handoffs",
    "phase x/y visible in project",
    "add /task done",
    "complete phase 2/3",
    "complete phase 3/3",
    "run browser visual check on memory tab",
    "ensure future handoffs are automatically ingested",
    "qa inbox ingest and verify retrieve",
    "finish diagnostics qa",
    "ui memory panel",
    "restart the crowley bus",
    "project_state regarding phase",
    "project_state is stale",
    "sessionstop hook",
    "session stop hook",
    "stop hook or richer auto-handoff",
    "run full sync qa",
    "cursor can continue with ci",
    "git init",
    "initialize git",
    "automated ci",
    "ci test suite",
    "ci pipeline",
    "v3.9.1 ci",

CANON_LAYERS = [
    (
        "Canon: Project",
        "Crowley V3.9.1 Repository & CI is shipped. Local-first OS: chat, SQLite memory, "
        "tickets board, GitHub CI on main, HTTP bus at 127.0.0.1:8765. Evidence: VERSIONS.md, "
        "docs/PROJECT_STATE.md, docs/WHERE_WE_ARE.md, github.com/adkinsd2261/crowley.",
    ),
    (
        "Canon: Agents",
        "Codex architects and mints tickets; Cursor builds and closes tickets via handoff + "
        "--ticket. Crowley is the only hub — no direct Codex↔Cursor messaging. "
        "Evidence: CODEX.md, CURSOR.md, ADR-028, ADR-030.",
    ),
    (
        "Canon: Work",
        "V3.8 Memory Trail, V3.8.1 agent parity, V3.9 concurrent ticketing, and V3.9.1 git/CI "
        "are complete. Next: first canon synthesis, agent feed UI tab, or V4 connectivity. "
        "Evidence: docs/TICKETS.md, docs/ROADMAP.md.",
    ),
    (
        "Canon: Mr. Go",
        "Mr. Go wants filesystem truth, agent memory trails, and Codex/Cursor continuity without "
        "manual relay. Evidence: docs/WHERE_WE_ARE.md.",
    ),
]

NEXT_TICKETS = [
    {
        "title": "Plan first canon synthesis run",
        "assignee": "codex",
        "priority": 2,
        "description": "Review synthesize_canon.py packet; decide when to --write.",
        "acceptance": "Handoff with go/no-go and steps",
    },
    {
        "title": "Plan agent feed UI tab",
        "assignee": "codex",
        "priority": 3,
        "description": "Spec Intelligence tab for cross-agent handoffs using existing APIs.",
        "acceptance": "Ticket(s) minted for Cursor if approved",
    },
]

CODEX_HANDOFF_BODY = """# Crowley Handoff

Source: codex
Type: architect_handoff
Project: Crowley

## Summary

- State lock-in pass: WHERE_WE_ARE.md, refreshed project_state, canon seed, loop hygiene, next-initiative tickets minted. Crowley is at V3.9 with full multi-agent memory trail (handoffs, agent_activity, tickets).

## What Changed

- Planning handoff only — documents current position for the next Codex session.

## Files Changed

- None; planning-only architect handoff.

## Decisions

- Filesystem + WHERE_WE_ARE.md is the Codex onboarding source of truth.
- Tickets table is the agent work board; legacy tasks/loops retained.
- Next initiative chosen by Mr. Go: CI (V3.9.1), canon synthesis, or agent feed tab — Codex refines via minted tickets.

## QA Results

- lock_in_state.py run; codex_sync --before shows Cursor V3.9 ship (#167+) and fresh codex contact.

## Known Issues

- Some open_loops may remain until manually reviewed; test DB probe-row pollution possible.

## Open Loops

- Debounced canon synthesis after ingest (P3)
- Plan agent feed UI tab (ticket #3)

## Next Action

- Mr. Go returns with Cursor to plan ticketing; Codex/Cursor run --before, read docs/WHERE_WE_ARE.md, mint builder tickets from planning board.

## Do Not Build

- Do not build direct Codex-to-Cursor communication; Crowley is the only hub.
- Do not re-architect V3.9 ticketing — it is shipped.
"""


def _run(cmd: list[str]) -> int:
    return subprocess.run(cmd, cwd=ROOT, check=False).returncode


def _seed_canon(project_id: int) -> int:
    added = 0
    for title, body in CANON_LAYERS:
        content = f"{title}\n\n{body}"
        existing = crowley.list_canon_memory_items(project_id)
        if any(content[:40] in str(row["content"]) for row in existing):
            continue
        mid = crowley.save_memory_item(
            "summary",
            content,
            source="crowley",
            project_id=project_id,
            importance=5,
            pinned=True,
            confidence=1.0,
        )
        if mid:
            added += 1
    return added


def _close_shipped_loops(project_id: int) -> int:
    closed = 0
    for loop in crowley.list_open_loops(project_id, status="open", limit=200):
        desc = str(loop["description"]).lower()
        if any(snippet in desc for snippet in SHIPPED_LOOP_SNIPPETS):
            if crowley.close_open_loop(int(loop["id"])):
                closed += 1
    return closed


def _refresh_project_state(project_id: int) -> None:
    updates = {
        "phase": "Post-V3.9.1 — stable hub; plan next initiative",
        "focus": (
            "V3.9.1 git/CI live on github.com/adkinsd2261/crowley; memory trail, tickets, "
            "and handoffs with --from-git file lists. Next: ticketing planning session."
        ),
        "current_risk": (
            "Stale open_loops may remain until reviewed; test DB accumulates QA probe rows; "
            "bus must be restarted after version bumps to refresh /api/health."
        ),
        "next_action": (
            "Mr. Go returns with Cursor to plan ticketing; run scripts/cursor_sync.py --before "
            "or scripts/codex_sync.py --before → read docs/WHERE_WE_ARE.md → mint builder tickets."
        ),
        "what_changed": (
            "V3.9.1 Repository & CI shipped; GitHub remote + Actions CI on main; "
            "HTTPS git auth verified; handoff --from-git file lists operational."
        ),
    }
    for field, value in updates.items():
        crowley.update_project_state_field(project_id, field, value, updated_by="lock_in")


def _mint_tickets(project_id: int) -> list[int]:
    created: list[int] = []
    for spec in NEXT_TICKETS:
        title = spec["title"]
        existing = crowley.list_tickets(project_id=project_id, open_only=True, limit=100)
        if any(title.lower() in str(row["title"]).lower() for row in existing):
            continue
        desc = spec["description"]
        acc = spec.get("acceptance")
        if acc:
            desc = f"{desc}\n\nAcceptance:\n- {acc}"
        result = crowley.create_ticket(
            title,
            description=desc,
            assignee=spec["assignee"],
            priority=spec["priority"],
            source="crowley",
            actor="lock_in",
            project_id=project_id,
        )
        created.append(int(result["ticket"]["id"]))
    return created


def _ingest_codex_handoff() -> int | None:
    INBOX.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in INBOX.glob("codex_*_handoff_*.md")}
    _run([str(PYTHON), str(ROOT / "scripts" / "crowley_handoff.py"), "--source", "codex", "--type", "architect_handoff"])
    new_files = [p for p in INBOX.glob("codex_*_handoff_*.md") if p.name not in before]
    if not new_files:
        candidates = sorted(INBOX.glob("codex_*_handoff_*.md"), key=lambda p: p.stat().st_mtime)
        handoff = candidates[-1] if candidates else None
    else:
        handoff = sorted(new_files, key=lambda p: p.stat().st_mtime)[-1]
    if handoff is None:
        return None
    handoff.write_text(CODEX_HANDOFF_BODY, encoding="utf-8")
    _run([str(PYTHON), str(ROOT / "scripts" / "ingest_inbox.py")])
    activity = crowley._agent_activity_summary(crowley.get_active_project() and int(crowley.get_active_project()["id"]))
    entry = (activity.get("last_by_source") or {}).get("codex")
    if isinstance(entry, dict):
        return int(entry["memory_id"]) if entry.get("memory_id") is not None else None
    return None


def main() -> int:
    crowley.setup_db()
    project = crowley.get_active_project()
    if project is None:
        print("No active project.")
        return 1
    pid = int(project["id"])

    _refresh_project_state(pid)
    loops_closed = _close_shipped_loops(pid)
    canon_added = _seed_canon(pid)
    ticket_ids = _mint_tickets(pid)
    crowley.save_decision(
        pid,
        "State lock-in: WHERE_WE_ARE.md + canon + tickets for multi-agent continuity",
        detail="lock_in_state.py",
        source="crowley",
    )
    mem_id = _ingest_codex_handoff()

    print("lock_in_state complete")
    print(f"  project_state: refreshed")
    print(f"  loops_closed: {loops_closed}")
    print(f"  canon_rows_added: {canon_added}")
    print(f"  tickets_minted: {ticket_ids}")
    print(f"  codex_handoff_memory_id: {mem_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
