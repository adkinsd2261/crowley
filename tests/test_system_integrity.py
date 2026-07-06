#!/usr/bin/env python3
"""V3.9.18 patch — system integrity hardening tests (#143–#149)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_behavior  # noqa: E402
import conflict_engine  # noqa: E402
import crowley  # noqa: E402
import memory_tiers  # noqa: E402
import system_integrity  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class SystemIntegrityUnitTests(unittest.TestCase):
    def test_invariant_registry(self) -> None:
        ids = {inv["id"] for inv in system_integrity.INVARIANT_REGISTRY}
        self.assertIn("handoff_ticket_parity", ids)
        self.assertIn("no_conflicting_canonical", ids)

    def test_plan_retrieval_domains_complex(self) -> None:
        plan = system_integrity.plan_retrieval_domains("audit system consistency across repo")
        self.assertTrue(plan.get("domains"))
        self.assertTrue(plan.get("required_tools"))
        self.assertTrue(plan.get("tool_order"))
        self.assertTrue(plan.get("complex"))

    def test_retrieval_planner_execution_plan(self) -> None:
        plan = system_integrity.retrieval_planner("what tickets are open")
        self.assertIn("tickets", plan.get("domains", []))
        self.assertIn("agent.sync", plan.get("tool_order", []))
        self.assertIn("ticket.list", plan.get("required_tools", []))

    def test_planner_cached_per_request_cycle(self) -> None:
        agent_behavior.reset_request_cycle("planner-cache")
        plan1, fresh1 = system_integrity._get_or_run_planner("planner-cache", "what tickets are open")
        plan2, fresh2 = system_integrity._get_or_run_planner("planner-cache", "what tickets are open")
        self.assertTrue(fresh1)
        self.assertFalse(fresh2)
        self.assertEqual(plan1, plan2)

    def test_gates_emit_planner_observability(self) -> None:
        agent_behavior.reset_request_cycle("planner-obs")
        _, _, _, extra = system_integrity.run_enforcement_gates(
            "planner-obs",
            "agent.sync",
            query_text="what tickets are open",
        )
        self.assertTrue(extra.get("planner_called_before_gates"))
        self.assertTrue(extra.get("gates_use_planner_output"))
        self.assertIn("domains", extra.get("planner_output", {}))

    def test_retrieval_tools_not_blocked_before_reads(self) -> None:
        agent_behavior.reset_request_cycle("ret-pass")
        system_integrity.run_enforcement_gates(
            "ret-pass",
            "agent.sync",
            query_text="what tickets are open",
        )
        ok, code, _, _ = system_integrity.run_enforcement_gates(
            "ret-pass",
            "ticket.list",
            query_text="what tickets are open",
        )
        self.assertTrue(ok)
        self.assertIsNone(code)

    def test_multi_domain_retrieval_single_pass(self) -> None:
        agent_behavior.reset_request_cycle("multi-pass")
        query = "audit system consistency across repo"
        system_integrity.run_enforcement_gates("multi-pass", "agent.sync", query_text=query)
        for tool in ("handoff.list", "github.status", "context.get"):
            ok, code, _, _ = system_integrity.run_enforcement_gates(
                "multi-pass",
                tool,
                query_text=query,
            )
            self.assertTrue(ok, f"{tool} blocked: {code}")

    def test_non_retrieval_blocked_until_plan_satisfied(self) -> None:
        agent_behavior.reset_request_cycle("block-plan")
        system_integrity.run_enforcement_gates(
            "block-plan",
            "agent.sync",
            query_text="what tickets are open",
        )
        ok, code, _, extra = system_integrity.run_enforcement_gates(
            "block-plan",
            "spark.list",
            query_text="what tickets are open",
        )
        self.assertFalse(ok)
        self.assertEqual(code, "domain_retrieval_required")
        self.assertTrue(extra.get("gates_use_planner_output"))
        self.assertEqual(extra.get("triggering_rule"), "execution_plan")

    def test_ambiguous_query_no_domain_block(self) -> None:
        agent_behavior.reset_request_cycle("ambiguous")
        agent_behavior.record_tool_call("ambiguous", "agent.sync")
        ok, code, _, extra = system_integrity.run_enforcement_gates(
            "ambiguous",
            "context.get",
            query_text="hello there",
        )
        self.assertTrue(ok)
        self.assertTrue(extra.get("gates_use_planner_output"))
        self.assertEqual(extra.get("planner_output", {}).get("domains"), [])

    def test_idempotent_sync_recall(self) -> None:
        agent_behavior.reset_request_cycle("idem-sync")
        system_integrity.run_enforcement_gates(
            "idem-sync",
            "agent.sync",
            query_text="what tickets are open",
        )
        ok, code, _, _ = system_integrity.run_enforcement_gates(
            "idem-sync",
            "agent.sync",
            query_text="what tickets are open",
        )
        self.assertTrue(ok)
        self.assertIsNone(code)

    def test_gate_order(self) -> None:
        gates = [g["gate"] for g in system_integrity.GATE_ORDER]
        self.assertEqual(gates[:3], ["boot", "sync", "domain_plan"])

    def test_can_auto_resolve_blocks_low_confidence(self) -> None:
        ok, reason = system_integrity.can_auto_resolve_conflict(
            0.5, 0.9, left_tier="working", right_tier="working"
        )
        self.assertFalse(ok)
        self.assertIn("escalate", reason)

    def test_can_auto_resolve_blocks_dual_canonical(self) -> None:
        ok, reason = system_integrity.can_auto_resolve_conflict(
            0.95, 0.95, left_tier="canonical", right_tier="canonical"
        )
        self.assertFalse(ok)

    def test_automation_guardrails_rate_limit(self) -> None:
        system_integrity._write_timestamps.clear()
        for _ in range(system_integrity.WRITE_RATE_LIMIT_PER_MINUTE):
            ok, _, _ = system_integrity.check_automation_guardrails("cursor", "ticket.create")
            self.assertTrue(ok)
        ok, msg, _ = system_integrity.check_automation_guardrails("cursor", "ticket.create")
        self.assertFalse(ok)
        self.assertIn("rate limit", msg or "")

    def test_dispatch_observability_bound(self) -> None:
        agent_behavior.reset_request_cycle("obs-bind")
        entry = system_integrity.record_dispatch_observability(
            "obs-bind",
            "agent.sync",
            dispatch_id=42,
            http_status=200,
        )
        self.assertTrue(entry.get("bound_to_dispatch"))
        self.assertEqual(entry.get("dispatch_id"), 42)
        obs = agent_behavior.retrieval_observability("obs-bind")
        log_entry = obs["log"][-1]
        assert isinstance(log_entry, dict)
        self.assertEqual(log_entry.get("dispatch_id"), 42)

    def test_run_enforcement_gates_retrieval_allowed(self) -> None:
        agent_behavior.reset_request_cycle("gate-test")
        system_integrity.run_enforcement_gates(
            "gate-test",
            "agent.sync",
            kind="read",
            boot_allowed=True,
        )
        ok, code, status, _ = system_integrity.run_enforcement_gates(
            "gate-test",
            "ticket.list",
            query_text="what tickets are open",
            kind="read",
            boot_allowed=True,
        )
        self.assertTrue(ok)
        self.assertIsNone(code)


class SystemIntegrityIntegrationTests(IsolatedDbTestCase):
    def test_conflict_resolve_blocks_low_confidence(self) -> None:
        conn = crowley.connect_db()
        project_id = crowley._active_project_id(conn)
        assert project_id is not None
        id_a = crowley.save_memory_item(
            "decision",
            "Cache layer uses redis for all session storage",
            source="cursor",
            project_id=project_id,
            confidence=0.95,
        )
        id_b = crowley.save_memory_item(
            "decision",
            "Cache layer uses memory for all session storage",
            source="chatgpt",
            project_id=project_id,
            confidence=0.5,
        )
        assert id_a is not None and id_b is not None
        conflicts = conflict_engine.detect_memory_conflicts(project_id=project_id)
        self.assertTrue(conflicts)
        with self.assertRaises(ValueError) as ctx:
            conflict_engine.resolve_memory_conflict(
                int(conflicts[0]["id"]),
                agent_id="codex",
            )
        self.assertIn("escalate", str(ctx.exception).lower())

    def test_run_invariant_checks_returns_structure(self) -> None:
        result = system_integrity.run_invariant_checks("sync")
        self.assertIn("ok", result)
        self.assertIn("violations", result)


if __name__ == "__main__":
    unittest.main()
