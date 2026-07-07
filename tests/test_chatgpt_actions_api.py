#!/usr/bin/env python3
"""V3.9.13 — ChatGPT Actions API auth and route tests."""

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
AUTH_HEADER = actions_headers(ACTIONS_KEY, session="chatgpt-actions-api")
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ChatGptActionsAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prior_key = os.environ.get("CROWLEY_ACTION_KEY")
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY

    def tearDown(self) -> None:
        if self._prior_key is None:
            os.environ.pop("CROWLEY_ACTION_KEY", None)
        else:
            os.environ["CROWLEY_ACTION_KEY"] = self._prior_key

    def test_unauthorized_actions_request_fails(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/actions/health")
        self.assertEqual(res.status_code, 401)
        detail = res.json()["detail"]
        self.assertEqual(detail["error"], "authorization_required")

    def test_wrong_token_fails(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get(
                "/api/actions/health",
                headers={"Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"]["error"], "invalid_token")

    def test_wrong_scheme_fails(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get(
                "/api/actions/health",
                headers={"Authorization": f"Basic {ACTIONS_KEY}"},
            )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["detail"]["error"], "invalid_token")

    def test_x_api_key_header_succeeds(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get(
                "/api/actions/health",
                headers={"X-API-Key": ACTIONS_KEY},
            )
        self.assertEqual(res.status_code, 200)

    def test_raw_authorization_token_succeeds(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get(
                "/api/actions/health",
                headers={"Authorization": ACTIONS_KEY},
            )
        self.assertEqual(res.status_code, 200)

    def test_actions_disabled_when_key_missing(self) -> None:
        os.environ.pop("CROWLEY_ACTION_KEY", None)
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/actions/health", headers=AUTH_HEADER)
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["detail"]["error"], "actions_api_disabled")

    def test_public_health_unchanged_without_auth(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["version"], crowley.CROWLEY_VERSION)

    def test_non_actions_portable_route_unchanged_without_auth(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/portable/packet?surface=chatgpt")
        self.assertEqual(res.status_code, 200)
        self.assertIn("markdown", res.json())


class ChatGptActionsAuthorizedTests(IsolatedDbTestCase):
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

    def test_authorized_health_succeeds(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/actions/health", headers=AUTH_HEADER)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["version"], crowley.CROWLEY_VERSION)
        self.assertEqual(body["actions_api"], "enabled")
        self.assertEqual(body["auth"], "bearer")
        self.assertIn("runtime", body)
        self.assertNotIn("token", json.dumps(body).lower())

    def test_authorized_context_succeeds(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get(
                "/api/actions/context",
                headers=AUTH_HEADER,
                params={"q": "current project state", "limit": 3},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("state", body)
        self.assertIn("project", body)

    def test_authorized_retrieve_succeeds(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.get(
                "/api/actions/retrieve",
                headers=AUTH_HEADER,
                params={"q": "current project state", "limit": 5},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("results", body)

    def test_authorized_portable_packet_succeeds(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/actions/portable/packet", headers=AUTH_HEADER)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["packet"]["surface"], "chatgpt")
        self.assertIn("markdown", body)

    def test_authorized_writeback_parse_succeeds(self) -> None:
        payload = {
            "writeback": {
                "session": {
                    "summary": "Test ChatGPT Actions parse.",
                    "surface": "chatgpt",
                    "model": "test",
                },
                "sparks": [],
            }
        }
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/writeback/parse",
                headers=AUTH_HEADER,
                json=payload,
            )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])

    def test_authorized_writeback_parse_matches_fixture(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/writeback/parse",
                headers=AUTH_HEADER,
                json={"writeback": payload},
            )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])

    def test_gateway_read_context_matches_legacy(self) -> None:
        with TestClient(crowley_app.app) as client:
            legacy = client.get(
                "/api/actions/context",
                headers=AUTH_HEADER,
                params={"q": "current project state", "limit": 3},
            )
            gateway = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={
                    "tool": "context.get",
                    "args": {"q": "current project state", "limit": 3},
                },
            )
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(gateway.status_code, 200)
        self.assertEqual(gateway.json()["state"], legacy.json()["state"])

    def test_gateway_write_parse_matches_legacy(self) -> None:
        payload = {
            "writeback": {
                "session": {
                    "summary": "Gateway parse test.",
                    "surface": "chatgpt",
                    "model": "test",
                },
                "sparks": [],
            }
        }
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            legacy = client.post(
                "/api/actions/writeback/parse",
                headers=AUTH_HEADER,
                json=payload,
            )
            gateway = client.post(
                "/api/actions/write",
                headers=AUTH_HEADER,
                json={"tool": "writeback.parse", "args": payload},
            )
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(gateway.status_code, 200)
        self.assertEqual(gateway.json()["ok"], legacy.json()["ok"])

    def test_catalog_requires_auth(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/actions/catalog")
        self.assertEqual(res.status_code, 401)

    def test_catalog_lists_tools(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/actions/catalog", headers=AUTH_HEADER)
        self.assertEqual(res.status_code, 200)
        names = {tool["name"] for tool in res.json()["tools"]}
        self.assertIn("context.get", names)
        self.assertIn("writeback.ingest", names)

    def test_gateway_unknown_tool(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": "missing.tool", "args": {}},
            )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"], "unknown_tool")

    def test_alias_agent_sync_route_available(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get(
                "/api/actions/agent/sync",
                headers=AUTH_HEADER,
                params={"agent": "chatgpt", "limit": 5},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body.get("agent"), "chatgpt")
        self.assertIn("sync_meta", body)

    def test_alias_agent_deep_sync_route_available(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.get(
                "/api/actions/agent/deep_sync",
                headers=AUTH_HEADER,
                params={"agent": "chatgpt", "section": "tickets", "limit": 5},
            )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body.get("section"), "tickets")
        self.assertIn("items", body)

    def test_alias_github_status_route_available(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.get("/api/actions/github/status", headers=AUTH_HEADER)
        self.assertIn(res.status_code, {200, 503})

    def test_alias_github_file_route_available(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.get(
                "/api/actions/github/file",
                headers=AUTH_HEADER,
                params={"path": "README.md"},
            )
        self.assertIn(res.status_code, {200, 503})

    def test_alias_github_search_code_route_available(self) -> None:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.get(
                "/api/actions/github/search_code",
                headers=AUTH_HEADER,
                params={"q": "agent.sync"},
            )
        self.assertIn(res.status_code, {200, 503})


if __name__ == "__main__":
    unittest.main()
