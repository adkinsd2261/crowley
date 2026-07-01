#!/usr/bin/env python3
"""One-shot backlog hygiene: dedupe tasks, close stale loops, seed missing items."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


def _loop_exists(project_id: int, description: str) -> bool:
    needle = description.strip().lower()[:48]
    for loop in crowley.list_open_loops(project_id, status="open", limit=100):
        if needle in str(loop["description"]).lower():
            return True
    return False


def main() -> int:
    crowley.setup_db()
    project = crowley.get_active_project()
    if project is None:
        print("No active project.")
        return 1

    pid = int(project["id"])
    closed_loops = 0
    done_tasks = 0
    added_loops = 0

    # Duplicate diagnostics QA tasks from early testing
    open_tasks = crowley.list_tasks(status="open")
    seen_titles: set[str] = set()
    for task in open_tasks:
        title = str(task["title"]).strip().lower()
        if title in seen_titles:
            if crowley.update_task_status(int(task["id"]), "done"):
                done_tasks += 1
        else:
            seen_titles.add(title)

    # Stale duplicate diagnostic verification loops (QA passed)
    for loop_id, prefix in [(1, "verify diagnostics"), (2, "verify diagnostics")]:
        for loop in crowley.list_open_loops(pid, status="open", limit=100):
            if int(loop["id"]) == loop_id:
                desc = str(loop["description"]).lower()
                if prefix in desc and crowley.close_open_loop(loop_id):
                    closed_loops += 1

    backlog_seed = [
        (1, "Live UI reflects Cursor handoffs within poll interval"),
        (1, "Phase X/Y visible in project inspector and intelligence summary"),
        (2, "V3.6 Phase 4 memory consolidation"),
        (2, "Add /task done <id> CLI command"),
        (2, "Automated CI test suite for Crowley"),
    ]
    for priority, description in backlog_seed:
        if not _loop_exists(pid, description):
            crowley.save_open_loop(pid, description, priority=priority, source="sync")
            added_loops += 1

    print(
        f"sync_backlog: tasks_done={done_tasks} loops_closed={closed_loops} "
        f"loops_added={added_loops}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
