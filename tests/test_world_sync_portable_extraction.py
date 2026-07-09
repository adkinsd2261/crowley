#!/usr/bin/env python3
"""V4.1 — world, sync, and portable extraction compatibility tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_sync_bundle  # noqa: E402
import crowley  # noqa: E402
import portable_context  # noqa: E402
import world_state  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class WorldSyncPortableExtractionTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_world_state_module_backs_dashboard_facade(self) -> None:
        crowley.record_activity_pulse(
            "codex",
            "claimed",
            project_id=self.project_id,
            summary="T7 extraction dashboard probe",
        )

        direct = world_state.build_world_dashboard(crowley)
        facade = crowley.build_world_dashboard()

        self.assertEqual(set(direct.keys()), set(facade.keys()))
        self.assertEqual(direct["project"]["id"], facade["project"]["id"])
        self.assertEqual(
            direct["activity_wire"]["cap"],
            facade["activity_wire"]["cap"],
        )

    def test_agent_sync_module_backs_bundle_facade(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "T7 extraction sync probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )

        direct = agent_sync_bundle.build_agent_sync_bundle(crowley, "cursor", limit=8)
        facade = crowley.build_agent_sync_bundle("cursor", limit=8)

        self.assertEqual(direct["bundle_shape"], facade["bundle_shape"])
        self.assertEqual(direct["bundle_caps"], facade["bundle_caps"])
        direct_assigned = {int(item["id"]) for item in direct["tickets"]["assigned_to_agent"]}
        facade_assigned = {int(item["id"]) for item in facade["tickets"]["assigned_to_agent"]}
        self.assertIn(ticket_id, direct_assigned)
        self.assertEqual(direct_assigned, facade_assigned)

    def test_portable_module_handles_parse_and_internal_ingest_calls(self) -> None:
        raw = (FIXTURES / "portable_writeback_valid.json").read_text()

        parsed = portable_context.parse_terminal_writeback(crowley, raw)
        self.assertTrue(parsed.ok, parsed.errors)

        result = portable_context.ingest_terminal_writeback(crowley, raw)
        self.assertEqual(result["status"], "ok")
        self.assertIn("session_receipt_id", result)
        self.assertEqual(len(result["spark_ids"]), 2)


if __name__ == "__main__":
    import unittest

    unittest.main()
