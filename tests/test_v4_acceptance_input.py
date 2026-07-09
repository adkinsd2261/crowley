#!/usr/bin/env python3
"""V4 acceptance tests 1 and 5 — messy input and noise resistance (V4.2 #357)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"
_V42_GATE = "V4.2 T6 (#357) — intent gate, chunking, schema extensions"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


@unittest.skip(_V42_GATE)
class V4AcceptanceInputTests(unittest.TestCase):
    """Acceptance 1: multi-domain ingest splits into lane-tagged sparks."""

    def test_messy_multi_domain_input(self) -> None:
        fixture = _load("messy_multi_domain_input.json")
        os.environ["CROWLEY_TEST_MODE"] = "1"
        # Implemented in V4.2: ingest fixture raw_text, assert distinct lanes
        self.fail("implement after V4.2 T1–T5 land")

    def test_noise_ignore_temporary(self) -> None:
        """Acceptance 5: ignore/temporary inputs do not pollute active retrieval."""
        fixture = _load("noise_ignore_temporary.json")
        os.environ["CROWLEY_TEST_MODE"] = "1"
        for item in fixture["inputs"]:
            intent = item["intent"]
            # Implemented in V4.2: classify + ingest each text
            self.assertIn(intent, ("ignore", "temporary", "store"))
        self.fail("implement after V4.2 T1 lands")


if __name__ == "__main__":
    unittest.main()
