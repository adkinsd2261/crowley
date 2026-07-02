#!/usr/bin/env python3
"""V3.9 concurrent ticketing tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


class TicketTests(unittest.TestCase):
    def setUp(self) -> None:
        crowley.setup_db()
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

    def _create(self, **kwargs: object) -> int:
        result = crowley.create_ticket(
            str(kwargs.pop("title", "QA ticket")),
            project_id=self.project_id,
            **kwargs,  # type: ignore[arg-type]
        )
        ticket_id = int(result["ticket"]["id"])
        self.ticket_ids.append(ticket_id)
        return ticket_id

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


if __name__ == "__main__":
    unittest.main()
