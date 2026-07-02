#!/usr/bin/env python3
"""V3.9.9 post-work feedback loop tests (ticket #60)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS))

import agent_sync_lib as asl  # noqa: E402
import codex_sync as cs  # noqa: E402
import crowley  # noqa: E402
import cursor_sync as curs  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class FeedbackSectionMarkdownTests(unittest.TestCase):
    def test_empty_section_omitted(self) -> None:
        self.assertEqual(asl.feedback_section_markdown("Lessons", []), "")

    def test_non_empty_section_rendered(self) -> None:
        text = asl.feedback_section_markdown(
            "State Changed",
            ["V3.9.9 ticket #60 feedback loop shipped"],
        )
        self.assertIn("## State Changed", text)
        self.assertIn("feedback loop shipped", text)


class CursorSyncFeedbackTests(unittest.TestCase):
    def _content(self, **kwargs: object) -> str:
        defaults = {
            "handoff_type": "builder_handoff",
            "status": "",
            "changed": "",
            "summary": "Feedback loop probe summary for ticket sixty",
            "decisions": [],
            "lessons": [],
            "state_changed": [],
            "next_action": "Continue V3.9.9 context work",
            "do_not_build": [],
            "open_loops": [],
            "qa_results": [],
            "known_issues": [],
        }
        defaults.update(kwargs)
        return curs._section_content(**defaults)  # type: ignore[arg-type]

    def test_includes_lesson_and_state_changed_blocks(self) -> None:
        content = self._content(
            decisions=["Sync handoffs emit structured memory blocks"],
            lessons=["Restart bus after changing sync script output"],
            state_changed=["Ticket #60 post-work feedback loop is in progress"],
        )
        self.assertIn("## Lessons", content)
        self.assertIn("Restart bus after changing sync script output", content)
        self.assertIn("## State Changed", content)
        self.assertIn("Ticket #60 post-work feedback loop", content)
        self.assertIn("## Decisions", content)

    def test_omits_empty_feedback_blocks(self) -> None:
        content = self._content()
        self.assertNotIn("## Lessons", content)
        self.assertNotIn("## State Changed", content)


class CodexSyncFeedbackTests(unittest.TestCase):
    def test_architect_handoff_supports_feedback_blocks(self) -> None:
        content = cs._section_content(
            handoff_type="architect_handoff",
            status="",
            changed="",
            summary="Codex architect feedback loop probe for ticket sixty",
            decisions=["Mint tickets before builder claims work"],
            lessons=["Keep slim sync bundle after bus restart"],
            state_changed=["V3.9.9 planning arc remains active"],
            next_action="Cursor ships ticket #60",
            do_not_build=[],
            open_loops=[],
            qa_results=[],
        )
        self.assertIn("## Lessons", content)
        self.assertIn("slim sync bundle", content)
        self.assertIn("## State Changed", content)


class FeedbackLoopIngestTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def test_cursor_handoff_creates_typed_memories(self) -> None:
        content = curs._section_content(
            handoff_type="builder_handoff",
            status="",
            changed="",
            summary="Post-work feedback loop ingest probe for ticket sixty",
            decisions=["Structured decisions feed gated decision memories"],
            lessons=["Lessons learned feed gated lesson memories on ingest"],
            state_changed=["State changed rows promote as project_update memories"],
            next_action="QA feedback loop ingest paths",
            do_not_build=[],
            open_loops=[],
            qa_results=["unittest feedback loop"],
            known_issues=[],
        )
        result = crowley.ingest_handoff(
            "cursor",
            "builder_handoff",
            content,
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        promoted = result["applied"]["memory_items_promoted"]
        assert isinstance(promoted, dict)
        self.assertGreaterEqual(int(promoted["decision"]), 1)
        self.assertGreaterEqual(int(promoted["lesson"]), 1)
        # State Changed section promotes project_update rows (includes anchor)
        self.assertGreaterEqual(int(promoted.get("project_update", 0)), 1)

    def test_codex_handoff_creates_typed_memories(self) -> None:
        content = cs._section_content(
            handoff_type="architect_handoff",
            status="",
            changed="",
            summary="Codex post-work feedback loop ingest probe for sixty",
            decisions=["Architect decisions promote through ingest gate"],
            lessons=["Codex lessons promote through ingest gate on handoff"],
            state_changed=["Planning state changed to ticket #60 active"],
            next_action="Cursor validates feedback loop",
            do_not_build=[],
            open_loops=[],
            qa_results=["unittest codex feedback"],
        )
        result = crowley.ingest_handoff(
            "codex",
            "architect_handoff",
            content,
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        promoted = result["applied"]["memory_items_promoted"]
        assert isinstance(promoted, dict)
        self.assertGreaterEqual(int(promoted["decision"]), 1)
        self.assertGreaterEqual(int(promoted["lesson"]), 1)

    def test_empty_feedback_blocks_create_no_extra_rows(self) -> None:
        before = self.conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()
        assert before is not None
        before_count = int(before["n"])
        content = curs._section_content(
            handoff_type="builder_handoff",
            status="",
            changed="",
            summary="Empty feedback blocks should not add lesson or state rows",
            decisions=[],
            lessons=[],
            state_changed=[],
            next_action="Continue builder work on ticket sixty",
            do_not_build=[],
            open_loops=[],
            qa_results=[],
            known_issues=[],
        )
        result = crowley.ingest_handoff(
            "cursor",
            "builder_handoff",
            content,
            project=crowley.DEFAULT_PROJECT_SLUG,
        )
        self.assertEqual(result["status"], "ok")
        promoted = result["applied"]["memory_items_promoted"]
        assert isinstance(promoted, dict)
        self.assertEqual(int(promoted["lesson"]), 0)
        lesson_rows = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM memory_items
            WHERE memory_type = 'lesson' AND id > ?
            """,
            (before_count,),
        ).fetchone()
        self.assertEqual(int(lesson_rows["n"]), 0)


if __name__ == "__main__":
    unittest.main()
