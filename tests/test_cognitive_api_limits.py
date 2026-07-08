#!/usr/bin/env python3
"""V4 T21 — cognitive API input limits and rate-limit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import cognitive_ingest  # noqa: E402
import crowley  # noqa: E402
import system_integrity  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class CognitiveApiLimitTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        system_integrity._write_timestamps.clear()  # noqa: SLF001
        system_integrity._cognitive_ingest_timestamps.clear()  # noqa: SLF001

    def tearDown(self) -> None:
        system_integrity._write_timestamps.clear()  # noqa: SLF001
        system_integrity._cognitive_ingest_timestamps.clear()  # noqa: SLF001
        super().tearDown()

    def test_oversized_cognitive_ingest_rejected_before_receipt(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/cognitive/ingest",
            json={"content": "x" * ((32 * 1024) + 1), "source": "manual"},
        )
        self.assertEqual(res.status_code, 422, res.text)

        conn = crowley.connect_db()
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM memory_items
                WHERE summary = 'Cognitive ingest receipt'
                  AND json_extract(metadata_json, '$.cognitive_ingest') = 1
                """
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        self.assertEqual(int(row["n"]), 0)

    def test_manual_spark_seed_content_capped_at_300_chars(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/cognitive/sparks",
            json={
                "content": "x" * 301,
                "lane": "work",
                "why_keep": "Exercises the API-level content limit.",
                "worth_reason": "Keeps manual seed requests aligned with spark schema.",
                "confidence": 0.7,
            },
        )
        self.assertEqual(res.status_code, 422, res.text)

    def test_cognitive_ingest_rate_limit_triggers_after_ten_per_minute(self) -> None:
        client = TestClient(crowley_app.app)
        with mock.patch.object(
            cognitive_ingest,
            "ingest_cognitive_content",
            return_value={
                "status": "accepted",
                "memory_item_id": 100,
                "extraction": {"status": "queued"},
            },
        ) as ingest_mock:
            for idx in range(system_integrity.COGNITIVE_INGEST_RATE_LIMIT_PER_MINUTE):
                res = client.post(
                    "/api/cognitive/ingest",
                    json={
                        "content": f"Rate-limit probe cognitive ingest receipt {idx}.",
                        "source": "manual",
                    },
                )
                self.assertEqual(res.status_code, 201, res.text)

            blocked = client.post(
                "/api/cognitive/ingest",
                json={
                    "content": "This eleventh cognitive ingest should be blocked.",
                    "source": "manual",
                },
            )

        self.assertEqual(blocked.status_code, 429, blocked.text)
        self.assertEqual(blocked.json().get("error"), "automation_guardrail")
        self.assertIn("cognitive ingest rate limit", blocked.json().get("message", ""))
        self.assertEqual(ingest_mock.call_count, system_integrity.COGNITIVE_INGEST_RATE_LIMIT_PER_MINUTE)


if __name__ == "__main__":
    unittest.main()
