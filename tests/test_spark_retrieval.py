#!/usr/bin/env python3
"""V4 T8 — spark retrieval and canonical scoring tests."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import spark_retrieval  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Deterministic spark retrieval uses canonical scoring.",
        "lane": "work",
        "why_keep": "Keeps recall predictable across sessions.",
        "worth_reason": "Supports V4 cognitive context assembly.",
        "confidence": 0.5,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


def _pack_vec(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def _unit_vector(axis: int = 0) -> list[float]:
    vector = [0.0] * crowley.EMBED_DIM
    vector[axis] = 1.0
    return vector


class SparkRetrievalTests(IsolatedDbTestCase):
    def _insert(
        self,
        conn,
        spark: dict[str, object] | None = None,
        *,
        trust_state: str = "active",
        project_id: int | None = None,
    ) -> int:
        return sparks.insert_spark(
            conn,
            spark or _valid_spark(),
            source_memory_item_id=1,
            project_id=project_id,
            trust_state=trust_state,
        )

    def test_rank_ordering_matches_formula(self) -> None:
        conn = crowley.connect_db()
        try:
            low_id = self._insert(
                conn,
                _valid_spark(content="alpha retrieval scoring", confidence=0.2),
            )
            high_id = self._insert(
                conn,
                _valid_spark(content="beta retrieval scoring", confidence=0.9),
            )
            semantic = {low_id: 0.2, high_id: 0.8}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ):
                results = spark_retrieval.retrieve_sparks(
                    "retrieval scoring",
                    conn=conn,
                    bump_access=False,
                )
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].spark_id, high_id)
            self.assertGreater(results[0].score, results[1].score)
            expected_high = round(
                0.40 * 0.8 + 0.25 * 0.9 + 0.15 * results[0].score_breakdown["recency"],
                4,
            )
            self.assertEqual(results[0].score, expected_high)
        finally:
            conn.close()

    def test_determinism_same_inputs(self) -> None:
        conn = crowley.connect_db()
        try:
            self._insert(conn, _valid_spark(content="deterministic recall spark"))
            with mock.patch.object(crowley, "embed_text", return_value=None):
                first = spark_retrieval.retrieve_sparks("deterministic", conn=conn, bump_access=False)
                second = spark_retrieval.retrieve_sparks("deterministic", conn=conn, bump_access=False)
            self.assertEqual([r.spark_id for r in first], [r.spark_id for r in second])
            self.assertEqual([r.score for r in first], [r.score for r in second])
        finally:
            conn.close()

    def test_access_count_incremented(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, _valid_spark(content="access bump spark"))
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={spark_id: 0.5}
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                spark_retrieval.retrieve_sparks("access", conn=conn, limit=1)
            row = conn.execute(
                "SELECT access_count, last_accessed_at FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertEqual(int(row["access_count"]), 1)
            self.assertIsNotNone(row["last_accessed_at"])
        finally:
            conn.close()

    def test_rejected_sparks_excluded(self) -> None:
        conn = crowley.connect_db()
        try:
            rejected_id = self._insert(
                conn, _valid_spark(content="rejected spark"), trust_state="rejected"
            )
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores",
                return_value={rejected_id: 0.9},
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks("rejected", conn=conn, bump_access=False)
            self.assertEqual(results, [])
        finally:
            conn.close()

    def test_semantic_blob_fallback(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, _valid_spark(content="blob fallback semantic"))
            vector = _unit_vector()
            sparks.index_spark_embedding(conn, spark_id, vector, "test-model")
            with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                with mock.patch.object(crowley, "embed_text", return_value=vector):
                    results = spark_retrieval.retrieve_sparks(
                        "blob fallback semantic",
                        conn=conn,
                        bump_access=False,
                    )
            self.assertEqual(len(results), 1)
            self.assertGreater(results[0].score_breakdown["semantic"], 0.0)
        finally:
            conn.close()

    def test_graph_reinforcement_incoming_link(self) -> None:
        conn = crowley.connect_db()
        try:
            keeper = self._insert(conn, _valid_spark(content="keeper graph spark", confidence=0.5))
            other = self._insert(conn, _valid_spark(content="other graph spark", confidence=0.5))
            conn.execute(
                """
                INSERT INTO spark_links (
                    from_spark_id, to_spark_id, link_type, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    other,
                    keeper,
                    sparks.SPARK_LINK_TYPE_REINFORCES,
                    0.9,
                    crowley._now_iso(),
                    crowley._now_iso(),
                ),
            )
            scores = {keeper: 0.1, other: 0.1}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=scores
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks("graph", conn=conn, bump_access=False)
            by_id = {r.spark_id: r for r in results}
            self.assertGreater(
                by_id[keeper].score_breakdown["graph_reinforcement"],
                by_id[other].score_breakdown["graph_reinforcement"],
            )
            self.assertEqual(by_id[keeper].score_breakdown["graph_reinforcement"], 0.9)
        finally:
            conn.close()

    def test_graph_reinforcement_null_returns_zero(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, _valid_spark(content="no links spark"))
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={spark_id: 0.5}
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks("no links", conn=conn, bump_access=False)
            self.assertEqual(results[0].score_breakdown["graph_reinforcement"], 0.0)
        finally:
            conn.close()

    def test_tie_break_by_id_asc(self) -> None:
        conn = crowley.connect_db()
        try:
            first = self._insert(conn, _valid_spark(content="tie alpha", confidence=0.5))
            second = self._insert(conn, _valid_spark(content="tie beta", confidence=0.5))
            scores = {first: 0.5, second: 0.5}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=scores
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ):
                results = spark_retrieval.retrieve_sparks("tie", conn=conn, bump_access=False)
            self.assertEqual(results[0].spark_id, min(first, second))
            self.assertEqual(results[0].score, results[1].score)
        finally:
            conn.close()

    def test_keyword_pool_semantic_floor(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, _valid_spark(content="keyword floor unique term"))
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval,
                "_spark_keyword_candidate_scores",
                return_value={spark_id: 0.6},
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "keyword floor unique term",
                    conn=conn,
                    bump_access=False,
                )
            self.assertEqual(results[0].score_breakdown["semantic"], spark_retrieval.SPARK_KEYWORD_SEMANTIC_FLOOR)
        finally:
            conn.close()

    def test_pinned_always_in_pool(self) -> None:
        conn = crowley.connect_db()
        try:
            pinned_id = self._insert(
                conn,
                _valid_spark(content="pinned invisible otherwise"),
                trust_state="pinned",
            )
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ):
                results = spark_retrieval.retrieve_sparks(
                    "unrelated query xyz",
                    conn=conn,
                    bump_access=False,
                )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].spark_id, pinned_id)
        finally:
            conn.close()

    def test_semantic_clamped_range(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, _valid_spark(content="clamp semantic spark"))
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={spark_id: 1.5}
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=-0.2
            ):
                results = spark_retrieval.retrieve_sparks("clamp", conn=conn, bump_access=False)
            self.assertEqual(results[0].score_breakdown["semantic"], 1.0)
            self.assertEqual(results[0].score_breakdown["graph_reinforcement"], 0.0)
            self.assertLessEqual(results[0].score, 1.0)
            self.assertGreaterEqual(results[0].score, 0.0)
        finally:
            conn.close()

    def test_candidate_deduplication(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, _valid_spark(content="dedupe candidate spark"))
            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value={spark_id: 0.7},
            ), mock.patch.object(
                spark_retrieval,
                "_spark_keyword_candidate_scores",
                return_value={spark_id: 0.4},
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "dedupe candidate",
                    conn=conn,
                    bump_access=False,
                )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].spark_id, spark_id)
            self.assertEqual(results[0].score_breakdown["semantic"], 0.7)
        finally:
            conn.close()

    def test_lane_filter(self) -> None:
        conn = crowley.connect_db()
        try:
            work_id = self._insert(
                conn, _valid_spark(content="lane work spark", lane="work")
            )
            self._insert(
                conn, _valid_spark(content="lane health spark", lane="health")
            )
            scores = {work_id: 0.8}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=scores
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "lane",
                    lanes=frozenset({"work"}),
                    conn=conn,
                    bump_access=False,
                )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].spark_id, work_id)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
