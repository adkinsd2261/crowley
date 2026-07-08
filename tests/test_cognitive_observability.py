#!/usr/bin/env python3
"""V4 T22 — cognitive observability and invariant tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_behavior  # noqa: E402
import app as crowley_app  # noqa: E402
import cognitive_ingest  # noqa: E402
import observability_store  # noqa: E402
import system_integrity  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


SESSION_KEY = crowley_app.COGNITIVE_API_OBSERVABILITY_SESSION


class CognitiveObservabilityTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        agent_behavior.reset_request_cycle(SESSION_KEY)
        system_integrity._cognitive_ingest_timestamps.clear()  # noqa: SLF001

    def tearDown(self) -> None:
        system_integrity._cognitive_ingest_timestamps.clear()  # noqa: SLF001
        super().tearDown()

    def _tools(self) -> list[str]:
        return [
            str(entry.get("tool_called"))
            for entry in observability_store.get_observability_logs(SESSION_KEY, limit=20)
        ]

    def test_cognitive_ingest_logged_to_observability_chain(self) -> None:
        client = TestClient(crowley_app.app)
        with mock.patch.object(
            cognitive_ingest,
            "ingest_cognitive_content",
            return_value={
                "status": "accepted",
                "memory_item_id": 1,
                "extraction": {"status": "queued"},
            },
        ):
            res = client.post(
                "/api/cognitive/ingest",
                json={"content": "Observability records cognitive ingest.", "source": "manual"},
            )
        self.assertEqual(res.status_code, 201, res.text)
        self.assertIn("cognitive.ingest", self._tools())
        self.assertTrue(observability_store.verify_observability_chain(SESSION_KEY)["ok"])

    def test_cognitive_context_and_maintenance_logged(self) -> None:
        client = TestClient(crowley_app.app)
        context = client.get("/api/cognitive/context", params={"q": "observability"})
        maintenance = client.post("/api/cognitive/maintenance", json={"dry_run": True})
        self.assertEqual(context.status_code, 200, context.text)
        self.assertEqual(maintenance.status_code, 200, maintenance.text)

        tools = self._tools()
        self.assertIn("cognitive.context", tools)
        self.assertIn("cognitive.maintenance", tools)
        self.assertTrue(observability_store.verify_observability_chain(SESSION_KEY)["ok"])

    def test_cognitive_dispatch_blocked_on_invariant_violation(self) -> None:
        client = TestClient(crowley_app.app)
        broken = {
            "context": "dispatch",
            "ok": False,
            "violations": [{"invariant": "handoff_ticket_parity", "severity": "error"}],
        }
        with mock.patch.object(system_integrity, "run_invariant_checks", return_value=broken):
            res = client.get("/api/cognitive/context", params={"q": "blocked"})
        self.assertEqual(res.status_code, 428)
        self.assertEqual(res.json().get("error"), "invariant_violation")


if __name__ == "__main__":
    unittest.main()
