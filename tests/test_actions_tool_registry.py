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
        payload = registry.catalog_payload()
        names = {tool["name"] for tool in payload["tools"]}
        self.assertIn("context.get", names)
        self.assertIn("writeback.ingest", names)
        self.assertIn("gateway", payload)

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


if __name__ == "__main__":
    unittest.main()
