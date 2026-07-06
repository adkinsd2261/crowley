#!/usr/bin/env python3
"""Security hardening verification suite (#197–#200).

These tickets are adversarial verification tests, not feature work: they prove
the existing dispatch/observability/invariant pipeline cannot be bypassed or
silently corrupted. No production behavior is added here — the guarantees are
already enforced by run_enforcement_gates + _check_observability_truth (with the
direct-entrypoint gate added in #196 and the cold-memory fix in the ChatGPT
hotfix). Each test would fail if a future change regressed those guarantees.

Coverage map (#199 — externally reachable surface is the Cloudflare tunnel,
which exposes only ^/api/actions/.* per cloudflared/config.yml):

    POST /api/actions/read   ─┐
    POST /api/actions/write  ─┤─► registry.dispatch ─► run_enforcement_gates
    GET  /api/actions/* alias ┘        (boot→sync→plan→retrieval→pre_response
                                        →guardrails→dispatch invariant check)
    GET  /api/agent/sync      ──► attach_agent_sync_runtime → run_invariant_checks
    POST /api/ingest          ─┐
    POST /api/portable/       ─┤─► system_integrity.enforce_dispatch_invariants (#196)
         writeback/ingest      ┘
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_behavior  # noqa: E402
import crowley  # noqa: E402
import observability_store  # noqa: E402
import system_integrity  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _record(session: str, *tools: str) -> None:
    for tool in tools:
        rule = "sync" if tool == "agent.sync" else "domain_trigger"
        agent_behavior.record_tool_call(session, tool, reason="probe", triggering_rule=rule)


def _delete_db_tool(session: str, tool: str) -> None:
    conn = crowley.connect_db()
    try:
        row = conn.execute(
            "SELECT id FROM observability_logs WHERE session_key=? AND tool_called=? ORDER BY id",
            (session, tool),
        ).fetchone()
        if row is not None:
            conn.execute("DELETE FROM observability_logs WHERE id=?", (int(row["id"]),))
            conn.commit()
    finally:
        conn.close()


class DbObservabilityIntegrityTests(IsolatedDbTestCase):
    """#197 — DB-backed observability cannot be silently corrupted."""

    def test_tampered_removed_row_is_detected(self) -> None:
        session = "sec-tamper-remove"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync", "ticket.list", "context.get")
        # Sanity: all three landed in the DB log.
        self.assertEqual(
            [e.get("tool_called") for e in observability_store.get_observability_logs(session, limit=20)],
            ["agent.sync", "ticket.list", "context.get"],
        )
        _delete_db_tool(session, "ticket.list")
        violation = system_integrity._check_observability_truth(session, check_db=True)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.get("mismatch"), "memory_vs_db")

    def test_partial_write_state_ahead_of_all_sinks_is_detected(self) -> None:
        # Tool executed (state updated) but the log write never landed anywhere.
        session = "sec-partial-write"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync")
        state = agent_behavior._get_state(session)
        state["tools_called"] = list(state.get("tools_called", [])) + ["ticket.create"]
        with mock.patch.object(
            observability_store,
            "get_observability_logs",
            return_value=[{"tool_called": "agent.sync"}],
        ):
            violation = system_integrity._check_observability_truth(session, check_db=True)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.get("mismatch"), "state_not_observed")

    def test_delayed_write_snapshot_does_not_false_pass(self) -> None:
        # Simulate a delayed/absent DB write: the row is not yet visible. The
        # invariant must NOT pass by reading a stale/empty snapshot — memory has
        # the tool, DB does not, so divergence is surfaced.
        session = "sec-delayed-write"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync", "ticket.list")
        with mock.patch.object(
            observability_store,
            "get_observability_logs",
            return_value=[{"tool_called": "agent.sync"}],
        ):
            violation = system_integrity._check_observability_truth(session, check_db=True)
        self.assertIsNotNone(violation)
        self.assertEqual(violation.get("mismatch"), "memory_vs_db")

    def test_get_observability_logs_reads_committed_snapshot(self) -> None:
        # #197 delay clause: reads open a fresh connection, so each call reflects
        # the committed point-in-time state (no cross-call cache that could hide
        # a corruption between execution and check).
        session = "sec-snapshot"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync")
        first = observability_store.get_observability_logs(session, limit=20)
        _record(session, "ticket.list")
        second = observability_store.get_observability_logs(session, limit=20)
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 2)


