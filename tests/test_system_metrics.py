"""Operator metrics foundation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402
from tests.db_helpers import IsolatedDbTestCase  # noqa: E402


class SystemMetricsTestCase(IsolatedDbTestCase):
    def test_record_and_summary_24h(self) -> None:
        crowley.record_system_metric("retrieval", label="keyword-only fallback")
        crowley.record_system_metric("chat_error", label="empty response")
        crowley.record_system_metric("ingest_ok", label="cursor")
        crowley.record_system_metric("ticket_created", label="99")

        summary = crowley.get_metrics_summary_24h()
        self.assertEqual(summary["window_hours"], 24)
        counts = summary["counts"]
        self.assertGreaterEqual(int(counts.get("retrieval", 0)), 1)
        self.assertGreaterEqual(int(summary["chat_errors"]), 1)
        self.assertGreaterEqual(int(summary["ingest_ok"]), 1)
        self.assertGreaterEqual(int(summary["ticket_events"]), 1)
        self.assertIn("keyword-only fallback", summary["retrieval_modes"])


if __name__ == "__main__":
    unittest.main()
