#!/usr/bin/env python3
"""Memory trail, canon read path, and canon synthesis tests."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import synthesize_canon  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


VALID_CANON_OUTPUT = """
## Canon: Project
Crowley is the local AI operating system. Evidence: docs/PROJECT_STATE.md, project_state:1.

## Canon: Agents
Codex plans and Cursor builds through Crowley only. Evidence: memory_items:85.

## Canon: Decisions
Crowley remains the only hub. Evidence: decision:31.

## Canon: Work
Current work is memory continuity. Evidence: memory_items:85, docs/TICKETS.md.

## Canon: Mr. Go
Mr. Go prefers continuity over manual relay. Evidence: memory_items:85.

## Canon: Recent
Recent sessions wired agent sync and canon planning. Evidence: memory_items:87.
"""


class MemoryTrailTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        self.created_ids: list[int] = []

    def tearDown(self) -> None:
        if self.created_ids:
            marks = ",".join("?" for _ in self.created_ids)
            self.conn.execute(
                f"DELETE FROM memory_items WHERE id IN ({marks})",
                self.created_ids,
            )
            self.conn.commit()
        self.conn.close()
        super().tearDown()

    def _insert_memory(
        self,
        *,
        content: str,
        source: str = "manual",
        memory_type: str = "event",
        status: str = "active",
        pinned: bool = False,
    ) -> int:
        now = crowley._now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence
            ) VALUES (?, ?, ?, ?, ?, NULL, 3, ?, ?, ?, 0.9)
            """,
            (
                now,
                now,
                self.project_id,
                memory_type,
                content,
                source,
                1 if pinned else 0,
                status,
            ),
        )
        item_id = int(cur.lastrowid)
        self.created_ids.append(item_id)
        self.conn.commit()
        return item_id

    def test_world_dashboard_reports_real_memory_counts(self) -> None:
        dash = crowley.build_world_dashboard()
        counts = dash["counts"]
        status_counts = crowley.count_memory_items_by_status()
        active_total = int(status_counts.get("active", 0))
        total = sum(status_counts.values())
        self.assertEqual(counts["memory"], active_total)
        self.assertEqual(counts["memory_active"], active_total)
        self.assertEqual(counts["memory_total"], total)
        self.assertEqual(counts["memory_displayed"], len(dash["memory_items"]))

    def test_list_memory_items_filters_and_paginates(self) -> None:
        unique = "QA memory trail filter alpha"
        self._insert_memory(content=unique, source="manual", memory_type="lesson")
        self._insert_memory(
            content="QA memory trail filter beta",
            source="codex",
            memory_type="event",
            status="archived",
        )
        rows, total = crowley.list_memory_items(
            q="filter alpha",
            source="manual",
            memory_type="lesson",
            status="active",
            limit=10,
            offset=0,
        )
        self.assertGreaterEqual(total, 1)
        self.assertTrue(any(unique in str(row["content"]) for row in rows))
        archived_rows, archived_total = crowley.list_memory_items(
            q="filter beta",
            status="archived",
            limit=10,
            offset=0,
        )
        self.assertGreaterEqual(archived_total, 1)
        self.assertTrue(any(str(row["status"]) == "archived" for row in archived_rows))

    def test_ui_contains_memory_filter_controls(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="memory-count-summary"', html)
        self.assertIn('id="memory-search"', html)
        self.assertIn('id="memory-layer"', html)
        self.assertIn("memory-hierarchy-note", html)
        self.assertIn("formatMemoryCounts", js)
        self.assertIn("memoryLayerBadge", js)
        self.assertIn("active /", js)

    def test_ui_renders_assistant_markdown(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("renderMarkdown", js)
        self.assertIn("message-body prose", js)
        self.assertIn("message-expand", js)

    def test_canon_is_separate_from_agent_events(self) -> None:
        canon_id = self._insert_memory(
            content="Canon: Project\n\nQA canon memory_items:85 docs/PROJECT_STATE.md",
            source="crowley",
            memory_type="summary",
            pinned=True,
        )
        canon_rows = crowley.list_canon_memory_items(self.project_id)
        self.assertIn(canon_id, {int(row["id"]) for row in canon_rows})

        context = crowley.build_context_bundle(q="QA canon", limit=1)
        self.assertIn(canon_id, {int(item["id"]) for item in context["canon"]})
        self.assertIn("last_by_source", context["agent_activity"])

        sync = crowley.build_agent_sync_bundle(agent="cursor", limit=20)
        self.assertEqual(sync.get("bundle_shape"), "task_frame_v3910")
        self.assertNotIn("canon", sync)
        self.assertNotIn("open_loops", sync)
        self.assertNotIn("open_tasks", sync)
        self.assertIn("last_by_source", sync["agent_activity"])
        event_ids = {
            int(item["id"])
            for item in [
                *sync["events_from_other_agents"],
                *sync["events_from_this_agent"],
            ]
        }
        self.assertNotIn(canon_id, event_ids)

    def test_agent_sync_includes_role_and_pipeline(self) -> None:
        sync = crowley.build_agent_sync_bundle(agent="cursor", limit=5)
        self.assertIn("builder", sync["role"].lower())
        self.assertIn("you are not crowley", sync["role"].lower())
        self.assertEqual(sync["pipeline"]["hub"], "crowley")
        self.assertIn("architect", sync["pipeline"]["codex"])

        codex_sync = crowley.build_agent_sync_bundle(agent="codex", limit=5)
        self.assertIn("architect", codex_sync["role"].lower())
        self.assertIn("builder", codex_sync["pipeline"]["cursor"])

    def test_crowley_prompt_includes_agent_activity(self) -> None:
        self._insert_memory(
            content=(
                "# Crowley Handoff\n\nSource: cursor\nType: note\n\n"
                "## Summary\n\n- QA agent wiring probe unique phrase zeta"
            ),
            source="cursor",
            memory_type="event",
        )
        system = crowley.build_prompt("when did you last hear from cursor?")[0]["content"]
        self.assertIn("Agent activity", system)
        self.assertIn("cursor", system.lower())
        self.assertIn("QA agent wiring probe unique phrase zeta", system)

    def test_agent_activity_summary_last_contact(self) -> None:
        self._insert_memory(
            content=(
                "# Crowley Handoff\n\nSource: cursor\nType: note\n\n"
                "## Summary\n\n- last contact probe alpha"
            ),
            source="cursor",
            memory_type="event",
        )
        summary = crowley._agent_activity_summary(self.project_id)
        self.assertIn("cursor", summary["last_by_source"])
        self.assertIn("last contact probe alpha", str(summary["last_by_source"]["cursor"]["summary"]))

    def test_agent_activity_includes_next_action(self) -> None:
        self._insert_memory(
            content=(
                "# Crowley Handoff\n\nSource: codex\nType: architect_handoff\n\n"
                "## Summary\n\n- Planning slice approved\n\n"
                "## Next Action\n\n- Cursor starts ticket #19"
            ),
            source="codex",
            memory_type="project_update",
        )
        summary = crowley._agent_activity_summary(self.project_id)
        codex = summary["last_by_source"].get("codex")
        self.assertIsNotNone(codex)
        assert codex is not None
        self.assertEqual(codex.get("next_action"), "Cursor starts ticket #19")
        recent = summary.get("recent")
        assert isinstance(recent, list)
        self.assertGreaterEqual(len(recent), 1)
        self.assertEqual(recent[0].get("next_action"), "Cursor starts ticket #19")

    def test_agent_activity_links_closed_ticket_handoff(self) -> None:
        ticket_id = crowley.create_ticket(
            "Activity ticket link probe",
            assignee="cursor",
            project_id=self.project_id,
        )["ticket"]["id"]
        mem_id = crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- activity ticket cross-reference probe"
            ),
            source="cursor",
            project_id=self.project_id,
        )
        self.assertIsNotNone(mem_id)
        assert mem_id is not None
        crowley.update_ticket(
            int(ticket_id),
            actor="cursor",
            status="done",
            linked_memory_id=mem_id,
        )
        summary = crowley._agent_activity_summary(self.project_id)
        recent = summary.get("recent")
        assert isinstance(recent, list)
        match = next((item for item in recent if int(item["id"]) == mem_id), None)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertIn(int(ticket_id), match.get("linked_ticket_ids", []))

    def test_crowley_prompt_anchors_system_identity(self) -> None:
        system = crowley.build_prompt("what are you?")[0]["content"]
        self.assertIn("running system on this machine", system)
        self.assertIn("Codex architects", system)
        self.assertIn("Cursor builds", system)

    def test_prompt_places_canon_between_knowledge_and_retrieval(self) -> None:
        self._insert_memory(
            content="Canon: Project\n\nQA prompt canon memory_items:85 docs/PROJECT_STATE.md",
            source="crowley",
            memory_type="summary",
            pinned=True,
        )
        original_embed = crowley.embed_text
        crowley.embed_text = lambda _text: None  # type: ignore[assignment]
        try:
            system = crowley.build_prompt("QA prompt canon")[0]["content"]
        finally:
            crowley.embed_text = original_embed  # type: ignore[assignment]

        knowledge_idx = system.find(
            "Filesystem truth (primary readout — read before DB state and memory):"
        )
        canon_idx = system.find("Canonical memory trail:")
        memory_idx = system.find(
            "Supporting memory (hybrid retrieval — lower authority than filesystem truth):"
        )
        self.assertGreaterEqual(knowledge_idx, 0)
        self.assertGreaterEqual(canon_idx, 0)
        self.assertGreaterEqual(memory_idx, 0)
        self.assertLess(knowledge_idx, canon_idx)
        self.assertLess(canon_idx, memory_idx)


class SynthesizeCanonTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_slug = "qa-canon-test"
        now = crowley._now_iso()
        self.conn.execute(
            "DELETE FROM memory_items WHERE project_id IN (SELECT id FROM projects WHERE slug = ?)",
            (self.project_slug,),
        )
        self.conn.execute("DELETE FROM project_state WHERE project_id IN (SELECT id FROM projects WHERE slug = ?)", (self.project_slug,))
        self.conn.execute("DELETE FROM projects WHERE slug = ?", (self.project_slug,))
        cur = self.conn.execute(
            """
            INSERT INTO projects (name, slug, status, description, created_at, updated_at)
            VALUES ('QA Canon', ?, 'test', 'QA canon project', ?, ?)
            """,
            (self.project_slug, now, now),
        )
        self.project_id = int(cur.lastrowid)
        self.conn.execute(
            """
            INSERT INTO project_state (
                project_id, phase, focus, current_risk, next_action, what_changed,
                updated_at, updated_by
            ) VALUES (?, 'QA', 'Canon tests', '', 'Run tests', '', ?, 'test')
            """,
            (self.project_id, now),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.execute("DELETE FROM memory_items WHERE project_id = ?", (self.project_id,))
        self.conn.execute("DELETE FROM project_state WHERE project_id = ?", (self.project_id,))
        self.conn.execute("DELETE FROM projects WHERE id = ?", (self.project_id,))
        self.conn.commit()
        self.conn.close()
        super().tearDown()

    def _model(self, _messages: list[dict[str, str]]) -> str:
        return VALID_CANON_OUTPUT

    def test_dry_run_writes_nothing(self) -> None:
        before = int(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()["n"]
        )
        result = synthesize_canon.synthesize_canon(
            project_slug=self.project_slug,
            write=False,
            model_func=self._model,
        )
        after = int(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()["n"]
        )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["dry_run"])
        self.assertEqual(before, after)

    def test_write_archives_old_and_inserts_six(self) -> None:
        now = crowley._now_iso()
        self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence
            ) VALUES (?, ?, ?, 'summary', 'Canon: Project\n\nold memory_items:1', 'Canon: Project', 5, 'crowley', 1, 'active', 0.95)
            """,
            (now, now, self.project_id),
        )
        self.conn.commit()
        result = synthesize_canon.synthesize_canon(
            project_slug=self.project_slug,
            write=True,
            model_func=self._model,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["inserted"], 6)
        active = int(
            self.conn.execute(
                """
                SELECT COUNT(*) AS n FROM memory_items
                WHERE project_id = ? AND source = 'crowley' AND pinned = 1
                  AND status = 'active' AND content LIKE 'Canon:%'
                """,
                (self.project_id,),
            ).fetchone()["n"]
        )
        archived = int(
            self.conn.execute(
                """
                SELECT COUNT(*) AS n FROM memory_items
                WHERE project_id = ? AND source = 'crowley' AND pinned = 1
                  AND status = 'archived' AND content LIKE 'Canon:%'
                """,
                (self.project_id,),
            ).fetchone()["n"]
        )
        self.assertEqual(active, 6)
        self.assertEqual(archived, 1)

    def test_invalid_output_fails_closed(self) -> None:
        result = synthesize_canon.synthesize_canon(
            project_slug=self.project_slug,
            write=True,
            model_func=lambda _messages: "## Canon: Project\nNo evidence.",
        )
        self.assertEqual(result["status"], "error")
        count = int(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE project_id = ?",
                (self.project_id,),
            ).fetchone()["n"]
        )
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
