#!/usr/bin/env python3
"""V3.9.10 #68 — chat prompt task frame injection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class PromptTaskFrameTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_build_prompt_includes_task_frame_for_cursor_in_progress_ticket(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Prompt task frame injection probe",
                assignee="cursor",
                project_id=self.project_id,
                description=(
                    "Inject compact task frame into build_prompt.\n\n"
                    "Acceptance:\n"
                    "- Prompt cites ticket id and acceptance bullets\n"
                    "- Includes last handoff next_action"
                ),
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- Prompt task frame probe shipped\n\n"
                "## Next Action\n\n- Continue ticket #68 QA"
            ),
            source="cursor",
            project_id=self.project_id,
            importance=4,
            confidence=0.9,
        )

        system = crowley.build_prompt("where are we on the current ticket?")[0]["content"]
        self.assertIn("Task frame (current Cursor work", system)
        self.assertIn(f"Ticket #{ticket_id}", system)
        self.assertIn("acceptance: Prompt cites ticket id and acceptance bullets", system)
        self.assertIn("Next action from last handoff: Continue ticket #68 QA", system)
        self.assertNotIn("## Summary", system)
        self.assertNotIn("# Crowley Handoff", system)

    def test_build_prompt_omits_task_frame_without_cursor_in_progress_ticket(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Prompt task frame open-only probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="open")

        system = crowley.build_prompt("what is the status?")[0]["content"]
        self.assertNotIn("Task frame (current Cursor work", system)

    def test_prompt_section_order_matches_memory_hierarchy(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Prompt order hierarchy probe unique",
                assignee="cursor",
                project_id=self.project_id,
                description="Order probe.\n\nAcceptance:\n- tickets before task frame before retrieval",
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        system = crowley.build_prompt("Prompt order hierarchy probe unique where are we")[0][
            "content"
        ]
        tickets_idx = system.find("Tickets (authoritative work board")
        task_frame_idx = system.find("Task frame (current Cursor work")
        canon_idx = system.find("Canonical memory trail:")
        supporting_idx = system.find(
            "Supporting memory (hybrid retrieval — lower authority than filesystem truth):"
        )
        self.assertGreater(tickets_idx, 0)
        self.assertGreater(task_frame_idx, tickets_idx)
        self.assertGreater(canon_idx, task_frame_idx)
        self.assertGreater(supporting_idx, canon_idx)

    def test_format_task_frame_prompt_section_returns_empty_without_project(self) -> None:
        self.assertEqual(crowley._format_task_frame_prompt_section(None), "")


if __name__ == "__main__":
    unittest.main()
