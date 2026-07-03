#!/usr/bin/env python3
"""State lock-in: refresh project_state and close superseded open loops."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402

# Open loops describing shipped or superseded work — close on lock-in.
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
    # Pre-V4 ladder shipped (#9–#23) and superseded planning (#4–#8)
    "tickets #9-#23",
    "tickets #9–#23",
    "implementation of tickets #9",
    "planning workflow v1 tickets #4-#8",
    "tickets #4-#8",
    "planning workflow v1 tickets",
    # Agent Feed shipped (#19)
    "agent feed ui tab",
    "agent feed tab",
    "plan agent feed",
    # Test DB isolation shipped (#13)
    "test db isolation",
    "test environments lack isolation",
    "qa test environments lack isolation",
    "probe memory rows",
    # QA handoff planning loops resolved by tickets #37 / #35
    "loop hygiene and state lock-in",
    "bus restart/version drift",
    "version drift hardening",
    # V3.9.6 workspace polish shipped (#31–#36)
    "proceed to ticket #34",
    "ticket #34 to implement",
    "workspace polish in progress",
    # V3.9.5 conversation shipped (#25–#30)
    "v3.9.5 conversation",
)


def project_state_updates() -> dict[str, str]:
    """Current world-model fields after V3.9.11 ship."""
    return {
        "phase": "V3.9.11 shipped — Live Wire",
        "focus": "V3.9.12 Portable Context Terminal; V4 Spark Lanes planned",
        "current_risk": (
            "Restart bus after version bumps so /api/health matches constants."
        ),
        "next_action": (
            "Claim V3.9.12 #76 one ticket at a time after Mr. Go review."
        ),
        "what_changed": (
            "V3.9.11 Live Wire: activity_pulses + build_activity_wire, compose In the air "
            "ticker UI, sync/world exposure, runtime brain switcher (OpenAI/Claude/Ollama), "
            "agent feed lesson notes + latest handoff fix. Task frame (V3.9.10) unchanged."
        ),
    }


def _close_shipped_loops(project_id: int, *, dry_run: bool = False) -> list[int]:
    closed_ids: list[int] = []
    for loop in crowley.list_open_loops(project_id, status="open", limit=200):
        desc = str(loop["description"]).lower()
        if any(snippet in desc for snippet in SHIPPED_LOOP_SNIPPETS):
            loop_id = int(loop["id"])
            if dry_run:
                closed_ids.append(loop_id)
            elif crowley.close_open_loop(loop_id):
                closed_ids.append(loop_id)
    return closed_ids


def _refresh_project_state(project_id: int, *, dry_run: bool = False) -> list[str]:
    changed: list[str] = []
    for field, value in project_state_updates().items():
        if dry_run:
            changed.append(field)
        else:
            crowley.update_project_state_field(
                project_id, field, value, updated_by="lock_in"
            )
            changed.append(field)
    return changed


def run_lock_in(*, dry_run: bool = False) -> dict[str, object]:
    crowley.setup_db()
    project = crowley.get_active_project()
    if project is None:
        raise RuntimeError("No active project.")

    project_id = int(project["id"])
    state_fields = _refresh_project_state(project_id, dry_run=dry_run)
    closed_loop_ids = _close_shipped_loops(project_id, dry_run=dry_run)

    return {
        "project_id": project_id,
        "state_fields": state_fields,
        "closed_loop_ids": closed_loop_ids,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh project_state and close stale loops.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing to the database.",
    )
    args = parser.parse_args()

    try:
        result = run_lock_in(dry_run=args.dry_run)
    except RuntimeError as exc:
        print(exc)
        return 1

    prefix = "dry-run: " if args.dry_run else ""
    print(f"{prefix}lock_in_state complete")
    print(f"  project_state fields: {', '.join(result['state_fields'])}")
    print(f"  loops_closed: {len(result['closed_loop_ids'])} {result['closed_loop_ids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
