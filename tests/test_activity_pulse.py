#!/usr/bin/env python3
"""V3.9.11 #70 — activity pulse table and POST API."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class ActivityPulseTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_setup_db_creates_activity_pulses_table(self) -> None:
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_pulses'"
        ).fetchone()
        self.assertIsNotNone(row)

    def test_record_activity_pulse_inserts_row(self) -> None:
        result = crowley.record_activity_pulse(
            "cursor",
            "claimed",
            project_id=self.project_id,
            ticket_id=70,
            summary="Claimed ticket #70",
        )
        assert result is not None
        self.assertEqual(result["agent"], "cursor")
        self.assertEqual(result["verb"], "claimed")
        self.assertEqual(result["ticket_id"], 70)
        self.assertEqual(result["summary"], "Claimed ticket #70")

        rows = crowley.list_activity_pulses(self.project_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], result["id"])

    def test_record_activity_pulse_rejects_invalid_verb_without_raising(self) -> None:
        self.assertIsNone(
            crowley.record_activity_pulse("cursor", "invalid_verb", project_id=self.project_id)
        )
        self.assertEqual(crowley.list_activity_pulses(self.project_id), [])

    def test_record_activity_pulse_never_raises_on_db_error(self) -> None:
        with mock.patch.object(crowley, "connect_db", side_effect=RuntimeError("db down")):
            self.assertIsNone(
                crowley.record_activity_pulse("cursor", "session_start", project_id=self.project_id)
            )

    def test_list_activity_pulses_respects_retrieval_window(self) -> None:
        fresh = crowley.record_activity_pulse(
            "codex",
            "minted",
            project_id=self.project_id,
            summary="Minted 3 tickets",
        )
        assert fresh is not None
        stale_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.conn.execute(
            """
            INSERT INTO activity_pulses (
                project_id, agent, verb, ticket_id, summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (self.project_id, "cursor", "handoff", 68, "Old handoff", stale_time),
        )
        self.conn.commit()

        rows = crowley.list_activity_pulses(self.project_id, window_minutes=45)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], fresh["id"])

    def test_post_activity_pulse_api_persists_valid_pulse(self) -> None:
        with TestClient(crowley_app.app) as client:
            response = client.post(
                "/api/activity/pulse",
                json={
                    "agent": "cursor",
                    "verb": "session_start",
                    "summary": "Cursor session opened",
                },
            )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["pulse"]["verb"], "session_start")
        self.assertEqual(len(crowley.list_activity_pulses(self.project_id)), 1)

    def test_post_activity_pulse_api_rejects_invalid_verb(self) -> None:
        with TestClient(crowley_app.app) as client:
            response = client.post(
                "/api/activity/pulse",
                json={"agent": "cursor", "verb": "not_a_verb"},
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
