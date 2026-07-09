#!/usr/bin/env python3
"""V4 acceptance test 6 — security validation (V4.5 #374)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"


class V4AcceptanceSecurityPartialTests(IsolatedDbTestCase):
    """Runs today against T20 write-time gates; full test gated on V4.5."""

    def test_blocked_secret_patterns_fail_validation(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "security_no_leak.json").read_text())
        errors = sparks._spark_content_security_errors(fixture["blocked_content"])
        self.assertTrue(errors, "expected write-time rejection for secret-like ingest")


@unittest.skip("V4.5 T6 (#374) — high-sensitivity light-depth context + encryption")
class V4AcceptanceSecurityFullTests(IsolatedDbTestCase):
    def test_high_sensitivity_excluded_from_light_context(self) -> None:
        fixture = json.loads((FIXTURE_DIR / "security_no_leak.json").read_text())
        seed = fixture["high_sensitivity_seed"]
        self.assertEqual(seed["sensitivity"], "high")
        self.fail("implement after V4.5 T4 encryption + context wire complete")


if __name__ == "__main__":
    unittest.main()
