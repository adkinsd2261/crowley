#!/usr/bin/env python3
"""V3.9.9 slim agent sync bundle tests (ticket #58)."""

from __future__ import annotations

import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS))

import agent_sync_lib as asl  # noqa: E402
import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class SlimAgentSyncBundleTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def _insert_constraint(self, content: str) -> int:
        now = crowley._now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence
            ) VALUES (?, ?, ?, 'constraint', ?, ?, 4, 'codex', 0, 'active', 0.95)
            """,
            (now, now, self.project_id, content, content[:120]),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def test_slim_bundle_shape_and_caps(self) -> None:
        for idx in range(7):
            self._insert_constraint(f"Slim sync constraint probe {idx} unique phrase")
        for idx in range(7):
            crowley.save_decision(
                self.project_id,
                f"Slim sync decision probe {idx}",
                source="extract",
            )

        sync = crowley.build_agent_sync_bundle("cursor", limit=20)
        self.assertEqual(sync["bundle_shape"], "task_frame_v3910")
        caps = sync["bundle_caps"]
        assert isinstance(caps, dict)
        self.assertEqual(caps["recent_decisions"], 5)
        self.assertEqual(caps["constraint_memories"], 5)
        self.assertEqual(caps["events_from_other_agents"], 5)
        self.assertLessEqual(len(sync["recent_decisions"]), 5)
        self.assertLessEqual(len(sync["constraint_memories"]), 5)
        self.assertLessEqual(len(sync["events_from_other_agents"]), 5)
        self.assertGreaterEqual(len(sync["relevant_memories"]), 1)
        self.assertLessEqual(len(sync["relevant_memories"]), crowley.SUPPORTING_MEMORIES_CAP)
        self.assertNotIn("canon", sync)
        self.assertNotIn("open_loops", sync)
        self.assertNotIn("open_tasks", sync)
        self.assertNotIn("recent_events", sync)

    def test_cursor_bundle_includes_assigned_tickets_and_blockers(self) -> None:
        assigned_id = crowley.create_ticket(
            "Slim sync assigned probe",
            assignee="cursor",
            project_id=self.project_id,
        )["ticket"]["id"]
        blocked_id = crowley.create_ticket(
            "Slim sync blocked probe",
            assignee="cursor",
            project_id=self.project_id,
        )["ticket"]["id"]
        crowley.update_ticket(
            int(blocked_id),
            actor="cursor",
            status="blocked",
            comment="waiting on review",
        )

        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        tickets = sync["tickets"]
        assert isinstance(tickets, dict)
        assigned_ids = {int(t["id"]) for t in tickets["assigned_to_agent"]}
        self.assertIn(int(assigned_id), assigned_ids)
        blocked = tickets.get("blocked")
        assert isinstance(blocked, list)
        blocked_ids = {int(t["id"]) for t in blocked}
        self.assertIn(int(blocked_id), blocked_ids)

    def test_codex_bundle_keeps_planning_context_without_dump(self) -> None:
        sync = crowley.build_agent_sync_bundle("codex", limit=8)
        self.assertIn("architect", sync["role"].lower())
        self.assertIn("recent_decisions", sync)
        self.assertIn("tickets", sync)
        self.assertNotIn("open_loops", sync)
        self.assertNotIn("open_tasks", sync)
        self.assertNotIn("canon", sync)

    def test_relevant_memories_include_inclusion_reason(self) -> None:
        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        memories = sync.get("relevant_memories")
        assert isinstance(memories, list)
        if memories:
            self.assertIn("inclusion_reason", memories[0])

    def test_print_order_shows_tickets_before_memories(self) -> None:
        crowley.create_ticket(
            "Slim sync print order probe",
            assignee="cursor",
            project_id=self.project_id,
        )
        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            asl.print_agent_sync_bundle(sync, agent="cursor")
        output = buffer.getvalue()
        tickets_idx = output.find("tickets assigned to you:")
        working_idx = output.find("Working on:")
        supporting_idx = output.find("Supporting (")
        self.assertGreater(tickets_idx, 0)
        self.assertGreater(working_idx, tickets_idx)
        self.assertGreater(supporting_idx, working_idx)

    def test_print_sync_extras_skips_slim_duplicate(self) -> None:
        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        self.assertTrue(asl.is_slim_sync_bundle(sync))
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            asl.print_sync_extras(sync, agent="cursor")
        self.assertEqual(buffer.getvalue(), "")

    def test_is_slim_sync_bundle_detects_caps_without_shape(self) -> None:
        sync = {"bundle_caps": {"relevant_memories": 8}, "constraint_memories": []}
        self.assertTrue(asl.is_slim_sync_bundle(sync))

    def test_is_slim_sync_bundle_rejects_legacy_canon_dump(self) -> None:
        legacy = {"canon": [], "open_loops": [], "recent_decisions": []}
        self.assertFalse(asl.is_slim_sync_bundle(legacy))


if __name__ == "__main__":
    unittest.main()
