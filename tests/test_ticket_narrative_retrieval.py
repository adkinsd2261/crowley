#!/usr/bin/env python3
"""V3.9.10 #65 — ticket-narrative supporting retrieval."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class TicketNarrativeRetrievalTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_query_includes_acceptance_keywords(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "UI hygiene inclusion badge probe",
                assignee="cursor",
                project_id=self.project_id,
                description=(
                    "Light UI for Agent Feed badges.\n\n"
                    "Acceptance:\n"
                    "- Agent Feed renders inclusion_reason when present\n"
                    "- Hygiene endpoint makes zero writes"
                ),
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        query, seeds = crowley.build_ticket_aware_retrieval_query(
            self.project_id,
            "cursor",
        )
        self.assertIn(f"ticket #{ticket_id}", query)
        self.assertIn("UI hygiene inclusion badge probe", query)
        self.assertIn("inclusion_reason", query)
        self.assertIn("Hygiene endpoint makes zero writes", query)
        self.assertNotIn("recent work by other agents", query.lower())
        self.assertGreaterEqual(len(seeds), 1)

    def test_supporting_memories_exclude_recent_handoff_ids(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Handoff dedupe probe ticket",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        handoff_id = crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- Unrelated QA handoff about runtime hardening only"
            ),
            source="cursor",
            project_id=self.project_id,
            importance=4,
            confidence=0.9,
        )
        lesson_id = crowley.save_memory_item(
            "lesson",
            "Handoff dedupe probe ticket lesson about inclusion badges and hygiene UI",
            source="cursor",
            project_id=self.project_id,
            summary="Why UI hygiene matters for agent feed",
            importance=4,
            confidence=0.9,
        )
        assert handoff_id is not None
        assert lesson_id is not None

        context = crowley.retrieve_work_context_memories(
            self.project_id,
            "cursor",
            limit=4,
        )
        memory_ids = {int(item["id"]) for item in context["memories"]}
        self.assertNotIn(int(handoff_id), memory_ids)
        self.assertLessEqual(len(context["memories"]), crowley.SUPPORTING_MEMORIES_CAP)

    def test_type_preference_boosts_lesson_over_project_update(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Type preference ranking probe unique phrase",
                assignee="cursor",
                project_id=self.project_id,
                description="Ranking probe for lesson vs project_update.\n\nAcceptance:\n- lesson ranks first",
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        crowley.save_memory_item(
            "project_update",
            "Type preference ranking probe unique phrase project update noise",
            source="cursor",
            project_id=self.project_id,
            importance=5,
            confidence=0.95,
        )
        lesson_id = crowley.save_memory_item(
            "lesson",
            "Type preference ranking probe unique phrase lesson about hygiene UI",
            source="cursor",
            project_id=self.project_id,
            summary="Lesson for ranking probe",
            importance=3,
            confidence=0.9,
        )
        assert lesson_id is not None

        context = crowley.retrieve_work_context_memories(
            self.project_id,
            "cursor",
            limit=4,
        )
        memories = context["memories"]
        self.assertGreaterEqual(len(memories), 1)
        types = [str(item["memory_type"]) for item in memories]
        if "lesson" in types and "project_update" in types:
            self.assertLess(types.index("lesson"), types.index("project_update"))

    def test_ticket_62_fixture_prefers_ui_hygiene_over_unrelated_qa_handoff(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "V3.9.9 Context: light UI and hygiene report",
                assignee="cursor",
                project_id=self.project_id,
                description=(
                    "Light UI: Agent Feed inclusion_reason badges; hygiene callout.\n\n"
                    "Acceptance:\n"
                    "- Agent Feed renders inclusion_reason when present\n"
                    "- Hygiene endpoint/report makes zero writes"
                ),
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- Unrelated runtime hardening QA handoff from ticket #50"
            ),
            source="cursor",
            project_id=self.project_id,
            importance=4,
            confidence=0.9,
        )
        ui_memory_id = crowley.save_memory_item(
            "qa_result",
            "Ticket #62 light UI hygiene report shipped inclusion badges and hygiene callout",
            source="cursor",
            project_id=self.project_id,
            summary="UI hygiene QA for agent feed",
            importance=4,
            confidence=0.95,
        )
        assert ui_memory_id is not None

        context = crowley.retrieve_work_context_memories(
            self.project_id,
            "cursor",
            limit=4,
        )
        memory_ids = [int(item["id"]) for item in context["memories"]]
        self.assertIn(int(ui_memory_id), memory_ids)
        self.assertIn("inclusion_reason", context["memories"][0])
        self.assertTrue(
            str(context["memories"][0]["inclusion_reason"]).startswith("Pulled because:")
        )

    def test_inclusion_reason_on_every_supporting_memory(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Inclusion reason probe ticket",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        crowley.save_memory_item(
            "constraint",
            f"Inclusion reason probe ticket #{ticket_id} constraint about agent feed wiring",
            source="codex",
            project_id=self.project_id,
            summary="Constraint for inclusion reason probe",
            importance=4,
            confidence=0.9,
        )

        context = crowley.retrieve_work_context_memories(
            self.project_id,
            "cursor",
            limit=4,
        )
        for item in context["memories"]:
            self.assertIn("inclusion_reason", item)
            self.assertTrue(str(item["inclusion_reason"]).startswith("Pulled because:"))


if __name__ == "__main__":
    unittest.main()
