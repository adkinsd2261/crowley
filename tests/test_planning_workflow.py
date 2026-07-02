#!/usr/bin/env python3
"""V3.9.3 planning workflow doc tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "V3.9.3_PLANNING_WORKFLOW.md"
WHERE_WE_ARE = ROOT / "docs" / "WHERE_WE_ARE.md"


class PlanningWorkflowDocTests(unittest.TestCase):
    def test_planning_workflow_doc_exists(self) -> None:
        self.assertTrue(DOC.is_file(), msg="missing docs/V3.9.3_PLANNING_WORKFLOW.md")

    def test_where_we_are_links_planning_workflow_in_rituals(self) -> None:
        text = WHERE_WE_ARE.read_text(encoding="utf-8")
        rituals_idx = text.find("## 4. Agent rituals")
        self.assertGreaterEqual(rituals_idx, 0)
        rituals_section = text[rituals_idx : rituals_idx + 600]
        self.assertIn("V3.9.3_PLANNING_WORKFLOW.md", rituals_section)

    def test_doc_covers_roles_and_cursor_ready_tickets(self) -> None:
        content = DOC.read_text(encoding="utf-8")
        lower = content.lower()
        self.assertIn("mr. go", lower)
        self.assertIn("codex", lower)
        self.assertIn("cursor", lower)
        self.assertIn("crowley", lower)
        self.assertIn("cursor-ready", lower)
        self.assertIn("acceptance criteria", lower)
        self.assertIn("non-goals", lower)
        self.assertIn("qa expectation", lower)

    def test_doc_does_not_imply_direct_codex_cursor_messaging(self) -> None:
        content = DOC.read_text(encoding="utf-8").lower()
        self.assertIn("only hub", content)
        self.assertIn("do not message each other directly", content)


if __name__ == "__main__":
    unittest.main()
