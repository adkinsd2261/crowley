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
                (
                    0.40 * 0.8
                    + 0.25 * 0.9
                    + 0.15 * results[0].score_breakdown["recency"]
                )
                * results[0].score_breakdown["certainty_multiplier"],
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

    def test_retrieve_sparks_does_not_auto_infer_lanes(self) -> None:
        """Direct retrieve_sparks(lanes=None) must not auto-infer (Codex #359)."""
        conn = crowley.connect_db()
        try:
            money_id = self._insert(
                conn,
                _valid_spark(content="insurance payment spark", lane="money"),
            )
            health_id = self._insert(
                conn,
                _valid_spark(content="knee therapy spark", lane="health"),
            )
            captured: dict[str, object] = {}

            def _semantic(conn_arg, embedding, limit, *, project_id, lanes):
                captured["lanes"] = lanes
                return {money_id: 0.9, health_id: 0.95}

            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                side_effect=_semantic,
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "What am I paying for insurance and subscriptions?",
                    lanes=None,
                    conn=conn,
                    bump_access=False,
                )
            self.assertIsNone(captured.get("lanes"))
            ids = {item.spark_id for item in results}
            self.assertIn(money_id, ids)
            self.assertIn(health_id, ids)
        finally:
            conn.close()

    def test_filter_before_score_receives_inferred_money_lanes(self) -> None:
        """Prove orchestration applies inferred money lanes into candidate helpers."""
        conn = crowley.connect_db()
        try:
            money_id = self._insert(
                conn,
                _valid_spark(content="car insurance payment", lane="money"),
            )
            health_id = self._insert(
                conn,
                _valid_spark(content="physical therapy for knee", lane="health"),
            )
            seen_lanes: list[frozenset[str] | None] = []

            def _semantic(conn_arg, embedding, limit, *, project_id, lanes):
                seen_lanes.append(lanes)
                if lanes and "money" in lanes and "health" not in lanes:
                    return {money_id: 0.5}
                return {money_id: 0.5, health_id: 0.99}

            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                side_effect=_semantic,
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                payload = __import__(
                    "context_orchestration", fromlist=["build_cognitive_context"]
                ).build_cognitive_context(
                    "What am I paying for insurance and subscriptions?",
                    conn=conn,
                    debug=True,
                )
            self.assertTrue(seen_lanes)
            self.assertEqual(seen_lanes[0], frozenset({"money"}))
            returned = {
                int(item["id"] if "id" in item else item.get("spark_id", -1))
                for item in payload["core_sparks"] + payload["supporting_sparks"]
            }
            # Prefer checking lane field from payload sparks.
            lanes = {
                str(item["lane"])
                for item in payload["core_sparks"] + payload["supporting_sparks"]
            }
            self.assertEqual(lanes, {"money"})
            self.assertEqual(payload["trace"]["lane_source"], "inferred")
        finally:
            conn.close()

    def test_cross_domain_inferred_keeps_both_lanes(self) -> None:
        conn = crowley.connect_db()
        try:
            money_id = self._insert(
                conn, _valid_spark(content="budget insurance note", lane="money")
            )
            health_id = self._insert(
                conn, _valid_spark(content="therapy sleep note", lane="health")
            )
            seen: list[frozenset[str] | None] = []

            def _semantic(conn_arg, embedding, limit, *, project_id, lanes):
                seen.append(lanes)
                return {money_id: 0.8, health_id: 0.8}

            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                side_effect=_semantic,
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                payload = __import__(
                    "context_orchestration", fromlist=["build_cognitive_context"]
                ).build_cognitive_context(
                    "finance and health costs this month",
                    conn=conn,
                    debug=True,
                )
            self.assertEqual(seen[0], frozenset({"health", "money"}))
            lanes = {
                str(item["lane"])
                for item in payload["core_sparks"] + payload["supporting_sparks"]
            }
            self.assertEqual(lanes, {"health", "money"})
            self.assertEqual(payload["trace"]["lanes_used"], ["health", "money"])
        finally:
            conn.close()

    def test_secondary_lane_boost_not_filter_bypass(self) -> None:
        conn = crowley.connect_db()
        try:
            # Primary work with secondary money must NOT enter a money-only filter.
            work_id = self._insert(
                conn,
                _valid_spark(
                    content="work note with money secondary",
                    lane="work",
                    secondary_lanes=["money"],
                ),
            )
            # Primary money with secondary work: admitted by money+work filter and boosted.
            money_id = self._insert(
                conn,
                _valid_spark(
                    content="money note with work secondary",
                    lane="money",
                    secondary_lanes=["work"],
                    confidence=0.5,
                ),
            )
            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value={work_id: 0.99, money_id: 0.5},
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                money_only = spark_retrieval.retrieve_sparks(
                    "money",
                    lanes=frozenset({"money"}),
                    conn=conn,
                    bump_access=False,
                )
            self.assertEqual([item.spark_id for item in money_only], [money_id])
            # Money-only filter does not intersect secondary=["work"] → no boost.
            self.assertEqual(money_only[0].score_breakdown["secondary_lane_boost"], 1.0)

            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value={work_id: 0.99, money_id: 0.5},
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                multi = spark_retrieval.retrieve_sparks(
                    "money work",
                    lanes=frozenset({"money", "work"}),
                    conn=conn,
                    bump_access=False,
                )
            by_id = {item.spark_id: item for item in multi}
            self.assertIn(money_id, by_id)
            self.assertIn(work_id, by_id)
            self.assertEqual(
                by_id[money_id].score_breakdown["secondary_lane_boost"],
                spark_retrieval.SECONDARY_LANE_SCORE_BOOST,
            )
            self.assertEqual(
                by_id[work_id].score_breakdown["secondary_lane_boost"],
                spark_retrieval.SECONDARY_LANE_SCORE_BOOST,
            )

            # Without filter, boost stays 1.0.
            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value={work_id: 0.7},
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                unfiltered = spark_retrieval.retrieve_sparks(
                    "work",
                    lanes=None,
                    conn=conn,
                    bump_access=False,
                )
            work_hit = next(item for item in unfiltered if item.spark_id == work_id)
            self.assertEqual(work_hit.score_breakdown["secondary_lane_boost"], 1.0)
        finally:
            conn.close()

    def test_recall_profile_matches_legacy_none_and_recall(self) -> None:
        """query_mode=None and recall must match pre-profile formula bit-for-bit."""
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(
                conn,
                _valid_spark(
                    content="legacy recall scoring fixture",
                    confidence=0.7,
                    certainty="confirmed",
                ),
            )
            semantic = {spark_id: 0.8}
            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value=semantic,
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=0.5
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.1
            ):
                none_results = spark_retrieval.retrieve_sparks(
                    "legacy",
                    conn=conn,
                    bump_access=False,
                    query_mode=None,
                )
                recall_results = spark_retrieval.retrieve_sparks(
                    "legacy",
                    conn=conn,
                    bump_access=False,
                    query_mode="recall",
                )
            self.assertEqual(len(none_results), 1)
            self.assertEqual(none_results[0].score, recall_results[0].score)
            expected = round(
                (
                    0.40 * 0.8
                    + 0.25 * none_results[0].confidence
                    + 0.15 * 0.5
                    + 0.20 * 0.1
                )
                * none_results[0].score_breakdown["certainty_multiplier"]
                * none_results[0].score_breakdown["secondary_lane_boost"]
                * none_results[0].score_breakdown["trust_multiplier"]
                * none_results[0].score_breakdown["spark_type_boost"],
                4,
            )
            self.assertEqual(none_results[0].score, expected)
            self.assertEqual(none_results[0].score_profile, "recall")
            self.assertEqual(none_results[0].score_breakdown["w_semantic"], 0.4)
            self.assertEqual(none_results[0].score_breakdown["trust_multiplier"], 1.0)
            self.assertEqual(none_results[0].score_breakdown["spark_type_boost"], 1.0)
        finally:
            conn.close()

    def test_invalid_query_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            spark_retrieval.resolve_scoring_profile("precise")
        conn = crowley.connect_db()
        try:
            with self.assertRaises(ValueError):
                spark_retrieval.retrieve_sparks(
                    "q",
                    conn=conn,
                    bump_access=False,
                    query_mode="typo",
                )
        finally:
            conn.close()

    def test_planning_boosts_recency_and_decision_type(self) -> None:
        conn = crowley.connect_db()
        try:
            recent_decision = self._insert(
                conn,
                _valid_spark(
                    content="recent decision spark for planning",
                    confidence=0.5,
                    spark_type="decision",
                    certainty="confirmed",
                ),
            )
            stale_fact = self._insert(
                conn,
                _valid_spark(
                    content="older fact spark for planning",
                    confidence=0.5,
                    spark_type="fact",
                    certainty="confirmed",
                ),
            )
            # Force equal semantic; planning should prefer decision type + higher recency.
            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value={recent_decision: 0.6, stale_fact: 0.6},
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval,
                "_spark_recency_score",
                side_effect=lambda row: 0.9
                if int(row["id"]) == recent_decision
                else 0.1,
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ):
                planning = spark_retrieval.retrieve_sparks(
                    "plan next steps",
                    conn=conn,
                    bump_access=False,
                    query_mode="planning",
                )
                recall = spark_retrieval.retrieve_sparks(
                    "plan next steps",
                    conn=conn,
                    bump_access=False,
                    query_mode="recall",
                )
            self.assertEqual(planning[0].spark_id, recent_decision)
            self.assertEqual(planning[0].score_profile, "planning")
            self.assertEqual(planning[0].score_breakdown["w_recency"], 0.3)
            self.assertEqual(planning[0].score_breakdown["spark_type_boost"], 1.08)
            # Under recall, type boost is neutral; ordering may still favor recency
            # but planning score for decision type should exceed recall for same row.
            plan_by_id = {item.spark_id: item for item in planning}
            recall_by_id = {item.spark_id: item for item in recall}
            self.assertGreater(
                plan_by_id[recent_decision].score,
                recall_by_id[recent_decision].score,
            )
        finally:
            conn.close()

    def test_confirmed_outranks_tentative_equal_semantic(self) -> None:
        conn = crowley.connect_db()
        try:
            confirmed_id = self._insert(
                conn,
                _valid_spark(
                    content="confirmed certainty spark",
                    confidence=0.6,
                    certainty="confirmed",
                ),
            )
            tentative_id = self._insert(
                conn,
                _valid_spark(
                    content="tentative certainty spark",
                    confidence=0.6,
                    certainty="tentative",
                ),
            )
            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value={confirmed_id: 0.7, tentative_id: 0.7},
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ), mock.patch.object(
                spark_retrieval, "_spark_recency_score", return_value=0.4
            ), mock.patch.object(
                spark_retrieval, "_spark_graph_reinforcement", return_value=0.0
            ):
                for mode in ("recall", "planning"):
                    results = spark_retrieval.retrieve_sparks(
                        "certainty",
                        conn=conn,
                        bump_access=False,
                        query_mode=mode,
                    )
                    self.assertEqual(results[0].spark_id, confirmed_id, mode)
                    self.assertGreater(results[0].score, results[1].score, mode)
        finally:
            conn.close()

    def test_score_breakdown_documents_profile_weights(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, _valid_spark(content="breakdown docs"))
            with mock.patch.object(
                spark_retrieval,
                "_spark_semantic_candidate_scores",
                return_value={spark_id: 0.5},
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "breakdown",
                    conn=conn,
                    bump_access=False,
                    query_mode="decision",
                )
            breakdown = results[0].score_breakdown
            for key in (
                "w_semantic",
                "w_confidence",
                "w_recency",
                "w_graph",
                "trust_multiplier",
                "spark_type_boost",
                "certainty_multiplier",
                "secondary_lane_boost",
            ):
                self.assertIn(key, breakdown)
                self.assertIsInstance(breakdown[key], float)
            self.assertNotIn("profile", breakdown)
            self.assertEqual(results[0].score_profile, "decision")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
