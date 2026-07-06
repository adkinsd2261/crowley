"""#177–#184 — handoff↔ticket parity hardening regression guards."""

from __future__ import annotations

import unittest
from unittest import mock

import agent_behavior
import handoff_ticket_bridge
import system_integrity


class HandoffParityHardeningTests(unittest.TestCase):
    def test_dispatch_enforces_handoff_ticket_parity(self) -> None:
        session = "parity-dispatch"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
        invariant = {
            "context": "dispatch",
            "ok": False,
            "violations": [
                {
                    "invariant": "handoff_ticket_parity",
                    "severity": "error",
                    "missing_count": 1,
                }
            ],
        }
        with mock.patch.object(system_integrity, "run_invariant_checks", return_value=invariant):
            ok, code, _, extra = system_integrity.run_enforcement_gates(
                session,
                "spark.list",
                query_text="status",
                kind="read",
                boot_allowed=True,
            )
        self.assertFalse(ok)
        self.assertEqual(code, "invariant_violation")
        violations = extra.get("invariant_checks", {}).get("violations") or []
        ids = [v.get("invariant") for v in violations if isinstance(v, dict)]
        self.assertIn("handoff_ticket_parity", ids)

    def test_pre_response_gate_blocks_non_retrieval_when_not_ready(self) -> None:
        session = "qa-dispatch"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
        ok, msg, extra = agent_behavior.check_pre_response_gate(
            session,
            "note.ingest",
            query_text="what tickets are open",
            kind="write",
        )
        self.assertFalse(ok)
        self.assertIn("context_not_ready", msg or "")
        validation = extra.get("pre_response_validation") or {}
        self.assertFalse(validation.get("ready"))


if __name__ == "__main__":
    unittest.main()
