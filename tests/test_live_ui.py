#!/usr/bin/env python3
"""Live UI sync tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class PhaseProgressTests(unittest.TestCase):
    def test_parse_phase_fraction(self) -> None:
        p = crowley.parse_phase_progress("Phase 1/3 — Live UI sync")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p["current"], 1)
        self.assertEqual(p["total"], 3)

    def test_parse_phase_of(self) -> None:
        p = crowley.parse_phase_progress("V3.7 Phase 2 of 6")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p["current"], 2)
        self.assertEqual(p["total"], 6)

    def test_no_progress_for_plain_phase(self) -> None:
        self.assertIsNone(crowley.parse_phase_progress("V3.7.2 Knowledge Files"))


class WorldDashboardTests(IsolatedDbTestCase):
    def test_dashboard_includes_filesystem_truth(self) -> None:
        dash = crowley.build_world_dashboard()
        self.assertIn("filesystem", dash)
        self.assertIn("agent_activity", dash)
        fs = dash["filesystem"]
        self.assertEqual(fs["authority"], "filesystem")
        self.assertEqual(fs["version"], crowley.CROWLEY_VERSION)
        self.assertIn("project_files", dash)

    def test_dashboard_includes_panels(self) -> None:
        dash = crowley.build_world_dashboard()
        self.assertIsNotNone(dash.get("project"))
        self.assertIn("tasks", dash)
        self.assertIn("loops", dash)
        self.assertIn("memory_items", dash)
        self.assertIn("counts", dash)
        self.assertIn("agent_feed", dash["counts"])
        self.assertIn("synced_at", dash)
        self.assertEqual(dash["version"], crowley.CROWLEY_VERSION)

    def test_dashboard_agent_feed_uses_recent_activity(self) -> None:
        dash = crowley.build_world_dashboard()
        activity = dash.get("agent_activity")
        self.assertIsInstance(activity, dict)
        recent = activity.get("recent") if isinstance(activity, dict) else []
        assert isinstance(recent, list)
        self.assertEqual(dash["counts"]["agent_feed"], len(recent))

    def test_ui_contains_agent_feed_tab(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-tab="agent_feed"', html)
        self.assertIn('id="panel-agent-feed"', html)
        self.assertIn("renderAgentFeedPanel", js)
        self.assertIn("agent_feed:", js)

    def test_ui_contains_ticket_detail_view(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="ticket-detail"', html)
        self.assertIn("renderTicketDetail", js)
        self.assertIn("loadTicketDetail", js)
        self.assertIn("ticketStatusClass", js)
        self.assertIn("linked_handoff", js)
        self.assertIn("linked_ticket_ids", js)
        self.assertIn("has-detail", js)


if __name__ == "__main__":
    unittest.main()
