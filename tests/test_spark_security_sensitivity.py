#!/usr/bin/env python3
"""V4 T18 — spark sensitivity exposure gate tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import spark_retrieval  # noqa: E402
import spark_security  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Sensitivity gates protect cross-lane spark exposure.",
        "lane": "work",
        "why_keep": "Prevents wrong-lane recall of sensitive sparks.",
        "worth_reason": "Required for V4 spark security.",
        "confidence": 0.9,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


class SparkSecuritySensitivityTests(IsolatedDbTestCase):
    def _insert(
        self,
        conn,
        *,
        lane: str = "work",
        sensitivity: str = "normal",
        confidence: float = 0.9,
        content: str = "sensitivity gate retrieval content",
    ) -> int:
        return sparks.insert_spark(
            conn,
            _valid_spark(
                content=content,
                lane=lane,
                confidence=confidence,
                sensitivity=sensitivity,
            ),
            source_memory_item_id=1,
            project_id=None,
            trust_state="active",
        )

    def test_sensitive_hidden_without_lane_filter(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, sensitivity="sensitive")
            semantic = {spark_id: 0.9}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=1.0
            ):
                results = spark_retrieval.retrieve_sparks(
                    "sensitivity gate retrieval",
                    conn=conn,
                    lanes=None,
                    bump_access=False,
                )
            self.assertEqual(results, [])
        finally:
            conn.close()

    def test_sensitive_visible_with_matching_lane(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, sensitivity="sensitive", lane="work")
            semantic = {spark_id: 0.9}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=1.0
            ):
                results = spark_retrieval.retrieve_sparks(
                    "sensitivity gate retrieval",
                    conn=conn,
                    lanes=frozenset({"work"}),
                    bump_access=False,
                )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].spark_id, spark_id)
        finally:
            conn.close()

    def test_high_hidden_without_lane_filter(self) -> None:
        allowed = spark_security.spark_exposure_allowed(
            sensitivity="high",
            spark_lane="work",
            query_lanes=None,
            depth="medium",
            score=0.95,
        )
        self.assertFalse(allowed)

    def test_high_hidden_at_or_below_score_threshold(self) -> None:
        self.assertFalse(
            spark_security.spark_exposure_allowed(
                sensitivity="high",
                spark_lane="work",
                query_lanes=frozenset({"work"}),
                depth="medium",
                score=0.7,
            )
        )
        self.assertFalse(
            spark_security.spark_exposure_allowed(
                sensitivity="high",
                spark_lane="work",
                query_lanes=frozenset({"work"}),
                depth="medium",
                score=0.65,
            )
        )

    def test_high_visible_above_threshold_with_lane_at_medium_depth(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(
                conn,
                sensitivity="high",
                lane="work",
                confidence=0.95,
            )
            semantic = {spark_id: 0.95}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=1.0
            ):
                results = spark_retrieval.retrieve_sparks(
                    "sensitivity gate retrieval",
                    conn=conn,
                    lanes=frozenset({"work"}),
                    depth="medium",
                    bump_access=False,
                )
            self.assertEqual(len(results), 1)
            self.assertGreater(results[0].score, 0.7)
        finally:
            conn.close()

    def test_high_hidden_at_light_depth_even_with_lane_and_score(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(
                conn,
                sensitivity="high",
                lane="work",
                confidence=0.95,
            )
            semantic = {spark_id: 0.95}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=1.0
            ):
                results = spark_retrieval.retrieve_sparks(
                    "sensitivity gate retrieval",
                    conn=conn,
                    lanes=frozenset({"work"}),
                    depth="light",
                    bump_access=False,
                )
            self.assertEqual(results, [])
        finally:
            conn.close()

    def test_filtered_spark_does_not_bump_access(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, sensitivity="sensitive", lane="work")
            semantic = {spark_id: 0.9}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=1.0
            ):
                spark_retrieval.retrieve_sparks(
                    "sensitivity gate retrieval",
                    conn=conn,
                    lanes=None,
                    bump_access=True,
                )
            row = conn.execute(
                "SELECT access_count FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertEqual(int(row["access_count"]), 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
