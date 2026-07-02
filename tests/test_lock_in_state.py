#!/usr/bin/env python3
"""lock_in_state.py hygiene tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from lock_in_state import (  # noqa: E402
    _close_shipped_loops,
    _refresh_project_state,
    project_state_updates,
    run_lock_in,
)


class LockInStateTests(IsolatedDbTestCase):
    def test_project_state_updates_reference_quality_batch(self) -> None:
        updates = project_state_updates()
        self.assertIn("V3.9.5", updates["phase"])
        self.assertIn("#25", updates["focus"])
        self.assertNotIn("#23", updates["next_action"])

    def test_close_shipped_loops_closes_superseded_items(self) -> None:
        pid = self._seed_project()
        stale_id = crowley.save_open_loop(
            pid,
            "Cursor implementation of tickets #9-#23 remains open",
            priority=1,
            source="extract",
        )
        keep_id = crowley.save_open_loop(
            pid,
            "Debounced canon synthesis after ingest",
            priority=3,
            source="extract",
        )
        closed = _close_shipped_loops(pid)
        self.assertIn(stale_id, closed)
        self.assertNotIn(keep_id, closed)
        self.assertEqual(
            crowley.list_open_loops(pid, status="open", limit=10)[0]["id"],
            keep_id,
        )

    def test_refresh_project_state_writes_lock_in_fields(self) -> None:
        pid = self._seed_project()
        crowley.update_project_state_field(
            pid, "focus", "Review ticket #23 handoff", updated_by="extract"
        )
        fields = _refresh_project_state(pid)
        self.assertEqual(
            set(fields),
            {"phase", "focus", "current_risk", "next_action", "what_changed"},
        )
        state = crowley.get_project_state(pid)
        assert state is not None
        self.assertIn("V3.9.5", str(state["focus"]))
        self.assertIn("V3.9.4", str(state["phase"]))

    def test_run_lock_in_dry_run_does_not_mutate(self) -> None:
        pid = self._seed_project()
        loop_id = crowley.save_open_loop(
            pid,
            "Plan agent feed UI tab — ticket #3 for Codex",
            priority=3,
            source="extract",
        )
        before = crowley.get_project_state(pid)
        assert before is not None
        before_focus = before["focus"]

        result = run_lock_in(dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertGreaterEqual(len(result["closed_loop_ids"]), 1)

        after = crowley.get_project_state(pid)
        assert after is not None
        self.assertEqual(after["focus"], before_focus)
        open_loops = crowley.list_open_loops(pid, status="open", limit=10)
        self.assertTrue(any(int(row["id"]) == loop_id for row in open_loops))

    def _seed_project(self) -> int:
        conn = crowley.connect_db()
        project_id = crowley._active_project_id(conn)
        conn.close()
        assert project_id is not None
        return int(project_id)


if __name__ == "__main__":
    unittest.main()
