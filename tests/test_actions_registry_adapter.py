#!/usr/bin/env python3
"""V4.1 — Actions registry adapter tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import actions_tool_registry as registry  # noqa: E402
import crowley_tools  # noqa: E402


class ActionsRegistryAdapterTests(unittest.TestCase):
    def test_registry_uses_shared_tool_contract(self) -> None:
        tools = registry.list_tools()
        self.assertGreater(len(tools), 40)
        for tool in tools:
            self.assertIsInstance(tool, crowley_tools.ToolDefinition)
            self.assertIsNotNone(tool.timeout_seconds)
            self.assertIsNotNone(tool.permission_tier)
            self.assertIsNotNone(tool.workflow_tier)
            self.assertIsNotNone(tool.mcp_exposure)

    def test_catalog_is_legacy_projection_of_shared_contract(self) -> None:
        payload = registry.catalog_payload()
        projected = [
            crowley_tools.actions_catalog_entry(tool, tier=tool.workflow_tier)
            for tool in registry.list_tools()
        ]
        self.assertEqual(projected, payload["tools"])
        for item in payload["tools"]:
            self.assertEqual(
                sorted(item.keys()),
                ["args_schema", "description", "kind", "name", "tier"],
            )

    def test_contract_preserves_runtime_timeout_metadata(self) -> None:
        payload = registry.catalog_payload()
        by_name = {tool.name: tool for tool in registry.list_tools()}
        self.assertEqual(
            payload["timeouts_seconds"],
            {name: tool.timeout_seconds for name, tool in by_name.items()},
        )
        self.assertEqual(by_name["writeback.ingest"].timeout_seconds, 90)
        self.assertEqual(by_name["agent.sync"].workflow_tier, "core")
        self.assertEqual(by_name["ticket.update"].permission_tier, "agent_write")


if __name__ == "__main__":
    unittest.main()
