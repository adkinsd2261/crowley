#!/usr/bin/env python3
"""V3.9.17+ agent behavior layer tests (#123–#130)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_behavior  # noqa: E402
import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class AgentBehaviorUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        agent_behavior.reset_request_cycle("test-session")

    def test_system_query_requires_sync(self) -> None:
        ok, msg = agent_behavior.check_sync_for_system_query(
            "test-session",
            query_text="what tickets are open",
            tool_name="ticket.list",
        )
        self.assertFalse(ok)
        self.assertIn("sync_required", msg or "")

    def test_sync_dedup_within_cycle(self) -> None:
        agent_behavior.check_sync_for_system_query(
            "test-session", tool_name="agent.sync"
        )
        ok, msg = agent_behavior.check_sync_for_system_query(
            "test-session", tool_name="agent.sync"
        )
        self.assertTrue(ok)
        self.assertIn("sync_deduped", msg or "")

    def test_retrieval_policy_maps_intent(self) -> None:
        tools = agent_behavior.tools_for_intent("tickets")
        self.assertIn("ticket.list", tools)

    def test_pre_response_checklist(self) -> None:
        agent_behavior.record_tool_call("test-session", "agent.sync")
        agent_behavior.record_tool_call("test-session", "handoff.list")
        result = agent_behavior.validate_retrieval_state("test-session", intent="recent_work")
        self.assertTrue(result["checklist"][0]["passed"])
        self.assertTrue(result["checklist"][1]["passed"])


class AgentBehaviorIntegrationTests(IsolatedDbTestCase):
    def test_auto_handoff_feed(self) -> None:
        crowley.save_memory_item(
            "project_update",
            "Builder handoff feed probe for auto-load.",
            source="cursor",
            project_id=crowley._active_project_id(crowley.connect_db()),
            agent_id="cursor",
        )
        feed = agent_behavior.build_auto_handoff_feed(limit=8)
        self.assertTrue(feed["auto_loaded"])
        self.assertGreaterEqual(feed["total"], 1)

    def test_sync_bundle_includes_recent_handoffs(self) -> None:
        crowley.save_memory_item(
            "project_update",
            "Auto handoff feed sync bundle probe.",
            source="cursor",
            project_id=crowley._active_project_id(crowley.connect_db()),
            agent_id="cursor",
        )
        bundle = crowley.build_agent_sync_bundle("cursor")
        feed = bundle.get("recent_handoffs")
        self.assertIsInstance(feed, dict)
        assert isinstance(feed, dict)
        self.assertTrue(feed.get("auto_loaded"))
        self.assertGreaterEqual(int(feed.get("total", 0)), 1)

    def test_sync_bundle_includes_behavior(self) -> None:
        bundle = crowley.build_agent_sync_bundle("cursor")
        workflow = bundle.get("workflow") or {}
        if isinstance(workflow, dict):
            behavior = workflow.get("agent_behavior")
            if behavior is None:
                import workflow as wf

                payload = wf.workflow_enforcement_payload()
                behavior = payload.get("agent_behavior")
            self.assertIsNotNone(behavior)

    def test_chaining_depth_tracked(self) -> None:
        agent_behavior.reset_request_cycle("chain-test")
        agent_behavior.record_tool_call("chain-test", "agent.sync")
        agent_behavior.record_tool_call("chain-test", "ticket.list")
        agent_behavior.record_tool_call("chain-test", "ticket.get")
        obs = agent_behavior.retrieval_observability("chain-test")
        self.assertGreaterEqual(int(obs["chain_depth"]), 1)
        policy = agent_behavior.CHAINING_POLICY
        self.assertEqual(policy["max_chain_depth"], 3)

    def test_mandatory_retrieval_blocks_ready_state(self) -> None:
        agent_behavior.reset_request_cycle("mandatory-test")
        agent_behavior.record_tool_call("mandatory-test", "agent.sync")
        result = agent_behavior.validate_retrieval_state("mandatory-test", intent="tickets")
        self.assertFalse(result["ready"])
        self.assertTrue(result["missing_requirements"])

    def test_workflow_qa_crowley_context(self) -> None:
        import workflow

        schema = workflow.QA_PIPELINE_SCHEMA
        validation = schema.get("crowley_context_validation")
        self.assertIsInstance(validation, dict)
        assert isinstance(validation, dict)
        self.assertIn("recent handoffs", str(validation.get("required", [])))

    def test_observability_log(self) -> None:
        agent_behavior.reset_request_cycle("obs-test")
        agent_behavior.record_tool_call(
            "obs-test", "agent.sync", reason="boot", triggering_rule="sync"
        )
        agent_behavior.record_tool_call(
            "obs-test", "ticket.list", reason="tickets open", triggering_rule="domain_trigger"
        )
        obs = agent_behavior.retrieval_observability("obs-test")
        self.assertEqual(len(obs["log"]), 2)
        entry = obs["log"][-1]
        assert isinstance(entry, dict)
        self.assertIn("tool_called", entry)
        self.assertIn("triggering_rule", entry)
        self.assertIn("reason_for_call", entry)

    def test_domain_retrieval_gate_blocks_secondary_tool(self) -> None:
        agent_behavior.reset_request_cycle("domain-gate")
        agent_behavior.record_tool_call("domain-gate", "agent.sync")
        ok, msg, extra = agent_behavior.check_domain_retrieval_gate(
            "domain-gate",
            "qa.bundle",
            query_text="what tickets are open",
        )
        self.assertFalse(ok)
        self.assertIn("domain_retrieval_required", msg or "")
        self.assertIn("required_tools", extra)

    def test_pre_response_gate_blocks_write_when_not_ready(self) -> None:
        agent_behavior.reset_request_cycle("pre-gate")
        agent_behavior.record_tool_call("pre-gate", "agent.sync")
        ok, msg, extra = agent_behavior.check_pre_response_gate(
            "pre-gate",
            "note.ingest",
            query_text="what tickets are open",
            kind="write",
        )
        self.assertFalse(ok)
        self.assertIn("context_not_ready", msg or "")
        self.assertIn("retry_path", extra)

    def test_complex_query_requires_proactive_chain(self) -> None:
        agent_behavior.reset_request_cycle("complex")
        agent_behavior.record_tool_call("complex", "agent.sync")
        agent_behavior._note_query_context("complex", "audit system consistency")
        result = agent_behavior.validate_retrieval_state("complex", intent="system")
        self.assertFalse(result["ready"])
        self.assertTrue(result["missing_requirements"])


if __name__ == "__main__":
    unittest.main()