class ObservabilityChainTests(IsolatedDbTestCase):
    """#201 — per-session hash chain makes log tampering detectable."""

    def test_intact_chain_verifies(self) -> None:
        session = "sec-chain-ok"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync", "ticket.list", "context.get")
        report = observability_store.verify_observability_chain(session)
        self.assertTrue(report["ok"])
        self.assertEqual(report["checked"], 3)

    def test_deleted_row_breaks_chain(self) -> None:
        session = "sec-chain-delete"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync", "ticket.list", "context.get")
        _delete_db_tool(session, "ticket.list")
        report = observability_store.verify_observability_chain(session)
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "prev_hash_mismatch")

    def test_altered_tool_column_breaks_chain(self) -> None:
        session = "sec-chain-alter"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync", "ticket.list")
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT id FROM observability_logs WHERE session_key=? AND tool_called='ticket.list'",
                (session,),
            ).fetchone()
            conn.execute(
                "UPDATE observability_logs SET tool_called='memory.wipe' WHERE id=?",
                (int(row["id"]),),
            )
            conn.commit()
        finally:
            conn.close()
        report = observability_store.verify_observability_chain(session)
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "hash_mismatch")

    def test_entry_json_only_edit_is_detected(self) -> None:
        # Editing the tool inside entry_json but not the hashed column must still
        # be caught (the reader trusts entry_json for tool identity).
        session = "sec-chain-json"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync", "ticket.list")
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT id, entry_json FROM observability_logs "
                "WHERE session_key=? AND tool_called='ticket.list'",
                (session,),
            ).fetchone()
            import json as _json

            payload = _json.loads(row["entry_json"])
            payload["tool_called"] = "memory.wipe"
            payload["tool"] = "memory.wipe"
            conn.execute(
                "UPDATE observability_logs SET entry_json=? WHERE id=?",
                (_json.dumps(payload), int(row["id"])),
            )
            conn.commit()
        finally:
            conn.close()
        report = observability_store.verify_observability_chain(session)
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], "entry_json_tool_mismatch")

    def test_legitimate_dispatch_patch_keeps_chain_intact(self) -> None:
        # update_observability_log_dispatch patches mutable fields only; the
        # chain (built on immutable identity) must remain valid.
        session = "sec-chain-patch"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.begin_dispatch(session, 7777)
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync", dispatch_id=7777)
        entry = {"tool_called": "agent.sync", "dispatch_id": 7777, "http_status": 200, "bound_to_dispatch": True}
        observability_store.update_observability_log_dispatch(session, 7777, entry)
        report = observability_store.verify_observability_chain(session)
        self.assertTrue(report["ok"])

    def test_chain_check_is_warning_not_dispatch_blocker(self) -> None:
        # A broken chain surfaces as a warning in qa context and must NOT block
        # dispatch (dispatch blocks only on error severity).
        session = "sec-chain-warn"
        agent_behavior.reset_request_cycle(session)
        _record(session, "agent.sync", "ticket.list", "context.get")
        _delete_db_tool(session, "ticket.list")  # middle row -> chain break
        qa = system_integrity.run_invariant_checks("qa", session_key=session)
        chain_violations = [
            v for v in qa["violations"] if v.get("invariant") == "observability_chain_intact"
        ]
        self.assertTrue(chain_violations)
        self.assertEqual(chain_violations[0].get("severity"), "warning")
        # dispatch context does not run the chain check at all
        dispatch = system_integrity.run_invariant_checks("dispatch", session_key=session)
        self.assertFalse(
            any(v.get("invariant") == "observability_chain_intact" for v in dispatch["violations"])
        )


class OrderingGuaranteeTests(IsolatedDbTestCase):
    """#198 — logging is finalized before any invariant check can run."""

    def test_record_tool_call_finalizes_both_sinks_before_returning(self) -> None:
        # By the time record_tool_call returns, the tool is present in BOTH the
        # in-memory log and the DB. Logging is synchronous — there is no window
        # where an invariant check runs against half-written logging.
        session = "sec-order-sync"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
        mem = [e.get("tool_called") for e in agent_behavior._retrieval_log.get(session, [])]
        db = [e.get("tool_called") for e in observability_store.get_observability_logs(session, limit=20)]
        self.assertIn("agent.sync", mem)
        self.assertIn("agent.sync", db)

    def test_invariant_consistent_after_each_finalized_call(self) -> None:
        # Running the observability invariant after every finalized call never
        # reports divergence — prior calls are always fully logged first.
        session = "sec-order-chain"
        agent_behavior.reset_request_cycle(session)
        for tool in ("agent.sync", "context.get", "ticket.list"):
            agent_behavior.record_tool_call(session, tool, reason="x")
            violation = system_integrity._check_observability_truth(session, check_db=True)
            self.assertIsNone(violation, f"unexpected divergence after {tool}: {violation}")

    def test_dispatch_invariant_runs_before_handler_side_effects(self) -> None:
        # A blocked dispatch must never reach the tool handler. run_enforcement_gates
        # returns the invariant violation before actions_tool_registry.dispatch
        # invokes the handler.
        session = "sec-order-block"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
        broken = {
            "context": "dispatch",
            "ok": False,
            "violations": [{"invariant": "handoff_ticket_parity", "severity": "error"}],
        }
        with mock.patch.object(system_integrity, "run_invariant_checks", return_value=broken):
            ok, code, status, _ = system_integrity.run_enforcement_gates(
                session, "ticket.list", query_text="x", kind="read", boot_allowed=True
            )
        self.assertFalse(ok)
        self.assertEqual(code, "invariant_violation")
        self.assertEqual(status, 428)


