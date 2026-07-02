#!/usr/bin/env python3
"""V3.9.2 memory hygiene dry-run tests."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryHygieneTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        self.created_ids: list[int] = []

    def tearDown(self) -> None:
        if self.created_ids:
            self.conn.executemany(
                "DELETE FROM memory_items WHERE id = ?",
                [(item_id,) for item_id in self.created_ids],
            )
            self.conn.commit()
        self.conn.close()
        super().tearDown()

    def _insert(
        self,
        *,
        content: str,
        memory_type: str = "event",
        source: str = "cursor",
        importance: int = 3,
        created_at: str | None = None,
    ) -> int:
        now = created_at or crowley._now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, 0, 'active', 0.8)
            """,
            (
                now,
                now,
                self.project_id,
                memory_type,
                content,
                importance,
                source,
            ),
        )
        self.conn.commit()
        item_id = int(cur.lastrowid)
        self.created_ids.append(item_id)
        return item_id

    def test_hygiene_groups_candidates_without_mutation(self) -> None:
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=crowley.MEMORY_STALE_AGE_DAYS + 2)
        ).isoformat()
        stale_id = self._insert(
            content="stale low importance probe",
            source="implicit",
            importance=1,
            created_at=old_ts,
        )
        duplicate_old_id = self._insert(content="duplicate probe row")
        duplicate_new_id = self._insert(content="duplicate probe row")
        noisy_id = self._insert(content="tiny note", source="extract", importance=1)
        conflict_a_id = self._insert(
            content="Prefer use dark mode for coding sessions",
            memory_type="preference",
        )
        conflict_b_id = self._insert(
            content="Prefer avoid dark mode for coding sessions",
            memory_type="preference",
        )

        before_status = {
            int(row["id"]): str(row["status"])
            for row in self.conn.execute(
                "SELECT id, status FROM memory_items WHERE id IN (?, ?, ?, ?, ?, ?)",
                (
                    stale_id,
                    duplicate_old_id,
                    duplicate_new_id,
                    noisy_id,
                    conflict_a_id,
                    conflict_b_id,
                ),
            ).fetchall()
        }

        report = crowley.memory_hygiene_report()
        self.assertTrue(bool(report["dry_run"]))
        self.assertIn("counts", report)

        stale_ids = {int(item["id"]) for item in report["stale"]}
        duplicate_ids = {int(item["id"]) for item in report["duplicates"]}
        noisy_ids = {int(item["id"]) for item in report["noisy"]}
        conflict_ids = {int(item["id"]) for item in report["possible_conflicts"]}

        self.assertIn(stale_id, stale_ids)
        self.assertIn(duplicate_old_id, duplicate_ids)
        self.assertNotIn(duplicate_new_id, duplicate_ids)
        self.assertIn(noisy_id, noisy_ids)
        self.assertIn(conflict_a_id, conflict_ids)
        self.assertIn(conflict_b_id, conflict_ids)

        after_status = {
            int(row["id"]): str(row["status"])
            for row in self.conn.execute(
                "SELECT id, status FROM memory_items WHERE id IN (?, ?, ?, ?, ?, ?)",
                (
                    stale_id,
                    duplicate_old_id,
                    duplicate_new_id,
                    noisy_id,
                    conflict_a_id,
                    conflict_b_id,
                ),
            ).fetchall()
        }
        self.assertEqual(before_status, after_status)

    def test_hygiene_api_wrapper_returns_grouped_payload(self) -> None:
        payload = crowley.memory_hygiene_report_api()
        for key in ("stale", "noisy", "duplicates", "possible_conflicts", "counts"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
