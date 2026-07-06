#!/usr/bin/env python3
"""#165 — regression guards for pre_response_validation observability (#162)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_behavior  # noqa: E402
import actions_tool_registry  # noqa: E402
import workflow  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _checklist_map(result: dict[str, object]) -> dict[str, bool]:
    checklist = result.get("checklist", [])
    assert isinstance(checklist, list)
    return {
        str(item["item"]): bool(item.get("passed"))
        for item in checklist
        if isinstance(item, dict)
    }


class PreResponseValidationTests(unittest.TestCase):
    def test_sync_only_checklist_from_observability(self) -> None:
        agent_behavior.reset_request_cycle("pre-sync")
        agent_behavior.apply_agent_sync_completion("pre-sync")
        result = agent_behavior.validate_retrieval_state("pre-sync")
        items = _checklist_map(result)
        self.assertTrue(items["agent.sync executed"])
        self.assertTrue(items["recent handoffs loaded"])
        self.assertEqual(result.get("observability", {}).get("source"), "retrieval_log")
        self.assertGreaterEqual(int(result.get("observability", {}).get("log_entries", 0)), 1)

    def test_retrieval_sets_domain_checklist(self) -> None:
        agent_behavior.reset_request_cycle("pre-domain")
        agent_behavior.apply_agent_sync_completion("pre-domain")
        agent_behavior.record_tool_call("pre-domain", "ticket.list", reason="open tickets")
        result = agent_behavior.validate_retrieval_state("pre-domain", intent="tickets")
        items = _checklist_map(result)
        self.assertTrue(items["relevant domain data retrieved"])
        self.assertTrue(result.get("ready"))

    def test_mixed_flow_sync_plus_retrieval(self) -> None:
        agent_behavior.reset_request_cycle("pre-mixed")
        agent_behavior.record_tool_call("pre-mixed", "agent.sync", triggering_rule="sync")
        agent_behavior.record_tool_call("pre-mixed", "handoff.list", reason="recent work")
        agent_behavior.record_tool_call("pre-mixed", "github.status", reason="repo status")
        result = agent_behavior.validate_retrieval_state("pre-mixed", intent="code")
        items = _checklist_map(result)
        self.assertTrue(all(items.values()))
        self.assertTrue(result.get("ready"))

    def test_no_false_ready_without_sync(self) -> None:
        agent_behavior.reset_request_cycle("pre-empty")
        result = agent_behavior.validate_retrieval_state("pre-empty")
        items = _checklist_map(result)
        self.assertFalse(items["agent.sync executed"])
        self.assertFalse(result.get("ready"))

    def test_observed_tools_merge_log_and_state(self) -> None:
        agent_behavior.reset_request_cycle("pre-merge")
        agent_behavior.record_tool_call("pre-merge", "context.get", reason="memory")
        tools = agent_behavior._observed_tools("pre-merge")  # noqa: SLF001
        self.assertIn("context.get", tools)

    def test_dispatch_id_scoped_observability(self) -> None:
        agent_behavior.reset_request_cycle("pre-dispatch")
        agent_behavior.begin_dispatch("pre-dispatch", 7)
        agent_behavior.record_tool_call(
            "pre-dispatch",
            "agent.sync",
            triggering_rule="sync",
            dispatch_id=7,
        )
        result = agent_behavior.validate_retrieval_state("pre-dispatch", dispatch_id=7)
        obs = result.get("observability", {})
        assert isinstance(obs, dict)
        self.assertEqual(obs.get("dispatch_id"), 7)
        self.assertIn("agent.sync", obs.get("dispatch_tools_called", []))
        items = _checklist_map(result)
        self.assertTrue(items["agent.sync executed"])


class PreResponseActionsIntegrationTests(IsolatedDbTestCase):
    def test_agent_sync_response_validation_ready(self) -> None:
        session = "actions-sync-test"
        agent_behavior.reset_request_cycle(session)
        body, status = actions_tool_registry.dispatch(
            "read",
            "agent.sync",
            {"agent": "chatgpt", "session_key": session},
            session_key=session,
        )
        self.assertEqual(status, 200)
        validation = body.get("pre_response_validation")
        assert isinstance(validation, dict)
        items = _checklist_map(validation)
        self.assertTrue(items["agent.sync executed"])
        self.assertTrue(items["recent handoffs loaded"])
        obs = validation.get("observability", {})
        assert isinstance(obs, dict)
        self.assertEqual(body.get("dispatch_id"), obs.get("dispatch_id"))

    def test_api_agent_sync_runtime_wiring(self) -> None:
        import app as crowley_app
        from fastapi.testclient import TestClient

        session = "agent:cursor"
        agent_behavior.reset_request_cycle(session)
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/agent/sync", params={"agent": "cursor", "limit": 5})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        validation = body.get("pre_response_validation")
        assert isinstance(validation, dict)
        items = _checklist_map(validation)
        self.assertTrue(items["agent.sync executed"])
        self.assertTrue(items["recent handoffs loaded"])
        self.assertEqual(body.get("session_key"), session)
        self.assertIsNotNone(body.get("dispatch_id"))


if __name__ == "__main__":
    unittest.main()
