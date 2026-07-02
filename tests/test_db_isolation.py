#!/usr/bin/env python3
"""Guard tests for isolated unittest database setup."""

from __future__ import annotations

import sqlite3
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import isolated_db  # noqa: E402


def _count_memory_items_matching(path: Path, needle: str) -> int:
    if not path.is_file():
        return 0
    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM memory_items WHERE content LIKE ?",
            (f"%{needle}%",),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


class DbIsolationGuardTests(unittest.TestCase):
    def test_isolated_db_path_differs_from_working_db(self) -> None:
        with isolated_db() as db_path:
            self.assertNotEqual(
                db_path.resolve(),
                crowley.DEFAULT_DB_PATH.resolve(),
            )
        self.assertEqual(
            crowley.get_db_path().resolve(),
            crowley.DEFAULT_DB_PATH.resolve(),
        )

    def test_isolated_writes_do_not_touch_working_db(self) -> None:
        needle = f"db isolation guard {uuid.uuid4()}"
        working = crowley.DEFAULT_DB_PATH
        before = _count_memory_items_matching(working, needle)

        with isolated_db():
            conn = crowley.connect_db()
            project_id = crowley._active_project_id(conn)
            assert project_id is not None
            now = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO memory_items (
                    created_at, updated_at, project_id, memory_type, content, summary,
                    importance, source, pinned, status, confidence
                ) VALUES (?, ?, ?, 'event', ?, NULL, 1, 'cursor', 0, 'active', 0.8)
                """,
                (now, now, project_id, needle),
            )
            conn.commit()
            conn.close()

        after = _count_memory_items_matching(working, needle)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
