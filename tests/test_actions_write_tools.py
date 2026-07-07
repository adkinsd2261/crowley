#!/usr/bin/env python3
"""V3.9.15 — Codex-parity write tool tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
from actions_helpers import actions_headers, boot_actions_session  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ACTIONS_KEY = "test-secret"
AUTH_HEADER = actions_headers(ACTIONS_KEY, session="write-tools")


class WriteToolTests(IsolatedDbTestCase):
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

    def test_ticket_create_read_cancel(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            create = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={
                    "tool": "ticket.create",
                    "args": {
                        "title": "GPT Toolbelt write test ticket",
                        "description": "temp",
                        "assignee": "cursor",
                        "priority": 3,
                    },
                },
            )
            self.assertEqual(create.status_code, 201, create.text)
            ticket_id = create.json()["ticket"]["id"]
            read = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": "ticket.get", "args": {"id": ticket_id}},
            )
            self.assertEqual(read.status_code, 200)
            cancel = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={
                    "tool": "ticket.cancel",
                    "args": {"id": ticket_id, "comment": "test cleanup"},
                },
            )
        self.assertEqual(cancel.status_code, 200)

    def test_ticket_cancel_requires_comment(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={"tool": "ticket.cancel", "args": {"id": 1}},
            )
        self.assertEqual(res.status_code, 400)

    def test_writeback_ingest_auto_promotes_accepted_sparks(self) -> None:
        marker = "Actions auto-promotion retrieval visibility marker"
        payload = {
            "writeback": {
                "session": {
                    "summary": "Actions auto-promotion retrieval visibility test.",
                },
                "sparks": [
                    {
                        "content": f"{marker}: accepted staged portable sparks should be promoted to active when ingested via actions.writeback.ingest.",
                        "lane": "work",
                        "why_keep": "Ensures retrieve.search can surface newly accepted portable sparks without manual acceptance runs.",
                        "confidence": 0.95,
                        "sensitivity": "normal",
                    }
                ],
            }
        }
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={"tool": "writeback.ingest", "args": payload},
            )
        self.assertEqual(res.status_code, 201, res.text)
        body = res.json()
        self.assertEqual(body.get("status"), "ok")
        self.assertTrue(body.get("auto_promotion", {}).get("applied"))
        spark_ids = body.get("spark_ids") or []
        self.assertTrue(spark_ids)
        spark_id = int(spark_ids[0])

        import crowley

        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?",
                (spark_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row["status"]), "active")

        hits = crowley.retrieve_memories(marker, limit=20)
        hit_ids = {int(item["id"]) for item in hits}
        self.assertIn(spark_id, hit_ids)

    def test_writeback_ingest_rejects_handoff_shaped_args(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={
                    "tool": "writeback.ingest",
                    "args": {
                        "content": "Wrong shape for writeback ingest",
                        "type": "project_update",
                        "metadata": {"source": "chatgpt", "sensitivity": "normal"},
                    },
                },
            )
        self.assertEqual(res.status_code, 400, res.text)
        errors = res.json().get("errors") or []
        self.assertTrue(any("handoff.ingest" in str(item) for item in errors))

    def test_writeback_ingest_keeps_sensitive_sparks_staged(self) -> None:
        payload = {
            "writeback": {
                "session": {
                    "summary": "Sensitive spark should remain staged after actions ingest.",
                },
                "sparks": [
                    {
                        "content": "Sensitive portable spark must stay staged until manual review.",
                        "lane": "health",
                        "why_keep": "Protects high-sensitivity content from automatic promotion into retrieval.",
                        "confidence": 0.9,
                        "sensitivity": "sensitive",
                    }
                ],
            }
        }
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={"tool": "writeback.ingest", "args": payload},
            )
        self.assertEqual(res.status_code, 201, res.text)
        body = res.json()
        promotion = body.get("auto_promotion") or {}
        self.assertTrue(promotion.get("applied"))
        self.assertEqual(int(promotion.get("accepted", -1)), 0)

        import crowley

        spark_id = int(body["spark_ids"][0])
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?",
                (spark_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        self.assertEqual(str(row["status"]), "rejected")


if __name__ == "__main__":
    unittest.main()
