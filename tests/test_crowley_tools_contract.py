#!/usr/bin/env python3
"""V4.1 — transport-neutral tool contract tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import actions_tool_registry as registry  # noqa: E402
import crowley_tools  # noqa: E402
import workflow  # noqa: E402
from actions_tool_runtime import tool_timeout_seconds  # noqa: E402


def _contracts() -> list[crowley_tools.ToolDefinition]:
    return [
        crowley_tools.complete_tool_metadata(
            tool,
            timeout_seconds=tool_timeout_seconds(tool.name),
            workflow_tier=workflow.tool_tier(tool.name),
        )
        for tool in registry.list_tools()
    ]


class CrowleyToolsContractTests(unittest.TestCase):
    def test_contract_represents_every_actions_tool(self) -> None:
        registry_tools = registry.list_tools()
        contracts = _contracts()
        self.assertGreater(len(contracts), 40)
        self.assertEqual([tool.name for tool in registry_tools], [tool.name for tool in contracts])
        self.assertEqual([tool.kind for tool in registry_tools], [tool.kind for tool in contracts])
        for contract in contracts:
            self.assertIsNotNone(contract.timeout_seconds)
            self.assertIn(contract.permission_tier, {"read", "validation_write", "agent_write", "operator_write"})
            self.assertIn(contract.workflow_tier, {"core", "secondary"})
            self.assertIn(
                contract.mcp_exposure,
                {"mcp_safe", "mcp_conditional", "actions_only", "local_only", "blocked"},
            )
            self.assertEqual(contract.input_schema, contract.args_schema)

    def test_actions_catalog_projection_matches_current_payload(self) -> None:
        catalog = registry.catalog_payload()
        projected = [
            crowley_tools.actions_catalog_entry(
                contract,
                tier=workflow.tool_tier(contract.name),
            )
            for contract in _contracts()
        ]
        self.assertEqual(projected, catalog["tools"])
        self.assertEqual(
            {contract.name: contract.timeout_seconds for contract in _contracts()},
            catalog["timeouts_seconds"],
        )

    def test_actions_catalog_does_not_expose_mcp_metadata_yet(self) -> None:
        catalog = registry.catalog_payload()
        for tool in catalog["tools"]:
            self.assertNotIn("mcp_exposure", tool)
            self.assertNotIn("permission_tier", tool)
            self.assertNotIn("timeout_seconds", tool)
            self.assertIn("args_schema", tool)
            self.assertNotIn("input_schema", tool)

    def test_mcp_candidate_classification_is_conservative(self) -> None:
        tools = {tool.name: tool for tool in _contracts()}
        self.assertEqual(tools["context.get"].mcp_exposure, "mcp_safe")
        self.assertEqual(tools["cognitive.context"].mcp_exposure, "mcp_safe")
        self.assertEqual(tools["writeback.parse"].mcp_exposure, "mcp_safe")
        self.assertEqual(tools["writeback.ingest"].mcp_exposure, "mcp_conditional")
        self.assertEqual(tools["agent.sync"].mcp_exposure, "actions_only")
        self.assertEqual(tools["inspect.invariant_checks"].mcp_exposure, "local_only")
        self.assertEqual(tools["github.status"].mcp_exposure, "local_only")
        self.assertEqual(tools["audit.rollback"].mcp_exposure, "blocked")
        self.assertEqual(tools["audit.rollback"].permission_tier, "operator_write")


if __name__ == "__main__":
    unittest.main()
