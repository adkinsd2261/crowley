#!/usr/bin/env python3
"""V4 acceptance test 2 — clean domain retrieval (V4.3 #362)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"
_V43_GATE = "V4.3 T5 (#362) — query interpreter and lane inference"


@unittest.skip(_V43_GATE)
class V4AcceptanceRetrievalTests(unittest.TestCase):
    def test_finance_query_excludes_health_lane(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "retrieval_finance_query.json").read_text())
        forbidden = set(fixture["forbidden_lanes_in_results"])
        self.assertIn("health", forbidden)
        self.fail("implement after V4.3 T1–T4 land")


if __name__ == "__main__":
    unittest.main()
