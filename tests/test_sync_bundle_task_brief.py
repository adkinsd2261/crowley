#!/usr/bin/env python3
"""V3.9.10 #66 — sync bundle task brief integration."""

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


class SyncBundleTaskBriefTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_bundle_includes_task_frame_and_supporting_memories(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Sync bundle task brief probe",
                assignee="cursor",
                project_id=self.project_id,
                description="Brief integration.\n\nAcceptance:\n- bundle includes supporting_memories",
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        self.assertEqual(sync["bundle_shape"], "task_frame_v3910")
        self.assertIn("task_frame", sync)
        self.assertIn("supporting_memories", sync)
        self.assertIn("relevant_memories", sync)
        self.assertIs(sync["supporting_memories"], sync["relevant_memories"])
        caps = sync["bundle_caps"]
        assert isinstance(caps, dict)
        self.assertIn("supporting_memories", caps)
        self.assertLessEqual(
            len(sync["supporting_memories"]),
            crowley.SUPPORTING_MEMORIES_CAP,
        )
        task_frame = sync["task_frame"]
        assert isinstance(task_frame, dict)
        self.assertEqual(task_frame.get("agent"), "cursor")

    def test_cursor_print_order_task_frame_before_supporting(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Print order task brief probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- Print order probe shipped\n\n"
                "## Next Action\n\n- Continue #66"
            ),
            source="cursor",
            project_id=self.project_id,
            importance=4,
            confidence=0.9,
        )

        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            asl.print_agent_sync_bundle(sync, agent="cursor")
        output = buffer.getvalue()
        working_idx = output.find("Working on:")
        handoff_idx = output.find("Last handoff:")
        guardrails_idx = output.find("Guardrails:")
        supporting_idx = output.find("Supporting (")
        self.assertGreater(working_idx, 0)
        self.assertGreater(handoff_idx, working_idx)
        self.assertGreater(guardrails_idx, handoff_idx)
        self.assertGreater(supporting_idx, guardrails_idx)
        self.assertNotIn("top retrieved memories:", output)
        self.assertNotIn("recent decisions:", output)
        self.assertNotIn("constraint memories:", output)

    def test_codex_print_shows_architect_task_frame(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Codex architect task frame probe",
                assignee="codex",
                project_id=self.project_id,
                description="Planning scope.\n\nAcceptance:\n- architect-scoped frame",
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="codex", status="open")

        sync = crowley.build_agent_sync_bundle("codex", limit=8)
        task_frame = sync["task_frame"]
        assert isinstance(task_frame, dict)
        self.assertEqual(task_frame.get("agent"), "codex")
        self.assertIn("architect", str(task_frame.get("role")).lower())
        work_ids = {int(item["id"]) for item in task_frame.get("working_on", [])}
        self.assertIn(ticket_id, work_ids)

        buffer = StringIO()
        with patch("sys.stdout", buffer):
            asl.print_agent_sync_bundle(sync, agent="codex")
        output = buffer.getvalue()
        self.assertIn("Working on:", output)
        self.assertIn("Codex architect task frame probe", output)

    def test_supporting_memories_fallback_from_relevant_memories(self) -> None:
        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        legacy = dict(sync)
        legacy.pop("supporting_memories", None)
        memories = asl.supporting_memories_from_sync(legacy)
        self.assertEqual(memories, sync["relevant_memories"])


if __name__ == "__main__":
    unittest.main()
