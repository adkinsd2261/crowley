#!/usr/bin/env python3
"""V3.9.15 — inspect and writeback observability tool tests."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import crowley  # noqa: E402
from actions_helpers import actions_headers, boot_actions_session  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ACTIONS_KEY = "test-secret"
AUTH_HEADER = actions_headers(ACTIONS_KEY, session="inspect-tools")
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class InspectToolTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._prior_key = os.environ.get("CROWLEY_ACTION_KEY")
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY

    def tearDown(self) -> None:
        if self._prior_key is None:
            os.environ.pop("CROWLEY_ACTION_KEY", None)
        else:
            os.environ["CROWLEY_ACTION_KEY"] = self._prior_key
        super().tearDown()

    def test_ingest_then_inspect_round_trip(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            ingest = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={"tool": "writeback.ingest", "args": {"writeback": payload}},
            )
            self.assertEqual(ingest.status_code, 201, ingest.text)
            body = ingest.json()
            self.assertIn("sparks", body)
            self.assertIn("session_receipt", body)
            session_id = body["session_receipt_id"]
            inspect = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={
                    "tool": "inspect.writeback_result",
                    "args": {"session_receipt_id": session_id},
                },
            )
        self.assertEqual(inspect.status_code, 200)
        detail = inspect.json()
        self.assertEqual(detail["session_receipt_id"], session_id)
        self.assertIn("evaluations", detail)

    def test_retrieval_observability_after_reads(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": "ticket.list", "args": {}},
            )
            inspect = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={
                    "tool": "inspect.retrieval_observability",
                    "args": {"intent": "tickets"},
                },
            )
        self.assertEqual(inspect.status_code, 200)
        detail = inspect.json()
        self.assertIn("log", detail)
        self.assertTrue(detail.get("tools_called"))
        self.assertIn("validation", detail)
        self.assertIn("recommended_tools", detail)


if __name__ == "__main__":
    unittest.main()
