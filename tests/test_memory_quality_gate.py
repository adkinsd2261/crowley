#!/usr/bin/env python3
"""V3.9.9 memory quality gate tests (ticket #56)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryQualityGateUnitTests(unittest.TestCase):
    def test_rejects_implicit_event_noise(self) -> None:
        outcome = crowley.evaluate_memory_quality_gate(
            "event",
            "just checking in on the project today",
            source="implicit",
            project_id=1,
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("implicit event", outcome.reason)

    def test_rejects_low_confidence_promoted_memory(self) -> None:
        outcome = crowley.evaluate_memory_quality_gate(
            "decision",
            "Use SQLite for local persistence in Crowley",
            summary="Architecture choice for local-first storage",
            source="codex",
            confidence=0.2,
            project_id=1,
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("confidence", outcome.reason)

    def test_rejects_promoted_memory_without_scope(self) -> None:
        outcome = crowley.evaluate_memory_quality_gate(
            "lesson",
            "Always restart the bus after version bumps",
            summary="Runtime hygiene lesson for release QA",
            source="cursor",
            project_id=None,
        )
        self.assertFalse(outcome.allowed)
        self.assertIn("scope", outcome.reason)

    def test_accepts_promoted_memory_with_metadata(self) -> None:
        outcome = crowley.evaluate_memory_quality_gate(
            "constraint",
            "No direct Codex-to-Cursor communication channel",
            summary="Pipeline stays Crowley-only between agents",
            source="codex",
            importance=4,
            confidence=0.95,
            project_id=1,
        )
        self.assertTrue(outcome.allowed)
        self.assertEqual(outcome.memory_type, "constraint")
        self.assertEqual(outcome.importance, 4)
        self.assertAlmostEqual(outcome.confidence, 0.95)
        self.assertIn("Crowley-only", outcome.summary or "")

    def test_handoff_event_promoted_to_lesson(self) -> None:
        outcome = crowley.evaluate_memory_quality_gate(
            "event",
            (
                "# Crowley Handoff\n\nSource: cursor\nType: note\n\n"
                "## Summary\n\n- Shipped memory quality gate for ticket #56"
            ),
            source="cursor",
            project_id=1,
        )
        self.assertTrue(outcome.allowed)
        self.assertEqual(outcome.memory_type, "lesson")
        self.assertIn("memory quality gate", outcome.content.lower())
        self.assertEqual(outcome.summary, outcome.content)

    def test_extracts_summary_from_handoff_for_project_update(self) -> None:
        outcome = crowley.evaluate_memory_quality_gate(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: cursor\n\n"
                "## Summary\n\n- Runtime hardening complete for V3.9.8"
            ),
            source="cursor",
            project_id=1,
        )
        self.assertTrue(outcome.allowed)
        self.assertIn("Runtime hardening", outcome.summary or "")


class MemoryQualityGateIntegrationTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def test_save_rejects_trim_spark_dual_write(self) -> None:
        legacy_id = crowley.save_memory(
            "spark",
            "hey there just saying hello to the workspace today",
            crowley.SPARK_IMPORTANCE_TRIM,
            conn=self.conn,
            dual_write=True,
        )
        self.assertGreater(legacy_id, 0)
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM memory_items
            WHERE legacy_memory_id = ?
            """,
            (legacy_id,),
        ).fetchone()
        self.assertEqual(int(row["n"]), 0)

    def test_save_allows_summary_spark_dual_write(self) -> None:
        content = (
            "We decided to gate memory saves so only high-value typed memories "
            "enter memory_items with explicit why_it_matters metadata."
        )
        legacy_id = crowley.save_memory(
            "spark",
            content,
            crowley.SPARK_IMPORTANCE_SUMMARY,
            conn=self.conn,
            dual_write=True,
        )
        self.assertGreater(legacy_id, 0)
        row = self.conn.execute(
            """
            SELECT memory_type, content FROM memory_items
            WHERE legacy_memory_id = ?
            """,
            (legacy_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row["memory_type"]), "summary")
        self.assertIn("why_it_matters", str(row["content"]).lower())

    def test_ingest_handoff_saves_gated_project_update(self) -> None:
        result = crowley.ingest_handoff(
            "cursor",
            "builder_handoff",
            (
                "# Crowley Handoff\n\nSource: cursor\nType: builder_handoff\n\n"
                "## Summary\n\n- Memory quality gate shipped for ticket #56\n\n"
                "## Next Action\n\n- Mr. Go QA gate behavior"
            ),
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        mem_id = result.get("memory_item_id")
        self.assertIsNotNone(mem_id)
        assert mem_id is not None
        row = self.conn.execute(
            """
            SELECT memory_type, summary, importance, confidence, project_id
            FROM memory_items WHERE id = ?
            """,
            (mem_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(str(row["memory_type"]), "project_update")
        self.assertIn("quality gate", str(row["summary"]).lower())
        self.assertGreaterEqual(int(row["importance"]), 1)
        self.assertLessEqual(int(row["importance"]), 5)
        self.assertGreaterEqual(float(row["confidence"]), 0.5)
        self.assertLessEqual(float(row["confidence"]), 1.0)
        self.assertEqual(int(row["project_id"]), self.project_id)

    def test_ingest_note_not_saved_as_raw_event(self) -> None:
        result = crowley.ingest_handoff(
            "cursor",
            "note",
            (
                "# Crowley Handoff\n\nSource: cursor\nType: note\n\n"
                "## Summary\n\n- Gate rejects raw handoff event rows"
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
        self.assertEqual(str(row["memory_type"]), "lesson")
        self.assertNotIn("# Crowley Handoff", str(row["content"]))
        self.assertIn("raw handoff event", str(row["summary"]).lower())

    def test_rejects_generic_promoted_content(self) -> None:
        item_id = crowley.save_memory_item(
            "decision",
            "continue working",
            summary="continue working",
            source="codex",
            project_id=self.project_id,
        )
        self.assertIsNone(item_id)


if __name__ == "__main__":
    unittest.main()
