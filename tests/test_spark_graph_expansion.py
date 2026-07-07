#!/usr/bin/env python3
"""V4 T10 — spark graph expansion and pruning tests."""

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
import spark_graph  # noqa: E402
import spark_retrieval  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Graph expansion keeps cognitive context bounded.",
        "lane": "work",
        "why_keep": "Prevents noisy graph traversal during retrieval.",
        "worth_reason": "Supports deterministic context assembly.",
        "confidence": 0.5,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


class SparkGraphExpansionTests(IsolatedDbTestCase):
    def _insert(
        self,
        conn,
        *,
        content: str,
        confidence: float = 0.5,
        lane: str = "work",
        trust_state: str = "active",
        project_id: int | None = None,
    ) -> int:
        return sparks.insert_spark(
            conn,
            _valid_spark(content=content, confidence=confidence, lane=lane),
            source_memory_item_id=1,
            project_id=project_id,
            trust_state=trust_state,
        )

    def _link(self, conn, from_id: int, to_id: int, confidence: float) -> int:
        result = spark_graph.create_spark_link(
            conn,
            from_id,
            to_id,
            sparks.SPARK_LINK_TYPE_REINFORCES,
            explicit_reinforcement=True,
            confidence=confidence,
        )
        self.assertTrue(result.ok, result.errors)
        assert result.link_id is not None
        return result.link_id

    def test_expansion_bounded_to_max_nodes(self) -> None:
        conn = crowley.connect_db()
        try:
            ids = [
                self._insert(conn, content=f"bounded chain spark {i}")
                for i in range(60)
            ]
            for left, right in zip(ids, ids[1:]):
                self._link(conn, left, right, 0.8)

            result = spark_graph.expand_spark_graph(
                conn,
                [ids[0]],
                max_hops=100,
                max_nodes=spark_graph.SPARK_GRAPH_MAX_NODES,
            )

            self.assertEqual(result.visited_count, spark_graph.SPARK_GRAPH_MAX_NODES)
            self.assertEqual(len(result.hop_distance), spark_graph.SPARK_GRAPH_MAX_NODES)
            self.assertNotIn(ids[50], result.hop_distance)
        finally:
            conn.close()

    def test_expansion_respects_max_hops(self) -> None:
        conn = crowley.connect_db()
        try:
            first = self._insert(conn, content="hop first")
            second = self._insert(conn, content="hop second")
            third = self._insert(conn, content="hop third")
            self._link(conn, first, second, 0.9)
            self._link(conn, second, third, 0.9)

            result = spark_graph.expand_spark_graph(conn, [first], max_hops=1)

            self.assertEqual(result.hop_distance, {first: 0, second: 1})
            self.assertNotIn(third, result.hop_distance)
        finally:
            conn.close()

    def test_orphan_and_unseeded_island_excluded(self) -> None:
        conn = crowley.connect_db()
        try:
            seed = self._insert(conn, content="seed component")
            linked = self._insert(conn, content="linked component")
            orphan = self._insert(conn, content="orphan component")
            island_a = self._insert(conn, content="island a")
            island_b = self._insert(conn, content="island b")
            self._link(conn, seed, linked, 0.9)
            self._link(conn, island_a, island_b, 0.9)

            result = spark_graph.expand_spark_graph(conn, [seed], max_hops=2)

            self.assertIn(linked, result.hop_distance)
            self.assertNotIn(orphan, result.hop_distance)
            self.assertNotIn(island_a, result.hop_distance)
            self.assertNotIn(island_b, result.hop_distance)
        finally:
            conn.close()

    def test_rejected_neighbor_skipped(self) -> None:
        conn = crowley.connect_db()
        try:
            seed = self._insert(conn, content="accepted seed")
            rejected = self._insert(conn, content="rejected neighbor")
            self._link(conn, seed, rejected, 0.9)
            conn.execute(
                "UPDATE sparks SET trust_state = 'rejected' WHERE id = ?",
                (rejected,),
            )

            result = spark_graph.expand_spark_graph(conn, [seed], max_hops=1)

            self.assertEqual(result.hop_distance, {seed: 0})
        finally:
            conn.close()

    def test_lane_and_project_scope_filter_neighbors(self) -> None:
        conn = crowley.connect_db()
        try:
            seed = self._insert(conn, content="scoped seed", project_id=7)
            same_scope = self._insert(conn, content="same scope", project_id=7)
            wrong_project = self._insert(conn, content="wrong project", project_id=8)
            wrong_lane = self._insert(
                conn, content="wrong lane", lane="learning", project_id=7
            )
            self._link(conn, seed, same_scope, 0.9)
            self._link(conn, seed, wrong_project, 0.95)
            self._link(conn, seed, wrong_lane, 0.99)

            result = spark_graph.expand_spark_graph(
                conn,
                [seed],
                max_hops=1,
                project_id=7,
                lanes=frozenset({"work"}),
            )

            self.assertIn(same_scope, result.hop_distance)
            self.assertNotIn(wrong_project, result.hop_distance)
            self.assertNotIn(wrong_lane, result.hop_distance)
        finally:
            conn.close()

    def test_neighbor_ordering_prefers_stronger_edges_under_budget(self) -> None:
        conn = crowley.connect_db()
        try:
            seed = self._insert(conn, content="ordered seed")
            weak = self._insert(conn, content="weak neighbor")
            strong = self._insert(conn, content="strong neighbor")
            self._link(conn, seed, weak, 0.4)
            self._link(conn, seed, strong, 0.95)

            result = spark_graph.expand_spark_graph(
                conn,
                [seed],
                max_hops=1,
                max_nodes=2,
            )

            self.assertIn(strong, result.hop_distance)
            self.assertNotIn(weak, result.hop_distance)
        finally:
            conn.close()

    def test_hop_attenuation_applies_to_expansion_boosts(self) -> None:
        conn = crowley.connect_db()
        try:
            first = self._insert(conn, content="attenuation first")
            second = self._insert(conn, content="attenuation second")
            third = self._insert(conn, content="attenuation third")
            self._link(conn, first, second, 0.9)
            self._link(conn, second, third, 0.9)

            result = spark_graph.expand_spark_graph(conn, [first], max_hops=2)

            self.assertAlmostEqual(
                result.graph_boost[second],
                0.9 * spark_graph.SPARK_EXPANSION_HOP_DECAY,
            )
            self.assertAlmostEqual(
                result.graph_boost[third],
                0.9 * (spark_graph.SPARK_EXPANSION_HOP_DECAY**2),
            )
        finally:
            conn.close()

    def test_prune_dry_run_reports_stale_weak_links(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="old weak left")
            right = self._insert(conn, content="old weak right")
            link_id = self._link(conn, left, right, 0.2)
            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            conn.execute(
                "UPDATE spark_links SET updated_at = ? WHERE id = ?",
                (old, link_id),
            )

            candidates = spark_graph.prune_spark_links_dry_run(conn)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].link_id, link_id)
            self.assertEqual(candidates[0].confidence, 0.2)
        finally:
            conn.close()

    def test_prune_dry_run_excludes_recent_or_strong_links(self) -> None:
        conn = crowley.connect_db()
        try:
            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            recent_left = self._insert(conn, content="recent weak left")
            recent_right = self._insert(conn, content="recent weak right")
            strong_left = self._insert(conn, content="old strong left")
            strong_right = self._insert(conn, content="old strong right")
            self._link(conn, recent_left, recent_right, 0.2)
            strong_id = self._link(conn, strong_left, strong_right, 0.3)
            conn.execute(
                "UPDATE spark_links SET updated_at = ? WHERE id = ?",
                (old, strong_id),
            )

            candidates = spark_graph.prune_spark_links_dry_run(conn)

            self.assertEqual(candidates, [])
        finally:
            conn.close()

    def test_prune_dry_run_does_not_delete(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="dry run left")
            right = self._insert(conn, content="dry run right")
            link_id = self._link(conn, left, right, 0.1)
            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            conn.execute(
                "UPDATE spark_links SET updated_at = ? WHERE id = ?",
                (old, link_id),
            )
            before = conn.execute("SELECT COUNT(*) AS n FROM spark_links").fetchone()

            spark_graph.prune_spark_links_dry_run(conn)
            after = conn.execute("SELECT COUNT(*) AS n FROM spark_links").fetchone()

            assert before is not None
            assert after is not None
            self.assertEqual(int(before["n"]), int(after["n"]))
        finally:
            conn.close()

    def test_retrieve_with_expansion_adds_linked_neighbor(self) -> None:
        conn = crowley.connect_db()
        try:
            seed = self._insert(conn, content="retrieval expansion seed", confidence=0.5)
            linked = self._insert(conn, content="retrieval expansion linked", confidence=0.5)
            self._link(conn, seed, linked, 0.95)

            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={seed: 0.9}
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "retrieval expansion",
                    conn=conn,
                    limit=2,
                    bump_access=False,
                    expand_hops=1,
                )

            self.assertEqual({item.spark_id for item in results}, {seed, linked})
            by_id = {item.spark_id: item for item in results}
            self.assertEqual(by_id[linked].score_breakdown["semantic"], 0.0)
            self.assertGreater(
                by_id[linked].score_breakdown["graph_reinforcement"], 0.0
            )
        finally:
            conn.close()

    def test_retrieve_expansion_seeds_only_top_ranked_limit(self) -> None:
        conn = crowley.connect_db()
        try:
            top = self._insert(conn, content="top scored seed", confidence=0.5)
            mid = self._insert(conn, content="middle scored seed", confidence=0.5)
            weak = self._insert(conn, content="weak scored non seed", confidence=0.5)
            noise = self._insert(conn, content="weak linked noise", confidence=0.5)
            self._link(conn, weak, noise, 0.99)

            semantic = {top: 0.9, mid: 0.2, weak: 0.01}
            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value=semantic
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "seed limit",
                    conn=conn,
                    limit=2,
                    bump_access=False,
                    expand_hops=1,
                )

            self.assertEqual([item.spark_id for item in results], [top, mid])
            self.assertNotIn(noise, {item.spark_id for item in results})
        finally:
            conn.close()

    def test_retrieve_expand_hops_zero_preserves_t8_behavior(self) -> None:
        conn = crowley.connect_db()
        try:
            seed = self._insert(conn, content="zero hop seed")
            linked = self._insert(conn, content="zero hop linked")
            self._link(conn, seed, linked, 0.95)

            with mock.patch.object(
                spark_retrieval, "_spark_semantic_candidate_scores", return_value={seed: 0.9}
            ), mock.patch.object(
                spark_retrieval, "_spark_keyword_candidate_scores", return_value={}
            ), mock.patch.object(
                spark_retrieval, "_pinned_spark_ids", return_value=set()
            ):
                results = spark_retrieval.retrieve_sparks(
                    "zero hop",
                    conn=conn,
                    limit=2,
                    bump_access=False,
                )

            self.assertEqual([item.spark_id for item in results], [seed])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
