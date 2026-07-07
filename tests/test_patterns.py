#!/usr/bin/env python3
"""V4 T11 — pattern detection and creation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import patterns  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Pattern detection keeps related sparks grouped.",
        "lane": "work",
        "why_keep": "Shows repeated cognitive structure.",
        "worth_reason": "Supports deterministic pattern creation.",
        "confidence": 0.7,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


def _unit_vector(axis: int = 0) -> list[float]:
    vector = [0.0] * crowley.EMBED_DIM
    vector[axis] = 1.0
    return vector


class PatternTests(IsolatedDbTestCase):
    def _insert(
        self,
        conn,
        *,
        content: str,
        lane: str = "work",
        confidence: float = 0.7,
        trust_state: str = "active",
        vector: list[float] | None = None,
    ) -> int:
        spark_id = sparks.insert_spark(
            conn,
            _valid_spark(content=content, lane=lane, confidence=confidence),
            source_memory_item_id=1,
            project_id=None,
            trust_state=trust_state,
        )
        if vector is not None:
            sparks.index_spark_embedding(conn, spark_id, vector, "test-model")
        return spark_id

    def _pattern_row(self, conn, pattern_id: int):
        return conn.execute(
            "SELECT * FROM patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()

    def test_pattern_created_from_valid_cluster(self) -> None:
        conn = crowley.connect_db()
        try:
            vec = _unit_vector()
            ids = [
                self._insert(conn, content="charlie pattern spark", vector=vec),
                self._insert(conn, content="alpha pattern spark", vector=vec),
                self._insert(conn, content="bravo pattern spark", vector=vec),
            ]

            result = patterns.create_pattern_from_sparks(conn, ids)

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.action, "created")
            assert result.pattern_id is not None
            row = self._pattern_row(conn, result.pattern_id)
            assert row is not None
            self.assertEqual(row["lane"], "work")
            self.assertEqual(row["trust_state"], patterns.PATTERN_TRUST_STATE_CANDIDATE)
            self.assertEqual(
                row["source_spark_ids_json"],
                f"[{ids[0]},{ids[1]},{ids[2]}]",
            )
            self.assertEqual(row["reasoning"], "3 sparks, avg_conf=0.70, min_sim=1.00")
            self.assertEqual(
                row["content"],
                "work: alpha pattern spark; bravo pattern spark; charlie pattern spark",
            )
            self.assertEqual(float(row["confidence"]), 0.7)
        finally:
            conn.close()

    def test_below_min_sparks_rejected_after_filtering(self) -> None:
        conn = crowley.connect_db()
        try:
            vec = _unit_vector()
            first = self._insert(conn, content="valid one", vector=vec)
            second = self._insert(conn, content="valid two", vector=vec)
            rejected = self._insert(
                conn, content="rejected three", trust_state="rejected", vector=vec
            )

            result = patterns.create_pattern_from_sparks(
                conn,
                [first, first, second, rejected, 999999],
            )

            self.assertFalse(result.ok)
            self.assertIn("not enough", result.errors[0])
        finally:
            conn.close()

    def test_below_avg_confidence_rejected(self) -> None:
        conn = crowley.connect_db()
        try:
            vec = _unit_vector()
            ids = [
                self._insert(conn, content="low conf one", confidence=0.5, vector=vec),
                self._insert(conn, content="low conf two", confidence=0.6, vector=vec),
                self._insert(conn, content="low conf three", confidence=0.6, vector=vec),
            ]

            result = patterns.create_pattern_from_sparks(conn, ids)

            self.assertFalse(result.ok)
            self.assertIn("confidence", result.errors[0])
        finally:
            conn.close()

    def test_mixed_lane_cluster_rejected(self) -> None:
        conn = crowley.connect_db()
        try:
            vec = _unit_vector()
            ids = [
                self._insert(conn, content="work lane one", lane="work", vector=vec),
                self._insert(conn, content="work lane two", lane="work", vector=vec),
                self._insert(
                    conn, content="learning lane three", lane="learning", vector=vec
                ),
            ]

            result = patterns.create_pattern_from_sparks(conn, ids)

            self.assertFalse(result.ok)
            self.assertIn("lane", result.errors[0])
        finally:
            conn.close()

    def test_strict_pairwise_similarity_rejected(self) -> None:
        conn = crowley.connect_db()
        try:
            ids = [
                self._insert(conn, content="similar one", vector=_unit_vector(0)),
                self._insert(conn, content="similar two", vector=_unit_vector(0)),
                self._insert(conn, content="dissimilar three", vector=_unit_vector(1)),
            ]

            result = patterns.create_pattern_from_sparks(conn, ids)

            self.assertFalse(result.ok)
            self.assertIn("similarity", result.errors[0])
        finally:
            conn.close()

    def test_missing_embedding_rejected(self) -> None:
        conn = crowley.connect_db()
        try:
            vec = _unit_vector()
            ids = [
                self._insert(conn, content="embedded one", vector=vec),
                self._insert(conn, content="embedded two", vector=vec),
                self._insert(conn, content="missing embedding"),
            ]

            result = patterns.create_pattern_from_sparks(conn, ids)

            self.assertFalse(result.ok)
            self.assertIn("embeddings", result.errors[0])
        finally:
            conn.close()

    def test_duplicate_source_cluster_returns_existing(self) -> None:
        conn = crowley.connect_db()
        try:
            vec = _unit_vector()
            ids = [
                self._insert(conn, content="duplicate one", vector=vec),
                self._insert(conn, content="duplicate two", vector=vec),
                self._insert(conn, content="duplicate three", vector=vec),
            ]

            first = patterns.create_pattern_from_sparks(conn, ids)
            second = patterns.create_pattern_from_sparks(conn, list(reversed(ids)))

            self.assertTrue(first.ok, first.errors)
            self.assertTrue(second.ok, second.errors)
            self.assertEqual(second.action, "existing")
            self.assertEqual(first.pattern_id, second.pattern_id)
            row = conn.execute("SELECT COUNT(*) AS n FROM patterns").fetchone()
            assert row is not None
            self.assertEqual(int(row["n"]), 1)
        finally:
            conn.close()

    def test_source_index_exists(self) -> None:
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'index'
                  AND name = 'idx_patterns_sources'
                """
            ).fetchone()

            self.assertIsNotNone(row)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
