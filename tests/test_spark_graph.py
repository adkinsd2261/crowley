#!/usr/bin/env python3
"""V4 T9 — spark graph link CRUD limits and confidence tests."""

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
import spark_graph  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Graph link discipline keeps spark reinforcement bounded.",
        "lane": "work",
        "why_keep": "Prevents uncontrolled graph growth during ingest.",
        "worth_reason": "Supports deterministic cognitive memory links.",
        "confidence": 0.7,
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


class SparkGraphTests(IsolatedDbTestCase):
    def _insert(self, conn, **overrides: object) -> int:
        return sparks.insert_spark(
            conn,
            _valid_spark(**overrides),
            source_memory_item_id=1,
            project_id=None,
            trust_state="active",
        )

    def _index_both(
        self, conn, from_id: int, to_id: int, *, sim_axis_from: int = 0, sim_axis_to: int = 0
    ) -> None:
        sparks.index_spark_embedding(conn, from_id, _unit_vector(sim_axis_from), "test")
        sparks.index_spark_embedding(conn, to_id, _unit_vector(sim_axis_to), "test")

    def test_rejects_subthreshold_similarity(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="alpha graph spark")
            right = self._insert(conn, content="beta graph spark")
            self._index_both(conn, left, right, sim_axis_from=0, sim_axis_to=1)
            result = spark_graph.create_spark_link(
                conn, left, right, sparks.SPARK_LINK_TYPE_REINFORCES
            )
            self.assertFalse(result.ok)
            self.assertIn("similarity", result.errors[0])
        finally:
            conn.close()

    def test_accepts_threshold_similarity(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="threshold left spark")
            right = self._insert(conn, content="threshold right spark")
            vec = _unit_vector(0)
            sparks.index_spark_embedding(conn, left, vec, "test")
            sparks.index_spark_embedding(conn, right, vec, "test")
            result = spark_graph.create_spark_link(
                conn, left, right, sparks.SPARK_LINK_TYPE_REINFORCES, confidence=0.82
            )
            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.action, "created")
            row = conn.execute(
                "SELECT confidence FROM spark_links WHERE id = ?",
                (result.link_id,),
            ).fetchone()
            assert row is not None
            self.assertEqual(float(row["confidence"]), 0.82)
        finally:
            conn.close()

    def test_explicit_reinforcement_bypasses_sim(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="explicit left")
            right = self._insert(conn, content="explicit right")
            result = spark_graph.create_spark_link(
                conn,
                left,
                right,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
                confidence=0.6,
            )
            self.assertTrue(result.ok, result.errors)
        finally:
            conn.close()

    def test_rejects_without_blob_and_no_explicit(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="no blob left")
            right = self._insert(conn, content="no blob right")
            result = spark_graph.create_spark_link(
                conn, left, right, sparks.SPARK_LINK_TYPE_REINFORCES
            )
            self.assertFalse(result.ok)
        finally:
            conn.close()

    def test_existing_pair_updates_despite_low_sim(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="upsert left spark")
            right = self._insert(conn, content="upsert right spark")
            first = spark_graph.create_spark_link(
                conn,
                left,
                right,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
                confidence=0.7,
            )
            assert first.link_id is not None
            second = spark_graph.create_spark_link(
                conn,
                left,
                right,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                similarity=0.1,
            )
            self.assertTrue(second.ok, second.errors)
            self.assertEqual(second.action, "updated")
            count = conn.execute("SELECT COUNT(*) AS n FROM spark_links").fetchone()
            assert count is not None
            self.assertEqual(int(count["n"]), 1)
        finally:
            conn.close()

    def test_rejects_16th_outgoing_link(self) -> None:
        conn = crowley.connect_db()
        try:
            source = self._insert(conn, content="hub spark outgoing")
            old_ts = "2020-01-01T00:00:00+00:00"
            targets = [
                self._insert(conn, content=f"target spark {idx}") for idx in range(16)
            ]
            for target in targets[:15]:
                result = spark_graph.create_spark_link(
                    conn,
                    source,
                    target,
                    sparks.SPARK_LINK_TYPE_REINFORCES,
                    explicit_reinforcement=True,
                )
                self.assertTrue(result.ok, result.errors)
                conn.execute(
                    "UPDATE spark_links SET created_at = ? WHERE from_spark_id = ? AND to_spark_id = ?",
                    (old_ts, source, target),
                )
            blocked = spark_graph.create_spark_link(
                conn,
                source,
                targets[15],
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
            )
            self.assertFalse(blocked.ok)
            self.assertIn("max outgoing", blocked.errors[0])
        finally:
            conn.close()

    def test_daily_rate_limit_enforced(self) -> None:
        conn = crowley.connect_db()
        try:
            source = self._insert(conn, content="rate limited source")
            for idx in range(10):
                target = self._insert(conn, content=f"rate target {idx}")
                result = spark_graph.create_spark_link(
                    conn,
                    source,
                    target,
                    sparks.SPARK_LINK_TYPE_REINFORCES,
                    explicit_reinforcement=True,
                )
                self.assertTrue(result.ok, result.errors)
            extra = self._insert(conn, content="rate target extra")
            blocked = spark_graph.create_spark_link(
                conn,
                source,
                extra,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
            )
            self.assertFalse(blocked.ok)
            self.assertIn("daily", blocked.errors[0])
        finally:
            conn.close()

    def test_upsert_existing_pair_not_rate_limited(self) -> None:
        conn = crowley.connect_db()
        try:
            source = self._insert(conn, content="upsert rate source")
            for idx in range(10):
                target = self._insert(conn, content=f"upsert rate target {idx}")
                spark_graph.create_spark_link(
                    conn,
                    source,
                    target,
                    sparks.SPARK_LINK_TYPE_REINFORCES,
                    explicit_reinforcement=True,
                )
            repeat_target = self._insert(conn, content="upsert rate target 0")
            first_id = conn.execute(
                "SELECT id FROM spark_links WHERE from_spark_id = ? LIMIT 1",
                (source,),
            ).fetchone()
            assert first_id is not None
            updated = spark_graph.create_spark_link(
                conn,
                source,
                int(
                    conn.execute(
                        "SELECT to_spark_id FROM spark_links WHERE id = ?",
                        (int(first_id["id"]),),
                    ).fetchone()["to_spark_id"]
                ),
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
                confidence=0.55,
            )
            self.assertTrue(updated.ok, updated.errors)
            self.assertEqual(updated.action, "updated")
            blocked = spark_graph.create_spark_link(
                conn,
                source,
                repeat_target,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
            )
            self.assertFalse(blocked.ok)
        finally:
            conn.close()

    def test_link_confidence_zero_preserved(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="zero conf left")
            right = self._insert(conn, content="zero conf right")
            result = spark_graph.create_spark_link(
                conn,
                left,
                right,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
                confidence=0.0,
            )
            self.assertTrue(result.ok, result.errors)
            row = conn.execute(
                "SELECT confidence FROM spark_links WHERE id = ?",
                (result.link_id,),
            ).fetchone()
            assert row is not None
            self.assertEqual(float(row["confidence"]), 0.0)
        finally:
            conn.close()

    def test_update_link_confidence(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="update conf left")
            right = self._insert(conn, content="update conf right")
            created = spark_graph.create_spark_link(
                conn,
                left,
                right,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
                confidence=0.4,
            )
            assert created.link_id is not None
            updated = spark_graph.update_spark_link_confidence(
                conn, int(created.link_id), 0.91
            )
            self.assertTrue(updated.ok, updated.errors)
            row = conn.execute(
                "SELECT confidence FROM spark_links WHERE id = ?",
                (created.link_id,),
            ).fetchone()
            assert row is not None
            self.assertEqual(float(row["confidence"]), 0.91)
        finally:
            conn.close()

    def test_rejects_self_link(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, content="self link spark")
            result = spark_graph.create_spark_link(
                conn,
                spark_id,
                spark_id,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
            )
            self.assertFalse(result.ok)
            self.assertIn("self", result.errors[0])
        finally:
            conn.close()

    def test_rejects_invalid_spark(self) -> None:
        conn = crowley.connect_db()
        try:
            left = self._insert(conn, content="valid left")
            result = spark_graph.create_spark_link(
                conn,
                left,
                999_999,
                sparks.SPARK_LINK_TYPE_REINFORCES,
                explicit_reinforcement=True,
            )
            self.assertFalse(result.ok)
        finally:
            conn.close()

    def test_get_spark_links_both_directions(self) -> None:
        conn = crowley.connect_db()
        try:
            a = self._insert(conn, content="link node a")
            b = self._insert(conn, content="link node b")
            c = self._insert(conn, content="link node c")
            spark_graph.create_spark_link(
                conn, a, b, sparks.SPARK_LINK_TYPE_REINFORCES, explicit_reinforcement=True
            )
            spark_graph.create_spark_link(
                conn, c, a, sparks.SPARK_LINK_TYPE_REINFORCES, explicit_reinforcement=True
            )
            outgoing = spark_graph.get_spark_links(conn, a, direction="from")
            incoming = spark_graph.get_spark_links(conn, a, direction="to")
            both = spark_graph.get_spark_links(conn, a, direction="both")
            self.assertEqual(len(outgoing), 1)
            self.assertEqual(len(incoming), 1)
            self.assertEqual(len(both), 2)
        finally:
            conn.close()

    def test_t6_dedup_path_uses_spark_graph(self) -> None:
        conn = crowley.connect_db()
        try:
            vec = _unit_vector(0)
            with mock.patch.object(crowley, "embed_text", return_value=vec):
                with mock.patch.object(crowley, "_cosine_similarity", return_value=0.90):
                    first = sparks.upsert_spark_with_dedup(
                        conn,
                        _valid_spark(content="keeper dedup graph spark"),
                        source_memory_item_id=1,
                        project_id=None,
                        trust_state="candidate",
                    )
                    conn.execute(
                        "UPDATE sparks SET embedding_blob = ? WHERE id = ?",
                        (_pack_vec(vec), first.spark_id),
                    )
                    second = sparks.upsert_spark_with_dedup(
                        conn,
                        _valid_spark(content="near dedup graph spark"),
                        source_memory_item_id=2,
                        project_id=None,
                        trust_state="candidate",
                    )
            self.assertEqual(second.action, "linked")
            link = conn.execute(
                "SELECT confidence FROM spark_links WHERE from_spark_id = ? AND to_spark_id = ?",
                (second.spark_id, first.spark_id),
            ).fetchone()
            assert link is not None
            self.assertGreater(float(link["confidence"]), 0.0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
