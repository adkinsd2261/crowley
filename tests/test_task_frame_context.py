#!/usr/bin/env python3
"""V3.9.10 #64 — task frame builder API."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class TaskFrameContextTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def _save_handoff(self, source: str, summary_line: str, next_action: str) -> int:
        memory_id = crowley.save_memory_item(
            "project_update",
            (
                f"# Crowley Handoff\n\nSource: {source}\n\n"
                f"## Summary\n\n- {summary_line}\n\n"
                f"## Next Action\n\n- {next_action}"
            ),
            source=source,
            project_id=self.project_id,
            importance=4,
            confidence=0.9,
        )
        assert memory_id is not None
        return int(memory_id)

    def test_cursor_frame_parses_acceptance_on_working_on(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Task frame builder API probe",
                assignee="cursor",
                project_id=self.project_id,
                description=(
                    "Build build_task_frame_context for agent sync.\n\n"
                    "Acceptance:\n"
                    "- task_frame includes acceptance criteria parsed from description\n"
                    "- Tests cover cursor and codex agent shapes"
                ),
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        frame = crowley.build_task_frame_context(self.project_id, "cursor")
        self.assertEqual(frame["agent"], "cursor")
        self.assertIn("builder", str(frame["role"]).lower())
        working_on = frame["working_on"]
        assert isinstance(working_on, list)
        self.assertGreaterEqual(len(working_on), 1)
        first = working_on[0]
        self.assertEqual(int(first["id"]), ticket_id)
        acceptance = first["acceptance"]
        assert isinstance(acceptance, list)
        self.assertGreaterEqual(len(acceptance), 2)
        self.assertIn("acceptance criteria parsed", acceptance[0])

    def test_codex_frame_scoped_to_architect_assignments(self) -> None:
        codex_id = int(
            crowley.create_ticket(
                "Codex task frame planning probe",
                assignee="codex",
                project_id=self.project_id,
                description="Architect planning scope.\n\nAcceptance:\n- Mint tickets with acceptance",
            )["ticket"]["id"]
        )
        crowley.update_ticket(codex_id, actor="codex", status="open")
        cursor_id = int(
            crowley.create_ticket(
                "Cursor-only task frame probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(cursor_id, actor="cursor", status="in_progress")

        frame = crowley.build_task_frame_context(self.project_id, "codex")
        self.assertEqual(frame["agent"], "codex")
        self.assertIn("architect", str(frame["role"]).lower())
        work_ids = {int(item["id"]) for item in frame["working_on"]}
        self.assertIn(codex_id, work_ids)
        self.assertNotIn(cursor_id, work_ids)

    def test_last_handoff_includes_summary_and_next_action(self) -> None:
        self._save_handoff(
            "cursor",
            "Task frame handoff summary probe",
            "Continue ticket #64 QA",
        )
        frame = crowley.build_task_frame_context(self.project_id, "cursor")
        last_handoff = frame["last_handoff"]
        assert isinstance(last_handoff, dict)
        self.assertIn("summary", last_handoff)
        self.assertIn("next_action", last_handoff)
        self.assertIn("Task frame handoff summary probe", str(last_handoff["summary"]))
        self.assertIn("ticket #64", str(last_handoff["next_action"]))

    def test_guardrails_caps_decisions_and_constraints(self) -> None:
        self.conn.close()
        for idx in range(7):
            crowley.save_decision(
                self.project_id,
                f"Task frame decision cap probe {idx}",
                source="extract",
            )
            now = crowley._now_iso()
            conn = crowley.connect_db()
            try:
                conn.execute(
                    """
                    INSERT INTO memory_items (
                        created_at, updated_at, project_id, memory_type, content, summary,
                        importance, source, pinned, status, confidence
                    ) VALUES (?, ?, ?, 'constraint', ?, ?, 4, 'codex', 0, 'active', 0.95)
                    """,
                    (
                        now,
                        now,
                        self.project_id,
                        f"Task frame constraint cap probe {idx}",
                        f"Task frame constraint cap probe {idx}",
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        self.conn = crowley.connect_db()

        frame = crowley.build_task_frame_context(self.project_id, "cursor")
        guardrails = frame["guardrails"]
        assert isinstance(guardrails, dict)
        decisions = guardrails["recent_decisions"]
        constraints = guardrails["constraint_memories"]
        assert isinstance(decisions, list)
        assert isinstance(constraints, list)
        self.assertLessEqual(len(decisions), crowley.AGENT_SYNC_DECISIONS_CAP)
        self.assertLessEqual(len(constraints), crowley.AGENT_SYNC_CONSTRAINTS_CAP)
        self.assertEqual(len(decisions), crowley.AGENT_SYNC_DECISIONS_CAP)
        self.assertEqual(len(constraints), crowley.AGENT_SYNC_CONSTRAINTS_CAP)

    def test_blockers_included_for_assigned_agent(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Task frame blocker probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="blocked",
            comment="waiting on review",
        )

        frame = crowley.build_task_frame_context(self.project_id, "cursor")
        blocker_ids = {int(item["id"]) for item in frame["blockers"]}
        self.assertIn(ticket_id, blocker_ids)

    def test_world_dashboard_exposes_task_frame(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "World dashboard task frame probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        dash = crowley.build_world_dashboard()
        task_frame = dash.get("task_frame")
        assert isinstance(task_frame, dict)
        self.assertIsNone(task_frame.get("agent"))
        work_ids = {int(item["id"]) for item in task_frame.get("working_on", [])}
        self.assertIn(ticket_id, work_ids)

    def test_agent_sync_bundle_exposes_task_frame(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Sync bundle task frame probe",
                assignee="cursor",
                project_id=self.project_id,
                description="Sync exposure.\n\nAcceptance:\n- bundle includes task_frame key",
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        task_frame = sync.get("task_frame")
        assert isinstance(task_frame, dict)
        self.assertEqual(task_frame.get("agent"), "cursor")
        work_ids = {int(item["id"]) for item in task_frame.get("working_on", [])}
        self.assertIn(ticket_id, work_ids)


if __name__ == "__main__":
    unittest.main()
