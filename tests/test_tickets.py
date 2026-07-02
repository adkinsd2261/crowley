#!/usr/bin/env python3
"""V3.9 concurrent ticketing tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class TicketTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        self.ticket_ids: list[int] = []

    def tearDown(self) -> None:
        if self.ticket_ids:
            marks = ",".join("?" for _ in self.ticket_ids)
            self.conn.execute(
                f"DELETE FROM ticket_events WHERE ticket_id IN ({marks})",
                self.ticket_ids,
            )
            self.conn.execute(
                f"DELETE FROM tickets WHERE id IN ({marks})",
                self.ticket_ids,
            )
            self.conn.commit()
        self.conn.close()
        super().tearDown()

    def _create(self, **kwargs: object) -> int:
        result = crowley.create_ticket(
            str(kwargs.pop("title", "QA ticket")),
            project_id=self.project_id,
            **kwargs,  # type: ignore[arg-type]
        )
        ticket_id = int(result["ticket"]["id"])
        self.ticket_ids.append(ticket_id)
        return ticket_id

    def test_parent_child_create_and_grouped_summary(self) -> None:
        parent_id = self._create(
            title="V3.9.3 Planning Workflow initiative",
            assignee="codex",
            priority=1,
        )
        child_id = self._create(
            title="Child slice probe",
            assignee="cursor",
            priority=1,
            parent_id=parent_id,
        )
        parent = crowley.get_ticket_by_id(parent_id)
        child = crowley.get_ticket_by_id(child_id)
        assert parent is not None and child is not None
        self.assertIsNone(parent["parent_id"])
        self.assertEqual(int(child["parent_id"]), parent_id)

        summary = crowley.build_tickets_summary(self.project_id, "cursor")
        grouped = summary["grouped_open"]
        assert isinstance(grouped, list)
        parent_group = next(
            (group for group in grouped if int(group["ticket"]["id"]) == parent_id),
            None,
        )
        self.assertIsNotNone(parent_group)
        assert parent_group is not None
        self.assertTrue(bool(parent_group["is_initiative"]))
        child_ids = {int(item["id"]) for item in parent_group["children"]}
        self.assertIn(child_id, child_ids)

        sync = crowley.build_agent_sync_bundle(agent="cursor", limit=5)
        sync_grouped = sync["tickets"]["grouped_open"]
        assert isinstance(sync_grouped, list)
        self.assertGreaterEqual(len(sync_grouped), 1)

    def test_orphan_open_child_renders_once_when_parent_not_open(self) -> None:
        parent_id = self._create(
            title="Closed parent initiative probe",
            assignee="codex",
            priority=1,
        )
        child_id = self._create(
            title="Orphan open child probe",
            assignee="cursor",
            priority=1,
            parent_id=parent_id,
        )
        crowley.complete_ticket(parent_id, actor="codex")

        open_rows = crowley.list_tickets(project_id=self.project_id, open_only=True)
        open_payload = [crowley.row_to_dict(row) for row in open_rows]
        grouped = crowley.group_tickets_by_parent(open_payload)

        rendered_ids: list[int] = []
        for group in grouped:
            rendered_ids.append(int(group["ticket"]["id"]))
            for child in group["children"]:
                rendered_ids.append(int(child["id"]))

        self.assertEqual(rendered_ids.count(child_id), 1)
        orphan_group = next(
            (group for group in grouped if int(group["ticket"]["id"]) == child_id),
            None,
        )
        self.assertIsNotNone(orphan_group)
        assert orphan_group is not None
        self.assertEqual(orphan_group["children"], [])
        self.assertFalse(bool(orphan_group["is_initiative"]))

    def test_create_and_list_ticket(self) -> None:
        ticket_id = self._create(title="Schema probe", assignee="cursor", priority=1)
        row = crowley.get_ticket_by_id(ticket_id)
        assert row is not None
        self.assertEqual(str(row["title"]), "Schema probe")
        self.assertEqual(str(row["assignee"]), "cursor")
        open_rows = crowley.list_tickets(project_id=self.project_id, open_only=True)
        self.assertIn(ticket_id, {int(r["id"]) for r in open_rows})

    def test_update_and_complete_ticket(self) -> None:
        ticket_id = self._create(title="Close probe", assignee="cursor")
        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="in_progress",
            comment="starting",
        )
        result = crowley.complete_ticket(ticket_id, actor="cursor")
        self.assertEqual(result["ticket"]["status"], "done")
        self.assertIsNotNone(result["ticket"]["closed_at"])

    def test_build_tickets_summary_assigned_filter(self) -> None:
        cursor_id = self._create(title="Cursor lane", assignee="cursor")
        codex_id = self._create(title="Codex lane", assignee="codex")
        summary = crowley.build_tickets_summary(self.project_id, "cursor")
        assigned = summary["assigned_to_agent"]
        assert isinstance(assigned, list)
        assigned_ids = {int(t["id"]) for t in assigned}
        self.assertIn(cursor_id, assigned_ids)
        self.assertNotIn(codex_id, assigned_ids)
        for ticket in assigned:
            self.assertEqual(str(ticket["assignee"]).lower(), "cursor")

    def test_context_and_sync_bundles_include_tickets(self) -> None:
        self._create(title="Bundle probe", assignee="cursor")
        context = crowley.build_context_bundle(q="tickets", limit=1)
        self.assertIn("open", context["tickets"])
        sync = crowley.build_agent_sync_bundle(agent="cursor", limit=5)
        self.assertIn("assigned_to_agent", sync["tickets"])

    def test_prompt_includes_ticket_block(self) -> None:
        self._create(title="Prompt probe ticket", assignee="cursor")
        system = crowley.build_prompt("what tickets are open?")[0]["content"]
        self.assertIn("Tickets (authoritative work board", system)
        self.assertIn("Prompt probe ticket", system)

    def test_get_ticket_detail_events(self) -> None:
        ticket_id = self._create(title="Event probe", assignee="cursor")
        detail = crowley.get_ticket_detail(ticket_id)
        assert detail is not None
        events = detail["events"]
        assert isinstance(events, list)
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "created")

    def test_get_ticket_detail_includes_core_fields(self) -> None:
        ticket_id = self._create(
            title="Detail probe",
            assignee="cursor",
            description="Scope body\n\nAcceptance:\n- Field visible\n- Events visible",
            priority=1,
        )
        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="in_progress",
            comment="starting detail probe",
        )
        detail = crowley.get_ticket_detail(ticket_id)
        assert detail is not None
        ticket = detail["ticket"]
        self.assertEqual(str(ticket["title"]), "Detail probe")
        self.assertEqual(str(ticket["status"]), "in_progress")
        self.assertEqual(str(ticket["assignee"]), "cursor")
        self.assertEqual(int(ticket["priority"]), 1)
        self.assertIn("Acceptance:", str(ticket["description"]))
        self.assertIsNotNone(ticket.get("created_at"))
        self.assertIsNotNone(ticket.get("updated_at"))
        event_types = {str(event["event_type"]) for event in detail["events"]}
        self.assertIn("created", event_types)
        self.assertIn("status_change", event_types)
        self.assertIn("comment", event_types)

    def test_close_with_linked_handoff_records_event_and_detail(self) -> None:
        ticket_id = self._create(title="Handoff link probe", assignee="cursor")
        mem_id = crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\nType: builder_handoff\n\n"
                "## Summary\n\n- shipped handoff link probe unique phrase"
            ),
            source="cursor",
            project_id=self.project_id,
        )
        self.assertIsNotNone(mem_id)
        assert mem_id is not None

        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="done",
            linked_memory_id=mem_id,
        )
        detail = crowley.get_ticket_detail(ticket_id)
        assert detail is not None
        self.assertEqual(int(detail["ticket"]["linked_memory_id"]), mem_id)
        linked = detail.get("linked_handoff")
        assert isinstance(linked, dict)
        self.assertEqual(int(linked["memory_id"]), mem_id)
        self.assertIn("handoff link probe", str(linked.get("summary", "")).lower())

        event_types = {str(event["event_type"]) for event in detail["events"]}
        self.assertIn("handoff_linked", event_types)
        handoff_event = next(
            event for event in detail["events"] if event["event_type"] == "handoff_linked"
        )
        self.assertEqual(str(handoff_event["actor"]), "cursor")
        payload = handoff_event["payload"]
        assert isinstance(payload, dict)
        self.assertEqual(int(payload["memory_id"]), mem_id)

        activity = crowley._agent_activity_summary(self.project_id)
        recent = activity.get("recent")
        assert isinstance(recent, list)
        linked_event = next((item for item in recent if int(item["id"]) == mem_id), None)
        self.assertIsNotNone(linked_event)
        assert linked_event is not None
        self.assertIn(ticket_id, linked_event.get("linked_ticket_ids", []))

    def test_cancel_ticket_excludes_from_open_summary(self) -> None:
        ticket_id = self._create(title="Draft superseded probe", assignee="cursor")
        result = crowley.cancel_ticket(
            ticket_id,
            actor="codex",
            comment="Superseded by tickets #9-#23 from approved Pre-V4 plan",
        )
        self.assertEqual(result["ticket"]["status"], "cancelled")
        self.assertIsNotNone(result["ticket"]["closed_at"])

        row = crowley.get_ticket_by_id(ticket_id)
        assert row is not None
        self.assertEqual(str(row["status"]), "cancelled")

        open_rows = crowley.list_tickets(project_id=self.project_id, open_only=True)
        self.assertNotIn(ticket_id, {int(r["id"]) for r in open_rows})

        summary = crowley.build_tickets_summary(self.project_id, "cursor")
        open_ids = {int(t["id"]) for t in summary["open"]}
        self.assertNotIn(ticket_id, open_ids)
        assigned_ids = {int(t["id"]) for t in summary["assigned_to_agent"]}
        self.assertNotIn(ticket_id, assigned_ids)

        detail = crowley.get_ticket_detail(ticket_id)
        assert detail is not None
        event_types = [event["event_type"] for event in detail["events"]]
        self.assertIn("cancelled", event_types)
        cancelled = next(
            event for event in detail["events"] if event["event_type"] == "cancelled"
        )
        self.assertEqual(str(cancelled["actor"]), "codex")
        payload = cancelled["payload"]
        assert isinstance(payload, dict)
        self.assertIn("Superseded", str(payload.get("reason", "")))

    def test_cancel_ticket_requires_comment(self) -> None:
        ticket_id = self._create(title="Cancel comment probe", assignee="cursor")
        with self.assertRaises(ValueError):
            crowley.cancel_ticket(ticket_id, actor="codex", comment="   ")


if __name__ == "__main__":
    unittest.main()
