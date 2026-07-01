#!/usr/bin/env python3
"""Close completed Live UI sync loops and stale tasks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402

# Substrings matching open loops to close (Live UI initiative complete)
CLOSE_LOOP_SNIPPETS = (
    "live ui reflects cursor handoffs",
    "phase x/y visible in project",
    "run browser visual check on memory tab",
    "complete phase 2/3",
    "complete phase 3/3",
    "add /task done",
    "qa inbox ingest and verify retrieve",
    "ensure future handoffs are automatically ingested",
)

STALE_OPEN_TASK_SNIPPETS = (
    "finish diagnostics qa",
)


def main() -> int:
    crowley.setup_db()
    project = crowley.get_active_project()
    if project is None:
        print("No active project.")
        return 1

    pid = int(project["id"])
    closed = 0
    tasks_done = 0

    for loop in crowley.list_open_loops(pid, status="open", limit=100):
        desc = str(loop["description"]).lower()
        if any(snippet in desc for snippet in CLOSE_LOOP_SNIPPETS):
            if crowley.close_open_loop(int(loop["id"])):
                closed += 1

    for task in crowley.list_tasks(status="open"):
        title = str(task["title"]).lower().strip()
        if any(snippet in title for snippet in STALE_OPEN_TASK_SNIPPETS):
            if crowley.complete_task(int(task["id"])):
                tasks_done += 1

    print(f"finalize_live_ui: loops_closed={closed} tasks_done={tasks_done}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
