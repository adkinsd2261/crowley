#!/usr/bin/env python3
"""V3.9.10 #67 — Agent Feed task brief UI."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class UiTaskFrameBriefTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_world_dashboard_includes_task_frame_payload(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "UI task brief dashboard probe",
                assignee="cursor",
                project_id=self.project_id,
                description=(
                    "Agent Feed brief.\n\n"
                    "Acceptance:\n"
                    "- Agent Feed shows structured task brief"
                ),
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        dash = crowley.build_world_dashboard()
        task_frame = dash.get("task_frame")
        assert isinstance(task_frame, dict)
        working_on = task_frame.get("working_on")
        assert isinstance(working_on, list)
        self.assertGreaterEqual(len(working_on), 1)
        self.assertIn(ticket_id, {int(item["id"]) for item in working_on})
        guardrails = task_frame.get("guardrails")
        assert isinstance(guardrails, dict)
        self.assertIn("recent_decisions", guardrails)
        self.assertIn("constraint_memories", guardrails)

    def test_static_assets_include_task_brief_ui(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("panel-agent-brief", html)
        self.assertIn("task-brief-working-list", html)
        self.assertIn("task-brief-handoff-body", html)
        self.assertIn("task-brief-guardrails-body", html)
        self.assertIn("agent-supporting-count", html)
        self.assertNotIn("Context pulled for agents", html)
        self.assertIn("Task brief for current work", html)
        self.assertIn("renderTaskFrameBrief", js)
        self.assertIn("renderTaskBriefWorkingOn", js)
        self.assertIn("renderTaskBriefGuardrails", js)
        self.assertIn("agent-feed-brief", css)
        self.assertIn("task-brief-guardrail-chip", css)
        self.assertIn("memory-hygiene-callout", html)
        self.assertIn("loadHygieneCallout", js)

    def test_supporting_memories_cap_on_dashboard(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Supporting cap dashboard probe unique phrase",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        for idx in range(6):
            crowley.save_memory_item(
                "lesson",
                f"Supporting cap dashboard probe unique phrase lesson {idx}",
                source="cursor",
                project_id=self.project_id,
                summary=f"Lesson {idx} for dashboard cap",
                importance=4,
                confidence=0.9,
            )

        dash = crowley.build_world_dashboard()
        memories = dash.get("relevant_memories")
        assert isinstance(memories, list)
        self.assertLessEqual(len(memories), crowley.SUPPORTING_MEMORIES_CAP)


if __name__ == "__main__":
    unittest.main()
