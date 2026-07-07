#!/usr/bin/env python3
"""V3.9.15 — Actions tool registry unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import actions_tool_registry as registry  # noqa: E402


class ActionsToolRegistryTests(unittest.TestCase):
    def test_catalog_lists_v313_tools(self) -> None:
        import crowley

        payload = registry.catalog_payload()
        self.assertEqual(payload["version"], crowley.CROWLEY_VERSION)
        self.assertEqual(payload["catalog_schema"], "actions_tool_catalog_v1")
        names = {tool["name"] for tool in payload["tools"]}
        self.assertIn("context.get", names)
        self.assertIn("writeback.ingest", names)
        self.assertIn("gateway", payload)
        self.assertIn("examples", payload)
        self.assertIn("writeback.ingest", payload["examples"])
        self.assertIn("retrieve.search", payload["examples"])

    def test_sync_tool_catalog_matches_registry(self) -> None:
        catalog = registry.sync_tool_catalog_payload()
        full = registry.catalog_payload()
        self.assertEqual(catalog["tool_count"], len(full["tools"]))
        self.assertEqual(catalog["tools"], full["tools"])
        self.assertEqual(catalog["examples"], full["examples"])

    def test_agent_sync_includes_tool_catalog(self) -> None:
        body, status = registry.dispatch(
            "read",
            "agent.sync",
            {"agent": "chatgpt", "limit": 5},
        )
        self.assertEqual(status, 200)
        catalog = body.get("tool_catalog")
        self.assertIsInstance(catalog, dict)
        self.assertGreater(int(catalog.get("tool_count") or 0), 40)
        ticket_get = next(
            tool for tool in catalog["tools"] if tool["name"] == "ticket.get"
        )
        props = ticket_get["args_schema"].get("properties", {})
        self.assertIn("ticket_id", props)

    def test_unknown_tool_returns_error(self) -> None:
        body, status = registry.dispatch("read", "does.not.exist", {})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "unknown_tool")

    def test_wrong_gateway_rejected(self) -> None:
        body, status = registry.dispatch("write", "context.get", {})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "wrong_gateway")

    def test_missing_tool_name(self) -> None:
        body, status = registry.dispatch("read", "", {})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "tool_required")

    def test_invalid_args_type(self) -> None:
        body, status = registry.dispatch("read", "context.get", "bad")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_args")

    def test_retrieve_search_accepts_query_alias(self) -> None:
        registry.dispatch("read", "agent.sync", {"agent": "chatgpt", "limit": 3})
        body, status = registry.dispatch(
            "read",
            "retrieve.search",
            {"query": "crowley project", "limit": 3},
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(body.get("results"), list)
        self.assertEqual(body.get("hits"), body.get("results"))

    def test_ticket_get_accepts_ticket_id_alias(self) -> None:
        import tickets

        created = tickets.create_ticket(
            "Alias id probe ticket",
            source="chatgpt",
            actor="codex",
        )
        ticket_id = int(created["ticket"]["id"])
        registry.dispatch("read", "agent.sync", {"agent": "chatgpt", "limit": 3})
        body, status = registry.dispatch(
            "read",
            "ticket.get",
            {"ticket_id": ticket_id},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["ticket"]["id"], ticket_id)


if __name__ == "__main__":
    unittest.main()
