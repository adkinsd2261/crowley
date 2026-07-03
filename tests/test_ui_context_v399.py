#!/usr/bin/env python3
"""V3.9.9 #62 — light UI inclusion_reason badges and hygiene report."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class UiContextV399Tests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_world_dashboard_includes_relevant_memories_with_reason(self) -> None:
        crowley.save_memory_item(
            "decision",
            "UI context probe decision for agent feed wiring",
            source="cursor",
            project_id=self.project_id,
            summary="Why agent feed needs inclusion badges",
            importance=4,
            confidence=0.9,
        )
        dash = crowley.build_world_dashboard()
        memories = dash.get("relevant_memories")
        self.assertIsInstance(memories, list)
        self.assertGreaterEqual(len(memories), 1)
        first = memories[0]
        self.assertIn("inclusion_reason", first)
        self.assertTrue(str(first["inclusion_reason"]).startswith("Pulled because:"))

    def test_hygiene_report_includes_stale_loops_and_version_conflicts(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Hygiene loop probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.complete_ticket(ticket_id, actor="cursor")
        loop_id = crowley.save_open_loop(
            self.project_id,
            f"Follow up on closed ticket #{ticket_id}",
        )
        conflict_id = crowley.save_memory_item(
            "summary",
            "We shipped version 100.0 today",
            source="cursor",
            project_id=self.project_id,
            importance=3,
            confidence=0.8,
        )
        self.assertIsNotNone(conflict_id)

        report = crowley.memory_hygiene_report()
        loop_ids = {int(item["id"]) for item in report.get("stale_loops", [])}
        self.assertIn(int(loop_id), loop_ids)
        conflict_ids = {int(item["id"]) for item in report.get("version_conflicts", [])}
        self.assertIn(int(conflict_id), conflict_ids)
        self.assertTrue(report.get("dry_run"))
        counts = report.get("counts")
        assert isinstance(counts, dict)
        self.assertGreaterEqual(int(counts.get("stale_loops", 0)), 1)
        self.assertGreaterEqual(int(counts.get("version_conflicts", 0)), 1)

    def test_hygiene_report_makes_no_writes(self) -> None:
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
        ).fetchone()["n"]
        crowley.memory_hygiene_report()
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
        ).fetchone()["n"]
        self.assertEqual(before, after)

    def test_static_assets_include_inclusion_and_hygiene_ui(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("memory-hygiene-callout", html)
        self.assertIn("panel-agent-brief", html)
        self.assertIn("agent-supporting-count", html)
        self.assertIn("renderTaskFrameBrief", js)
        self.assertIn("inclusionReasonBadge", js)
        self.assertIn("renderAgentFeedMemories", js)
        self.assertIn("loadHygieneCallout", js)
        self.assertIn("/api/retrieve", js)
        self.assertIn("memoryDisplayLine", js)
        self.assertIn("inclusion-factor", css)
        self.assertIn("hygiene-callout", css)

    def test_ticket_aware_retrieval_query_includes_open_tickets(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "UI hygiene inclusion badge probe unique",
                assignee="cursor",
                project_id=self.project_id,
                priority=1,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- Ticket #62 light UI hygiene report shipped inclusion badges"
            ),
            source="cursor",
            project_id=self.project_id,
            importance=4,
            confidence=0.9,
        )

        query, seeds = crowley.build_ticket_aware_retrieval_query(
            self.project_id,
            "cursor",
        )
        self.assertIn(f"ticket #{ticket_id}", query)
        self.assertIn("UI hygiene inclusion badge probe", query)
        seed_ids = {int(item["id"]) for item in seeds}
        self.assertIn(ticket_id, seed_ids)

        context = crowley.retrieve_work_context_memories(
            self.project_id,
            "cursor",
            limit=6,
        )
        self.assertIn("tickets", context)
        self.assertIn("memories", context)
        self.assertIn(f"ticket #{ticket_id}", str(context["query"]))

    def test_world_dashboard_exposes_retrieval_ticket_scope(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Dashboard retrieval scope probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")
        dash = crowley.build_world_dashboard()
        scoped = dash.get("relevant_memories_tickets")
        self.assertIsInstance(scoped, list)
        self.assertGreaterEqual(len(scoped), 1)
        self.assertIn(ticket_id, {int(item["id"]) for item in scoped})
        self.assertIn(f"ticket #{ticket_id}", str(dash.get("relevant_memories_query", "")))


class HygieneApiAliasTests(unittest.TestCase):
    def test_app_exposes_hygiene_alias_route(self) -> None:
        app_py = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/api/hygiene")', app_py)
        self.assertIn('@app.get("/api/memory/hygiene")', app_py)


if __name__ == "__main__":
    unittest.main()
