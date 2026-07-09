#!/usr/bin/env python3
"""V4 acceptance test 4 — state evolution (V4.5 #374)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"
_V45_GATE = "V4.5 T6 (#374) — spark truth arbitration"


@unittest.skip(_V45_GATE)
class V4AcceptanceTruthTests(unittest.TestCase):
    def test_contradiction_downgrades_older_spark(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "truth_state_evolution.json").read_text())
        self.assertTrue(fixture["expect"]["older_downgraded"])
        self.assertTrue(fixture["expect"]["no_hard_delete"])
        self.fail("implement after V4.5 T1–T2 land")


if __name__ == "__main__":
    unittest.main()