class EntrypointCoverageTests(unittest.TestCase):
    """#199 — no shadow execution path skips the guarded pipeline."""

    def test_external_surface_is_actions_only(self) -> None:
        # The Cloudflare tunnel is the only externally reachable ingress, and it
        # exposes exclusively /api/actions/* — every external tool call is forced
        # through registry.dispatch -> run_enforcement_gates.
        config = (ROOT / "cloudflared" / "config.yml").read_text(encoding="utf-8")
        self.assertIn("path: ^/api/actions/.*", config)
        # Any non-actions hostname rule must fall through to a 404 service.
        self.assertIn("http_status:404", config)

    def test_unbooted_gateway_dispatch_is_blocked(self) -> None:
        # A fresh session cannot execute any tool before agent.sync — the boot
        # gate blocks it. This is the first guard in the shared pipeline.
        import actions_tool_registry as registry

        registry.ensure_registry()
        body, status = registry.dispatch(
            "read", "ticket.list", {"limit": 3}, session_key="sec-cov-unbooted", agent_id="chatgpt"
        )
        self.assertEqual(status, 428)
        self.assertEqual(body.get("error"), "boot_required")

    def test_booted_gateway_dispatch_routes_through_enforcement(self) -> None:
        # Once booted, every gateway dispatch calls run_enforcement_gates before
        # the handler — no tool executes without passing the gate chain.
        import actions_tool_registry as registry

        registry.ensure_registry()
        registry.dispatch(
            "read", "agent.sync", {"agent": "chatgpt"}, session_key="sec-cov", agent_id="chatgpt"
        )
        with mock.patch.object(
            system_integrity,
            "run_enforcement_gates",
            return_value=(False, "invariant_violation", 428, {"message": "blocked"}),
        ) as gate:
            body, status = registry.dispatch(
                "read", "ticket.list", {"limit": 3}, session_key="sec-cov", agent_id="chatgpt"
            )
        gate.assert_called_once()
        self.assertEqual(status, 428)
        self.assertEqual(body.get("error"), "invariant_violation")

    def test_direct_ingest_entrypoints_enforce_invariants(self) -> None:
        # #196 gate: direct localhost mutation endpoints refuse to execute under
        # an error-severity violation, matching the gateway.
        broken = {
            "context": "dispatch",
            "ok": False,
            "violations": [{"invariant": "handoff_ticket_parity", "severity": "error"}],
        }
        with mock.patch.object(system_integrity, "run_invariant_checks", return_value=broken):
            ok, payload = system_integrity.enforce_dispatch_invariants("ingest.handoff")
        self.assertFalse(ok)
        self.assertEqual(payload.get("error"), "invariant_violation")


class ConcurrencyConsistencyTests(unittest.TestCase):
    """#200 — observability holds under parallel and chained execution."""

    def test_parallel_distinct_sessions_no_contamination(self) -> None:
        errors: list[tuple[str, list[str]]] = []

        def worker(n: int) -> None:
            session = f"sec-conc-{n}"
            agent_behavior.reset_request_cycle(session)
            agent_behavior.begin_dispatch(session, system_integrity.next_dispatch_id())
            agent_behavior.record_tool_call(session, "agent.sync", triggering_rule="sync")
            agent_behavior.record_tool_call(session, "ticket.list", reason="x")
            tools = [e.get("tool_called") for e in agent_behavior._retrieval_log.get(session, [])]
            if tools != ["agent.sync", "ticket.list"]:
                errors.append((session, tools))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_chained_calls_state_matches_log(self) -> None:
        session = "sec-chain"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.begin_dispatch(session, system_integrity.next_dispatch_id())
        for tool in ("agent.sync", "context.get", "retrieve.search"):
            agent_behavior.record_tool_call(session, tool, reason="x")
        mem = [e.get("tool_called") for e in agent_behavior._retrieval_log.get(session, [])]
        state = list(agent_behavior._get_state(session).get("tools_called", []))
        self.assertEqual(mem, state)
        self.assertEqual(mem, ["agent.sync", "context.get", "retrieve.search"])

    def test_concurrent_same_session_writes_are_race_free(self) -> None:
        session = "sec-race"
        agent_behavior.reset_request_cycle(session)
        agent_behavior.begin_dispatch(session, system_integrity.next_dispatch_id())
        writes_per_thread, thread_count = 40, 8

        def hammer() -> None:
            for _ in range(writes_per_thread):
                agent_behavior.record_tool_call(session, "retrieve.search", reason="x")

        threads = [threading.Thread(target=hammer) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # State list is unbounded and lock-protected: no lost updates.
        state_len = len(agent_behavior._get_state(session).get("tools_called", []))
        self.assertEqual(state_len, writes_per_thread * thread_count)


if __name__ == "__main__":
    unittest.main()
