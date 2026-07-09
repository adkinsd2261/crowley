#!/usr/bin/env python3
"""V4 acceptance test 3 — context token budget (V4.4 #367)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"
_V44_GATE = "V4.4 T5 (#367) — token budget and chat wire"


@unittest.skip(_V44_GATE)
class V4AcceptanceContextTests(unittest.TestCase):
    def test_prompt_cognitive_section_under_budget(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "context_token_budget.json").read_text())
        self.assertGreater(fixture["seed_count"], 15)
        self.assertIn("max_prompt_chars", fixture)
        self.fail("implement after V4.4 T1–T4 land")


if __name__ == "__main__":
    unittest.main()
