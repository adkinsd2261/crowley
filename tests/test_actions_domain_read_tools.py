#!/usr/bin/env python3
"""V3.9.15 — domain object read tool tests."""

from __future__ import annotations

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
AUTH_HEADER = actions_headers(ACTIONS_KEY, session="domain-read-tools")


class DomainReadToolTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._prior_key = os.environ.get("CROWLEY_ACTION_KEY")
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY
        self.memory_id = crowley.save_memory_item(
            "event",
            "Domain read tool test memory.",
            summary="test",
            source="manual",
            importance=3,
        )
        assert self.memory_id is not None

    def tearDown(self) -> None:
        if self._prior_key is None:
            os.environ.pop("CROWLEY_ACTION_KEY", None)
        else:
            os.environ["CROWLEY_ACTION_KEY"] = self._prior_key
        super().tearDown()

    def _read(self, tool: str, args: dict) -> dict:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": tool, "args": args},
            )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_memory_get_and_list(self) -> None:
        item = self._read("memory.get", {"id": self.memory_id})
        self.assertEqual(item["id"], self.memory_id)
        listed = self._read("memory.list", {"limit": 5})
        ids = {row["id"] for row in listed["items"]}
        self.assertIn(self.memory_id, ids)

    def test_memory_get_not_found(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": "memory.get", "args": {"id": 999999999}},
            )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"], "not_found")

    def test_ticket_list(self) -> None:
        listed = self._read("ticket.list", {"status": "open", "limit": 5})
        self.assertIn("items", listed)
        self.assertIn("total", listed)

    def test_ticket_create_list_newest_and_get_alias(self) -> None:
        import tickets

        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            create = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={
                    "tool": "ticket.create",
                    "args": {
                        "title": "Actions newest-sort probe",
                        "assignee": "cursor",
                        "priority": 4,
                    },
                },
            )
        self.assertEqual(create.status_code, 201, create.text)
        ticket_id = int(create.json()["ticket"]["id"])
        got = self._read("ticket.get", {"ticket_id": ticket_id})
        self.assertEqual(got["ticket"]["id"], ticket_id)
        listed = self._read("ticket.list", {"status": "open", "limit": 5})
        self.assertEqual(listed["items"][0]["id"], ticket_id)


if __name__ == "__main__":
    unittest.main()
