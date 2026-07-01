#!/usr/bin/env python3
"""Live UI sync tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


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


class WorldDashboardTests(unittest.TestCase):
    def test_dashboard_includes_filesystem_truth(self) -> None:
        crowley.setup_db()
        dash = crowley.build_world_dashboard()
        self.assertIn("filesystem", dash)
        self.assertIn("agent_activity", dash)
        fs = dash["filesystem"]
        self.assertEqual(fs["authority"], "filesystem")
        self.assertEqual(fs["version"], crowley.CROWLEY_VERSION)
        self.assertIn("project_files", dash)

    def test_dashboard_includes_panels(self) -> None:
        crowley.setup_db()
        dash = crowley.build_world_dashboard()
        self.assertIsNotNone(dash.get("project"))
        self.assertIn("tasks", dash)
        self.assertIn("loops", dash)
        self.assertIn("memory_items", dash)
        self.assertIn("counts", dash)
        self.assertIn("synced_at", dash)
        self.assertEqual(dash["version"], crowley.CROWLEY_VERSION)


if __name__ == "__main__":
    unittest.main()
