#!/usr/bin/env python3
"""#171–#176 — observability persistence, invariants, planner, claims."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_behavior  # noqa: E402
import claim_validation  # noqa: E402
import crowley  # noqa: E402
import observability_store  # noqa: E402
import system_integrity  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class ObservabilityPersistenceTests(IsolatedDbTestCase):
    def test_logs_persist_across_memory_reset(self) -> None:
        session = "obs-persist-test"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
        persisted = observability_store.get_observability_logs(session, limit=5)
        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted[0].get("tool_called"), "agent.sync")
        agent_behavior.record_tool_call(session, "ticket.list", reason="tickets")
        logs = observability_store.get_observability_logs(session, limit=10)
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[-1].get("tool_called"), "ticket.list")

    def test_session_state_persists_tools_called(self) -> None:
        session = "session-persist-test"
        agent_behavior.reset_request_cycle(session)
        with mock.patch.object(agent_behavior, "_session_persist_enabled", return_value=True):
            agent_behavior.record_tool_call(session, "context.get", reason="memory")
            agent_behavior._session_state.pop(session, None)  # noqa: SLF001
            reloaded = agent_behavior._get_state(session)  # noqa: SLF001
        tools = list(reloaded.get("tools_called", []))
        self.assertIn("context.get", tools)


class IntegrityDispatchTests(unittest.TestCase):
    def test_dispatch_blocks_invariant_error(self) -> None:
        session = "invariant-block"
        agent_behavior.reset_request_cycle(session)
        state = agent_behavior._get_state(session)  # noqa: SLF001
        state["tools_called"] = ["agent.sync", "ticket.list", "github.status"]
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
        ok, code, status, extra = system_integrity.run_enforcement_gates(
            session,
            "ticket.list",
            query_text="what tickets are open",
            kind="read",
            boot_allowed=True,
        )
        self.assertFalse(ok)
        self.assertEqual(code, "invariant_violation")
        self.assertEqual(status, 428)
        self.assertTrue(extra.get("violations"))

    def test_dispatch_allows_warning_only(self) -> None:
        session = "invariant-warn"
        agent_behavior.reset_request_cycle(session)
        warning = {
            "context": "dispatch",
            "ok": False,
            "violations": [
                {"invariant": "context_before_response", "severity": "warning"}
            ],
        }
        with mock.patch.object(system_integrity, "run_invariant_checks", return_value=warning):
            ok, code, _, _ = system_integrity.run_enforcement_gates(
                session,
                "agent.sync",
                kind="read",
                boot_allowed=True,
            )
        self.assertTrue(ok)
        self.assertIsNone(code)


class PlannerBatchTests(unittest.TestCase):
    def test_fallback_retrieval_plan_injects_tools(self) -> None:
        plan = system_integrity.apply_fallback_retrieval_plan(
            {"domains": [], "required_tools": [], "tool_order": []},
            "what is the system status and version",
        )
        self.assertTrue(plan.get("fallback_retrieval"))
        self.assertIn("context.get", plan.get("required_tools", []))

    def test_planner_refinement_retries_once(self) -> None:
        session = "planner-refine"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
        with mock.patch.object(
            system_integrity,
            "retrieval_planner",
            side_effect=[
                {
                    "domains": ["tickets"],
                    "required_tools": ["ticket.list"],
                    "tool_order": ["agent.sync", "ticket.list"],
                    "query": "open tickets",
                },
                {
                    "domains": ["tickets", "memory"],
                    "required_tools": ["ticket.list", "context.get"],
                    "tool_order": ["agent.sync", "ticket.list", "context.get"],
                    "query": "open tickets",
                },
            ],
        ):
            ok, code, _, extra = system_integrity.run_enforcement_gates(
                session,
                "spark.list",
                query_text="open tickets",
                kind="read",
                boot_allowed=True,
            )
        self.assertFalse(ok)
        self.assertEqual(code, "domain_retrieval_required")
        self.assertEqual(extra.get("planner_refinement_attempt"), 1)


class ClaimValidationTests(IsolatedDbTestCase):
    def test_conflicting_constraints_mark_contested(self) -> None:
        conn = crowley.connect_db()
        project_id = crowley._active_project_id(conn)
        assert project_id is not None
        first = crowley.save_memory_item(
            "constraint",
            "Always restart bus after version bumps",
            source="cursor",
            project_id=project_id,
        )
        assert first is not None
        second = crowley.save_memory_item(
            "constraint",
            "Never restart bus after version bumps",
            source="codex",
            project_id=project_id,
        )
        assert second is not None
        row = conn.execute(
            "SELECT metadata_json FROM memory_items WHERE id = ?",
            (int(second),),
        ).fetchone()
        conn.close()
        assert row is not None
        import json

        meta = json.loads(str(row["metadata_json"] or "{}"))
        self.assertEqual(meta.get("claim_status"), "contested")


if __name__ == "__main__":
    unittest.main()
