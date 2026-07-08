#!/usr/bin/env python3
"""Ticket lineage visibility — full history query, sync metadata, deep_sync scope."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import agent_sync_envelope  # noqa: E402
import crowley  # noqa: E402
import handoff_ticket_bridge  # noqa: E402
import tickets  # noqa: E402
from actions_helpers import actions_headers, boot_actions_session  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ACTIONS_KEY = "test-secret"
AUTH_HEADER = actions_headers(ACTIONS_KEY, session="ticket-lineage")


class TicketLineageTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._prior_key = os.environ.get("CROWLEY_ACTION_KEY")
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY
        project = crowley.get_active_project()
        assert project is not None
        self.project_id = int(project["id"])

    def tearDown(self) -> None:
        if self._prior_key is None:
            os.environ.pop("CROWLEY_ACTION_KEY", None)
        else:
            os.environ["CROWLEY_ACTION_KEY"] = self._prior_key
        super().tearDown()

    def _snapshot_open_tickets(self) -> list[dict[str, object]]:
        rows = tickets.list_tickets(project_id=self.project_id, open_only=True, limit=200)
        return [
            {
                "id": int(row["id"]),
                "status": row["status"],
                "assignee": row["assignee"],
                "title": row["title"],
            }
            for row in rows
        ]

    def _read(self, tool: str, args: dict) -> dict:
        with TestClient(crowley_app.app) as client:
            boot_actions_session(client, AUTH_HEADER)
            res = client.post(
                "/api/actions/read",
                headers=AUTH_HEADER,
                json={"tool": tool, "args": args},
            )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_list_oldest_returns_first_created(self) -> None:
        first = tickets.create_ticket(
            "Lineage oldest probe A",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="done",
        )
        second = tickets.create_ticket(
            "Lineage oldest probe B",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="open",
        )
        first_id = int(first["ticket"]["id"])
        second_id = int(second["ticket"]["id"])
        self.assertLess(first_id, second_id)

        oldest = self._read(
            "ticket.list",
            {"status": "all", "sort": "oldest", "limit": 200},
        )
        ids = [int(row["id"]) for row in oldest["items"]]
        self.assertEqual(ids[0], first_id)
        self.assertIn(second_id, ids)

    def test_default_list_open_only_unchanged(self) -> None:
        tickets.create_ticket(
            "Lineage open probe",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="open",
        )
        tickets.create_ticket(
            "Lineage done probe",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="done",
        )
        default_list = self._read("ticket.list", {"limit": 200})
        for row in default_list["items"]:
            self.assertIn(row["status"], {"open", "claimed", "in_progress", "blocked"})
        statuses = {row["status"] for row in default_list["items"]}
        self.assertNotIn("done", statuses)

    def test_build_tickets_summary_lineage(self) -> None:
        tickets.create_ticket(
            "Lineage summary done",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="done",
        )
        tickets.create_ticket(
            "Lineage summary open",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="open",
        )
        summary = tickets.build_tickets_summary(self.project_id, "cursor")
        lineage = summary.get("lineage")
        self.assertIsInstance(lineage, dict)
        assert isinstance(lineage, dict)
        self.assertGreater(int(lineage.get("total") or 0), 0)
        self.assertIsNotNone(lineage.get("first_id"))
        self.assertIsNotNone(lineage.get("first_ticket"))
        counts = summary.get("counts")
        self.assertIsInstance(counts, dict)
        assert isinstance(counts, dict)
        self.assertGreater(int(counts.get("total") or 0), int(counts.get("open") or 0))

    def test_recently_closed_sorted_newest(self) -> None:
        older = tickets.create_ticket(
            "Older closed lineage",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="done",
        )
        newer = tickets.create_ticket(
            "Newer closed lineage",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="done",
        )
        older_id = int(older["ticket"]["id"])
        newer_id = int(newer["ticket"]["id"])
        tickets.update_ticket(older_id, actor="cursor", comment="older close")
        tickets.update_ticket(newer_id, actor="cursor", comment="newer close")
        summary = tickets.build_tickets_summary(self.project_id, closed_limit=10)
        closed = summary.get("recently_closed") or []
        self.assertTrue(closed)
        closed_ids = [int(row["id"]) for row in closed if isinstance(row, dict)]
        self.assertEqual(closed_ids[0], newer_id)

    def test_deep_sync_tickets_default_open_scope(self) -> None:
        tickets.create_ticket(
            "Deep sync open",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="open",
        )
        tickets.create_ticket(
            "Deep sync done",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="done",
        )
        page = agent_sync_envelope.build_deep_sync_page(
            "cursor",
            "tickets",
            limit=50,
        )
        self.assertEqual(page.get("scope"), "open")
        for item in page.get("items") or []:
            self.assertIn(item.get("status"), {"open", "claimed", "in_progress", "blocked"})

    def test_deep_sync_tickets_history_scope(self) -> None:
        created = tickets.create_ticket(
            "History scope probe",
            assignee="cursor",
            source="manual",
            actor="codex",
            project_id=self.project_id,
            status="done",
        )
        first_id = int(created["ticket"]["id"])
        page = agent_sync_envelope.build_deep_sync_page(
            "cursor",
            "tickets",
            scope="history",
            limit=1,
        )
        self.assertEqual(page.get("scope"), "history")
        self.assertGreaterEqual(int(page.get("total") or 0), 1)
        items = page.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(int(items[0]["id"]), first_id)

    def test_open_ticket_regression_after_lineage_reads(self) -> None:
        before = self._snapshot_open_tickets()
        self._read("ticket.list", {"status": "all", "sort": "oldest", "limit": 5})
        self._read("ticket.list", {"status": "all", "sort": "newest", "limit": 5})
        agent_sync_envelope.build_deep_sync_page("cursor", "tickets", scope="history", limit=5)
        tickets.build_tickets_summary(self.project_id, "cursor")
        after = self._snapshot_open_tickets()
        self.assertEqual(before, after)

    def test_next_action_ticket_ref_not_extracted(self) -> None:
        body = (
            "# Crowley Handoff\n\n"
            "## Summary\n- Shipped doc lock.\n\n"
            "## Next Action\n\nResume T15 (#217) after bus restart.\n"
        )
        self.assertEqual(handoff_ticket_bridge.extract_referenced_ticket_ids(body), [])

    def test_context_basis_ticket_ref_still_extracted(self) -> None:
        body = (
            "# Crowley Handoff\n\n"
            "## Summary\n- Shipped.\n\n"
            "## Context Basis\n\n- ticket #131\n\n"
            "## Next Action\n\nResume T15 (#217).\n"
        )
        self.assertEqual(handoff_ticket_bridge.extract_referenced_ticket_ids(body), [131])


if __name__ == "__main__":
    unittest.main()
