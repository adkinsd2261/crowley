#!/usr/bin/env python3
"""V3.9.9 #61 — handoff ↔ ticket wiring in sync bundle and CLI helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import crowley  # noqa: E402
import tickets  # noqa: E402
from agent_sync_lib import (  # noqa: E402
    format_handoff_closed_ticket,
    ticket_handoff_note,
)
from db_helpers import IsolatedDbTestCase  # noqa: E402


class HandoffTicketWiringTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def _handoff(self, summary: str, *, source: str = "cursor") -> int:
        mem_id = crowley.save_memory_item(
            "project_update",
            (
                f"# Crowley Handoff\n\nSource: {source}\nType: builder_handoff\n\n"
                f"## Summary\n\n- {summary}"
            ),
            source=source,
            project_id=self.project_id,
        )
        assert mem_id is not None
        return int(mem_id)

    def test_tickets_summary_enriches_linked_handoff(self) -> None:
        mem_id = self._handoff("wiring enrich probe alpha")
        ticket_id = int(
            crowley.create_ticket(
                "Wiring enrich probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="in_progress",
            linked_memory_id=mem_id,
        )

        summary = tickets.build_tickets_summary(self.project_id, "cursor")
        assigned = summary["assigned_to_agent"]
        assert isinstance(assigned, list)
        match = next((t for t in assigned if int(t["id"]) == ticket_id), None)
        self.assertIsNotNone(match)
        assert match is not None
        linked = match.get("linked_handoff")
        assert isinstance(linked, dict)
        self.assertEqual(int(linked["memory_id"]), mem_id)
        self.assertIn("wiring enrich probe", str(linked.get("summary", "")).lower())

    def test_last_by_source_includes_linked_ticket_ids(self) -> None:
        mem_id = self._handoff("last by source wiring probe")
        ticket_id = int(
            crowley.create_ticket(
                "Last-by-source probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="done",
            linked_memory_id=mem_id,
        )

        activity = crowley._agent_activity_summary(self.project_id)
        last = activity["last_by_source"].get("cursor")
        self.assertIsNotNone(last)
        assert last is not None
        self.assertEqual(int(last["memory_id"]), mem_id)
        self.assertIn(ticket_id, last.get("linked_ticket_ids", []))

    def test_prompt_sections_surface_handoff_ticket_links(self) -> None:
        mem_id = self._handoff("prompt wiring probe beta")
        ticket_id = int(
            crowley.create_ticket(
                "Prompt wiring probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="in_progress",
            linked_memory_id=mem_id,
        )

        ticket_section = tickets._format_tickets_prompt_section(self.project_id, "cursor")
        self.assertIn(f"#{ticket_id}", ticket_section)
        self.assertIn(f"handoff #{mem_id}", ticket_section)

        activity_section = crowley._format_agent_activity_prompt_section(self.project_id)
        self.assertIn(f"#{ticket_id}", activity_section)
        self.assertIn(f"memory #{mem_id}", activity_section)

    def test_sync_bundle_carries_wiring_metadata(self) -> None:
        mem_id = self._handoff("sync bundle wiring probe gamma")
        ticket_id = int(
            crowley.create_ticket(
                "Sync bundle wiring probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(
            ticket_id,
            actor="cursor",
            status="done",
            linked_memory_id=mem_id,
        )

        sync = crowley.build_agent_sync_bundle(agent="cursor", limit=5)
        activity = sync.get("agent_activity")
        assert isinstance(activity, dict)
        last = (activity.get("last_by_source") or {}).get("cursor")
        assert isinstance(last, dict)
        self.assertIn(ticket_id, last.get("linked_ticket_ids", []))

        tickets_block = sync.get("tickets")
        assert isinstance(tickets_block, dict)
        closed = tickets_block.get("recently_closed")
        assert isinstance(closed, list)
        match = next((t for t in closed if int(t["id"]) == ticket_id), None)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(int(match["linked_handoff"]["memory_id"]), mem_id)

    def test_cli_helpers_for_handoff_ticket_notes(self) -> None:
        ticket = {
            "linked_handoff": {
                "memory_id": 42,
                "summary": "shipped wiring probe",
            }
        }
        note = ticket_handoff_note(ticket)
        self.assertIn("handoff #42", note)
        self.assertIn("shipped wiring probe", note)

        fallback = ticket_handoff_note({"linked_memory_id": 99})
        self.assertIn("handoff #99", fallback)

        close_line = format_handoff_closed_ticket(42, 61)
        self.assertEqual(close_line, "Handoff #42 closed ticket #61.")


if __name__ == "__main__":
    unittest.main()
