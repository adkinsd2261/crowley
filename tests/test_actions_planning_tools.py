#!/usr/bin/env python3
"""V3.9.15 — planning and QA read tool tests."""

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
AUTH_HEADER = actions_headers(ACTIONS_KEY, session="planning-tools")


class PlanningToolTests(IsolatedDbTestCase):
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

    def test_agent_sync_chatgpt(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": "agent.sync", "args": {"agent": "chatgpt"}},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["agent"], "chatgpt")
        self.assertIn("tickets", body)
        self.assertIn("recent_handoffs", body)
        feed = body["recent_handoffs"]
        self.assertTrue(feed.get("auto_loaded"))
        self.assertIn("agent_behavior", body)
        behavior = body["agent_behavior"]
        self.assertIn("retrieval_policy", behavior)
        self.assertIn("pre_response_validation", body)

    def test_retrieval_policy_tools_exist_in_catalog(self) -> None:
        import actions_tool_registry as registry

        registry.ensure_registry()
        names = set(registry._TOOLS.keys())
        import agent_behavior

        for entry in agent_behavior.RETRIEVAL_POLICY:
            for tool in entry["tools"]:
                self.assertIn(str(tool), names, msg=f"missing catalog tool {tool}")

    def test_qa_bundle(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": "qa.bundle", "args": {}},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["version"], crowley.CROWLEY_VERSION)
        self.assertIn("hygiene", body)


if __name__ == "__main__":
    unittest.main()
