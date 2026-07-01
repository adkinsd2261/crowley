#!/usr/bin/env python3
"""V3.6 Phase 4 / V3.7.3 memory consolidation tests — no live model calls."""

from __future__ import annotations

import struct
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


def _unit_embedding(dim: int = crowley.EMBED_DIM) -> list[float]:
    vector = [0.0] * dim
    vector[0] = 1.0
    return vector


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class MemoryConsolidationTests(unittest.TestCase):
    def setUp(self) -> None:
        crowley.setup_db()
        self.conn = crowley.connect_db()

    def tearDown(self) -> None:
        if self.conn is not None:
            self.conn.close()

    def _insert_item(
        self,
        *,
        content: str,
        source: str = "implicit",
        memory_type: str = "event",
        importance: int = 1,
        created_at: str | None = None,
        embedding: list[float] | None = None,
        pinned: bool = False,
    ) -> int:
        now = created_at or crowley._now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence, embedding_blob
            ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, 'active', 0.75, ?)
            """,
            (
                now,
                now,
                crowley._active_project_id(self.conn),
                memory_type,
                content,
                importance,
                source,
                1 if pinned else 0,
                _pack(embedding) if embedding else None,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def test_duplicate_merge_marks_older_item(self) -> None:
        vector = _unit_embedding()
        keep_id = self._insert_item(
            content="QA consolidation duplicate keep probe",
            embedding=vector,
        )
        merge_id = self._insert_item(
            content="QA consolidation duplicate merge probe",
            embedding=vector,
        )
        result = crowley.run_duplicate_merge(self.conn)
        self.assertGreaterEqual(int(result["merged"]), 1)
        self.conn.commit()
        older_id = min(keep_id, merge_id)
        newer_id = max(keep_id, merge_id)
        row = self.conn.execute(
            "SELECT status, merged_into_id FROM memory_items WHERE id = ?",
            (older_id,),
        ).fetchone()
        assert row is not None
        self.assertEqual(str(row["status"]), "merged")
        self.assertEqual(int(row["merged_into_id"]), newer_id)

    def test_stale_marking_flags_old_low_importance_items(self) -> None:
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=crowley.MEMORY_STALE_AGE_DAYS + 1)
        ).isoformat()
        item_id = self._insert_item(
            content="QA stale consolidation probe",
            importance=1,
            created_at=old_ts,
        )
        result = crowley.run_stale_marking(self.conn)
        self.assertIn(item_id, result["candidate_ids"])
        row = self.conn.execute(
            "SELECT status FROM memory_items WHERE id = ?", (item_id,)
        ).fetchone()
        assert row is not None
        self.assertEqual(str(row["status"]), "stale")

    def test_session_merge_supersedes_implicit_events(self) -> None:
        base = datetime.now(timezone.utc)
        first_summary_ts = (base - timedelta(hours=2)).isoformat()
        implicit_ts = (base - timedelta(hours=1)).isoformat()
        summary_ts = base.isoformat()
        self._insert_item(
            content="older session summary",
            source="session_summary",
            memory_type="summary",
            importance=2,
            created_at=first_summary_ts,
        )
        implicit_id = self._insert_item(
            content="trim implicit event for merge probe",
            source="implicit",
            memory_type="event",
            created_at=implicit_ts,
        )
        summary_id = self._insert_item(
            content="newer session summary supersedes trim events",
            source="session_summary",
            memory_type="summary",
            importance=2,
            created_at=summary_ts,
        )
        merged = crowley.merge_implicit_since_session_summary(self.conn, summary_id)
        self.assertGreaterEqual(merged, 1)
        row = self.conn.execute(
            "SELECT status, merged_into_id FROM memory_items WHERE id = ?",
            (implicit_id,),
        ).fetchone()
        assert row is not None
        self.assertEqual(str(row["status"]), "merged")
        self.assertEqual(int(row["merged_into_id"]), summary_id)

    def test_consolidate_dry_run_records_no_audit_row(self) -> None:
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM memory_consolidation_runs"
        ).fetchone()["n"]
        result = crowley.consolidate_memories("stale", dry_run=True)
        self.assertTrue(result["dry_run"])
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM memory_consolidation_runs"
        ).fetchone()["n"]
        self.assertEqual(before, after)

    def test_retrieve_skips_merged_items(self) -> None:
        vector = _unit_embedding()
        keep_id = self._insert_item(
            content="retrieve skip merged keep probe unique phrase alpha",
            embedding=vector,
        )
        merge_id = self._insert_item(
            content="retrieve skip merged merge probe unique phrase alpha",
            embedding=vector,
        )
        crowley.run_duplicate_merge(self.conn)
        self.conn.commit()
        project_id = crowley._active_project_id(self.conn)
        self.conn.close()
        self.conn = None  # type: ignore[assignment]
        results = crowley.retrieve_memories(
            "unique phrase alpha", limit=20, project_id=project_id
        )
        ids = {int(item["id"]) for item in results}
        self.assertIn(max(keep_id, merge_id), ids)
        self.assertNotIn(min(keep_id, merge_id), ids)


if __name__ == "__main__":
    unittest.main()
