#!/usr/bin/env python3
"""V3.9.9 handoff-to-memory upgrade tests (ticket #59)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class HandoffMemoryUpgradeTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def _memory_rows_for_source(self, source: str = "cursor") -> list:
        return self.conn.execute(
            """
            SELECT id, memory_type, content, summary
            FROM memory_items
            WHERE source = ? AND project_id = ?
            ORDER BY id ASC
            """,
            (source, self.project_id),
        ).fetchall()

    def test_decisions_section_creates_gated_decision_memories(self) -> None:
        result = crowley.ingest_handoff(
            "codex",
            "architect_handoff",
            (
                "# Crowley Handoff\n\nSource: codex\nType: architect_handoff\n\n"
                "## Summary\n\n- Approved handoff memory upgrade for ticket #59\n\n"
                "## Decisions\n\n"
                "- No direct Codex-to-Cursor communication channel\n"
                "- Memory sections promote through quality gate on ingest\n\n"
                "## Next Action\n\n- Cursor implements ticket #59"
            ),
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        promoted = result["applied"]["memory_items_promoted"]
        assert isinstance(promoted, dict)
        self.assertEqual(int(promoted["decision"]), 2)
        self.assertEqual(int(promoted["constraint"]), 0)

        decision_rows = self.conn.execute(
            """
            SELECT content, summary FROM memory_items
            WHERE memory_type = 'decision' AND source = 'codex'
            ORDER BY id ASC
            """
        ).fetchall()
        self.assertEqual(len(decision_rows), 2)
        self.assertIn("Codex-to-Cursor", str(decision_rows[0]["content"]))
        self.assertIsNotNone(decision_rows[0]["summary"])
        self.assertIn("quality gate", str(decision_rows[1]["content"]).lower())

    def test_constraints_and_lessons_sections_create_typed_rows(self) -> None:
        result = crowley.ingest_handoff(
            "cursor",
            "builder_handoff",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- Handoff section parsing ships for ticket #59\n\n"
                "## Constraints\n\n"
                "- Restart bus after version bumps so health matches constants\n\n"
                "## Lessons\n\n"
                "- Slim sync bundle requires bus restart to pick up API shape\n"
            ),
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        promoted = result["applied"]["memory_items_promoted"]
        assert isinstance(promoted, dict)
        self.assertEqual(int(promoted["constraint"]), 1)
        self.assertEqual(int(promoted["lesson"]), 1)

        rows = self._memory_rows_for_source("cursor")
        types = {str(row["memory_type"]) for row in rows}
        self.assertIn("constraint", types)
        self.assertIn("lesson", types)
        for row in rows:
            if str(row["memory_type"]) in {"constraint", "lesson"}:
                self.assertIsNotNone(row["summary"])
                self.assertGreaterEqual(len(str(row["summary"])), 8)

    def test_bulk_handoff_body_not_saved_when_sections_extracted(self) -> None:
        result = crowley.ingest_handoff(
            "cursor",
            "builder_handoff",
            (
                "# Crowley Handoff\n\nSource: cursor\nType: builder_handoff\n\n"
                "## Summary\n\n- Anchor summary only for ticket #59 bulk guard\n\n"
                "## Decisions\n\n"
                "- Promote typed memories instead of full handoff prose\n\n"
                "## Next Action\n\n- QA handoff ingest paths"
            ),
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        mem_id = result.get("memory_item_id")
        self.assertIsNotNone(mem_id)
        assert mem_id is not None
        anchor = self.conn.execute(
            "SELECT memory_type, content FROM memory_items WHERE id = ?",
            (mem_id,),
        ).fetchone()
        self.assertIsNotNone(anchor)
        assert anchor is not None
        self.assertEqual(str(anchor["memory_type"]), "project_update")
        self.assertNotIn("# Crowley Handoff", str(anchor["content"]))
        self.assertIn("Anchor summary only", str(anchor["content"]))

        full_body_rows = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM memory_items
            WHERE content LIKE '%## Next Action%'
              AND content LIKE '%# Crowley Handoff%'
            """
        ).fetchone()
        self.assertEqual(int(full_body_rows["n"]), 0)

    def test_generic_decision_bullet_rejected_by_gate(self) -> None:
        result = crowley.ingest_handoff(
            "codex",
            "architect_handoff",
            (
                "# Crowley Handoff\n\nSource: codex\n\n"
                "## Summary\n\n- Gate reject path for generic decision bullets\n\n"
                "## Decisions\n\n- continue working\n\n"
                "## Next Action\n\n- verify reject path"
            ),
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        promoted = result["applied"]["memory_items_promoted"]
        assert isinstance(promoted, dict)
        self.assertEqual(int(promoted["decision"]), 0)
        skipped = result.get("skipped")
        assert isinstance(skipped, list)
        self.assertTrue(any("continue working" in str(item) for item in skipped))

    def test_handoff_without_typed_sections_keeps_summary_project_update(self) -> None:
        result = crowley.ingest_handoff(
            "cursor",
            "builder_handoff",
            (
                "# Crowley Handoff\n\nSource: cursor\nType: builder_handoff\n\n"
                "## Summary\n\n- Legacy handoff path without typed sections\n\n"
                "## Next Action\n\n- QA unchanged ingest behavior"
            ),
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        mem_id = result.get("memory_item_id")
        self.assertIsNotNone(mem_id)
        assert mem_id is not None
        row = self.conn.execute(
            "SELECT memory_type, content, summary FROM memory_items WHERE id = ?",
            (mem_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row["memory_type"]), "project_update")
        self.assertIn("# Crowley Handoff", str(row["content"]))
        self.assertIn("legacy handoff path", str(row["summary"]).lower())


if __name__ == "__main__":
    unittest.main()
