#!/usr/bin/env python3
"""V4 T15 — spark confidence decay and re-evaluation tests."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import patterns  # noqa: E402
import spark_lifecycle  # noqa: E402
import spark_retrieval  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from memory_tiers import MIN_CONFIDENCE  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Spark lifecycle decay keeps retrieval honest over time.",
        "lane": "work",
        "why_keep": "Prevents stale sparks from dominating recall.",
        "worth_reason": "Supports V4 confidence decay.",
        "confidence": 0.8,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base

class SparkLifecycleDecayTests(IsolatedDbTestCase):
    def test_decay_factor_matches_formula(self) -> None:
        self.assertEqual(spark_lifecycle.time_decay_factor(0.0), 1.0)
        self.assertAlmostEqual(spark_lifecycle.time_decay_factor(30.0), 0.5)
        self.assertAlmostEqual(spark_lifecycle.time_decay_factor(60.0), 0.25)

    def test_live_confidence_floor(self) -> None:
        live = spark_lifecycle.compute_live_confidence(0.3, 365.0)
        self.assertEqual(live, MIN_CONFIDENCE)

    def test_pattern_boost_applied_and_capped_at_base(self) -> None:
        decayed = spark_lifecycle.compute_live_confidence(0.8, 60.0, pattern_participant=False)
        boosted = spark_lifecycle.compute_live_confidence(0.8, 60.0, pattern_participant=True)
        self.assertAlmostEqual(decayed, 0.2)
        self.assertAlmostEqual(boosted, 0.25)
        self.assertLessEqual(boosted, 0.8)

        nearly_fresh = spark_lifecycle.compute_live_confidence(
            0.8,
            0.0,
            pattern_participant=True,
        )
        self.assertAlmostEqual(nearly_fresh, 0.8)

    def test_days_since_last_access_prefers_last_accessed_at(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = sparks.insert_spark(
                conn,
                _valid_spark(),
                source_memory_item_id=1,
                project_id=None,
                trust_state="active",
            )
            created = "2026-01-01T00:00:00+00:00"
            accessed = "2026-06-01T00:00:00+00:00"
            conn.execute(
                """
                UPDATE sparks
                SET created_at = ?, last_accessed_at = ?
                WHERE id = ?
                """,
                (created, accessed, spark_id),
            )
            row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            assert row is not None
            now = datetime(2026, 7, 1, tzinfo=timezone.utc)
            days = spark_lifecycle.days_since_last_access(row, now=now)
            self.assertAlmostEqual(days, 30.0, places=3)
        finally:
            conn.close()

    def test_pinned_spark_decays_like_any_other(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = sparks.insert_spark(
                conn,
                _valid_spark(confidence=0.8),
                source_memory_item_id=1,
                project_id=None,
                trust_state="pinned",
            )
            conn.execute(
                """
                UPDATE sparks
                SET created_at = ?, base_confidence = 0.8
                WHERE id = ?
                """,
                ("2026-01-01T00:00:00+00:00", spark_id),
            )
            row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            assert row is not None
            now = datetime(2026, 1, 31, tzinfo=timezone.utc)
            live = spark_lifecycle.live_confidence_for_spark(conn, row, now=now)
            self.assertAlmostEqual(live, 0.4)
        finally:
            conn.close()

    def test_retrieval_uses_live_confidence_for_scoring(self) -> None:
        conn = crowley.connect_db()
        try:
            fresh_id = sparks.insert_spark(
                conn,
                _valid_spark(content="fresh decay spark", confidence=0.8),
                source_memory_item_id=1,
                project_id=None,
                trust_state="active",
            )
            stale_id = sparks.insert_spark(
                conn,
                _valid_spark(content="stale decay spark", confidence=0.8),
                source_memory_item_id=1,
                project_id=None,
                trust_state="active",
            )
            stale_created = (
                datetime.now(timezone.utc) - timedelta(days=60)
            ).isoformat()
            conn.execute(
                "UPDATE sparks SET created_at = ?, base_confidence = 0.8 WHERE id = ?",
                (stale_created, stale_id),
            )
            semantic = {fresh_id: 0.5, stale_id: 0.5}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=0.5
            ):
                results = spark_retrieval.retrieve_sparks(
                    "decay spark",
                    conn=conn,
                    bump_access=False,
                )
            by_id = {item.spark_id: item for item in results}
            self.assertGreater(by_id[fresh_id].confidence, by_id[stale_id].confidence)
            self.assertGreater(by_id[fresh_id].score, by_id[stale_id].score)
            stored = conn.execute(
                "SELECT confidence, base_confidence FROM sparks WHERE id = ?",
                (stale_id,),
            ).fetchone()
            assert stored is not None
            self.assertEqual(float(stored["confidence"]), 0.8)
            self.assertEqual(float(stored["base_confidence"]), 0.8)
        finally:
            conn.close()

    def test_access_bump_updates_last_accessed_and_slows_decay(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = sparks.insert_spark(
                conn,
                _valid_spark(content="access slows decay"),
                source_memory_item_id=1,
                project_id=None,
                trust_state="active",
            )
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=60)
            ).isoformat()
            conn.execute(
                """
                UPDATE sparks
                SET created_at = ?, base_confidence = 0.8, last_accessed_at = NULL
                WHERE id = ?
                """,
                (old_created, spark_id),
            )
            row_before = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            assert row_before is not None
            live_before = spark_lifecycle.live_confidence_for_spark(conn, row_before)

            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={spark_id: 0.5}
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                spark_retrieval.retrieve_sparks("access slows decay", conn=conn, limit=1)

            row_after = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            assert row_after is not None
            self.assertIsNotNone(row_after["last_accessed_at"])
            live_after = spark_lifecycle.live_confidence_for_spark(conn, row_after)
            self.assertGreater(live_after, live_before)
        finally:
            conn.close()

    def test_active_pattern_participation_boosts_live_confidence(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = sparks.insert_spark(
                conn,
                _valid_spark(content="pattern boost target", confidence=0.7),
                source_memory_item_id=1,
                project_id=None,
                trust_state="active",
            )
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=60)
            ).isoformat()
            conn.execute(
                "UPDATE sparks SET created_at = ?, base_confidence = 0.7 WHERE id = ?",
                (old_created, spark_id),
            )
            now = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO patterns (
                    content, lane, source_spark_ids_json, reasoning,
                    confidence, trust_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "work: pattern boost target",
                    "work",
                    f"[{spark_id}]",
                    "test fixture",
                    0.7,
                    patterns.PATTERN_ACTIVE_TRUST_STATE,
                    now,
                    now,
                ),
            )

            row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            assert row is not None
            without = spark_lifecycle.compute_live_confidence(
                0.7,
                spark_lifecycle.days_since_last_access(row),
                pattern_participant=False,
            )
            with_boost = spark_lifecycle.live_confidence_for_spark(conn, row)
            self.assertAlmostEqual(without, 0.2)
            self.assertAlmostEqual(with_boost, 0.225)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
