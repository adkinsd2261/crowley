#!/usr/bin/env python3
"""V3.9.2 memory hierarchy language tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryHierarchyTests(IsolatedDbTestCase):
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

    def _insert(
        self,
        *,
        content: str,
        source: str = "cursor",
        memory_type: str = "event",
        pinned: bool = False,
    ) -> int:
        now = crowley._now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence
            ) VALUES (?, ?, ?, ?, ?, NULL, 3, ?, ?, 'active', 0.9)
            """,
            (
                now,
                now,
                self.project_id,
                memory_type,
                content,
                source,
                1 if pinned else 0,
            ),
        )
        self.conn.commit()
        item_id = int(cur.lastrowid)
        self.created_ids.append(item_id)
        return item_id

    def test_memory_item_api_dict_labels_layers(self) -> None:
        canon_id = self._insert(
            content="Canon: Project\n\nHierarchy probe docs/MEMORY_HIERARCHY.md",
            source="crowley",
            memory_type="summary",
            pinned=True,
        )
        pinned_id = self._insert(content="Pinned note hierarchy probe", pinned=True)
        ordinary_id = self._insert(content="Ordinary memory hierarchy probe")

        rows = {
            int(row["id"]): row
            for row in self.conn.execute(
                "SELECT * FROM memory_items WHERE id IN (?, ?, ?)",
                (canon_id, pinned_id, ordinary_id),
            ).fetchall()
        }

        canon = crowley._memory_item_api_dict(rows[canon_id])
        pinned = crowley._memory_item_api_dict(rows[pinned_id])
        ordinary = crowley._memory_item_api_dict(rows[ordinary_id])

        self.assertTrue(canon["is_canon"])
        self.assertEqual(canon["memory_layer"], "canon")
        self.assertFalse(pinned["is_canon"])
        self.assertEqual(pinned["memory_layer"], "pinned")
        self.assertFalse(ordinary["is_pinned"])
        self.assertEqual(ordinary["memory_layer"], "memory")

    def test_canon_prompt_copy_does_not_outrank_filesystem_or_tickets(self) -> None:
        section = crowley._format_canon_prompt_section([])
        lower = section.lower()
        self.assertIn("filesystem truth", lower)
        self.assertIn("tickets", lower)
        self.assertIn("outrank canon", lower)

    def test_ground_truth_prompt_lists_full_hierarchy(self) -> None:
        prompt = crowley._ground_truth_prompt()
        self.assertIn("filesystem truth first", prompt.lower())
        self.assertIn("then tickets", prompt.lower())
        self.assertIn("then agent activity", prompt.lower())
        self.assertIn("then live db state", prompt.lower())
        self.assertIn("then canon", prompt.lower())
        self.assertIn("hybrid retrieval", prompt.lower())


if __name__ == "__main__":
    unittest.main()
