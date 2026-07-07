#!/usr/bin/env python3
"""Tests for portable writeback acceptance review and promotion."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "portable_writeback_valid.json"


class PortableWritebackAcceptanceTests(IsolatedDbTestCase):
    def test_missing_surface_defaults_to_chatgpt_for_acceptance(self) -> None:
        payload = {
            "format": "crowley_terminal_writeback_v1",
            "session": {
                "summary": "Validated acceptance flow for missing session surface.",
                "model": "gpt-4.1",
            },
            "sparks": [
                {
                    "content": "Spark acceptance should not fail when session.surface is omitted in ChatGPT actions payloads.",
                    "lane": "work",
                    "why_keep": "Prevents false chatgpt_surface rejection and keeps promotion deterministic.",
                    "confidence": 0.9,
                    "sensitivity": "normal",
                }
            ],
        }
        result = crowley.ingest_terminal_writeback(payload)
        self.assertEqual(result["status"], "ok")

        report = crowley.build_portable_writeback_acceptance_report(apply=False)
        session = next(
            s for s in report["sessions"] if int(s["session_receipt_id"]) == int(result["session_receipt_id"])
        )
        self.assertEqual(session["surface"], "chatgpt")
        accepted = [
            item
            for item in report["accepted"]
            if int(item["session_receipt_id"]) == int(result["session_receipt_id"])
        ]
        self.assertTrue(accepted)
        self.assertTrue(accepted[0]["accepted"])

    def test_acceptance_report_promotes_user_session_sparks(self) -> None:
        raw = FIXTURE.read_text(encoding="utf-8")
        payload = json.loads(raw)
        payload["session"]["surface"] = "chatgpt"
        payload["session"]["summary"] = "Brainstormed Crowley operating model."
        result = crowley.ingest_terminal_writeback(payload)
        self.assertEqual(result["status"], "ok")

        dry = crowley.build_portable_writeback_acceptance_report(apply=False)
        self.assertGreaterEqual(int(dry["counts"]["accepted"]), 1)

        applied = crowley.build_portable_writeback_acceptance_report(
            apply=True,
            reviewer="test",
        )
        self.assertTrue(applied["applied"])
        self.assertGreaterEqual(int(applied["counts"]["accepted"]), 1)

        active_rows, total = crowley.list_memory_items(
            source=crowley.PORTABLE_TERMINAL_SOURCE,
            status="active",
            limit=20,
        )
        self.assertGreaterEqual(total, 2)
        statuses = {str(row["status"]) for row in active_rows}
        self.assertIn("active", statuses)

    def test_fixture_session_is_rejected(self) -> None:
        payload = {
            "format": "crowley_terminal_writeback_v1",
            "session": {
                "summary": "Discussed V3.9.12 writeback parser scope with D.",
                "surface": "chatgpt",
                "model": "gpt-4.1",
            },
            "sparks": [
                {
                    "content": "D wants paste-ready packets under 12k chars.",
                    "lane": "work",
                    "why_keep": "Shapes portable terminal size discipline.",
                    "confidence": 0.9,
                    "sensitivity": "normal",
                },
                {
                    "content": "Morning walks help D reset before deep work.",
                    "lane": "health",
                    "why_keep": "Operating rhythm affects build quality.",
                    "confidence": 0.8,
                    "sensitivity": "sensitive",
                },
            ],
        }
        crowley.ingest_terminal_writeback(payload)
        report = crowley.build_portable_writeback_acceptance_report(apply=False)
        sessions = report["sessions"]
        self.assertTrue(sessions)
        fixture = next(
            s for s in sessions if s["classification"] == "test_fixture"
        )
        self.assertEqual(fixture["spark_rows_total"], 2)
        rejected = report["rejected"]
        self.assertEqual(len(rejected), 2)
        self.assertEqual(rejected[0]["rejection_reason"], "not_test_fixture")


if __name__ == "__main__":
    unittest.main()
