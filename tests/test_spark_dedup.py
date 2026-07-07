#!/usr/bin/env python3
"""V4 T6 — spark dedup and merge at creation tests."""

from __future__ import annotations

import json
import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Lane enums keep cognitive retrieval deterministic.",
        "lane": "work",
        "why_keep": "Prevents silent misclassification during ingest.",
        "worth_reason": "Supports reliable spark routing in V4 memory.",
        "confidence": 0.8,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


def _pack_vec(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def _vec_384(first: float, second: float = 0.0) -> list[float]:
    vector = [0.0] * crowley.EMBED_DIM
    vector[0] = first
    if crowley.EMBED_DIM > 1:
        vector[1] = second
    return vector


class SparkDedupTests(IsolatedDbTestCase):
    def _upsert(
        self,
        conn,
        spark: dict[str, object],
        *,
        memory_item_id: int = 1,
        project_id: int | None = None,
    ) -> sparks.SparkUpsertResult:
        return sparks.upsert_spark_with_dedup(
            conn,
            spark,
            source_memory_item_id=memory_item_id,
            project_id=project_id,
            trust_state="candidate",
        )

    def test_duplicate_merged_into_keeper(self) -> None:
        conn = crowley.connect_db()
        try:
            first = self._upsert(conn, _valid_spark())
            self.assertEqual(first.action, "inserted")
            second = self._upsert(
                conn,
                _valid_spark(content="Lane enums keep cognitive retrieval deterministic."),
                memory_item_id=2,
            )
            self.assertEqual(second.action, "merged")
            self.assertEqual(second.spark_id, first.spark_id)

            count = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            assert count is not None
            self.assertEqual(int(count["n"]), 1)

            row = conn.execute(
                "SELECT source_refs_json, confidence, base_confidence FROM sparks WHERE id = ?",
                (first.spark_id,),
            ).fetchone()
            assert row is not None
            refs = json.loads(str(row["source_refs_json"]))
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["source_memory_item_id"], 2)
            self.assertGreater(float(row["confidence"]), 0.8)
            self.assertEqual(float(row["base_confidence"]), 0.8)
        finally:
            conn.close()

    def test_near_duplicate_creates_reinforces_link(self) -> None:
        keeper_vec = _vec_384(1.0, 0.0)
        near_vec = _vec_384(0.90, 0.436)  # cosine ≈ 0.90

        def fake_embed(text: str) -> list[float] | None:
            if "keeper" in text:
                return keeper_vec
            if "near" in text:
                return near_vec
            return keeper_vec

        conn = crowley.connect_db()
        try:
            with mock.patch.object(crowley, "embed_text", side_effect=fake_embed):
                first = self._upsert(
                    conn,
                    _valid_spark(content="keeper spark about lane enums"),
                )
                self.assertEqual(first.action, "inserted")
                conn.execute(
                    "UPDATE sparks SET embedding_blob = ? WHERE id = ?",
                    (_pack_vec(keeper_vec), first.spark_id),
                )

                second = self._upsert(
                    conn,
                    _valid_spark(content="near spark about lane enums"),
                    memory_item_id=2,
                )
            self.assertEqual(second.action, "linked")
            assert second.keeper_id is not None
            self.assertEqual(second.keeper_id, first.spark_id)

            spark_count = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            link_count = conn.execute(
                "SELECT COUNT(*) AS n FROM spark_links WHERE link_type = ?",
                (sparks.SPARK_LINK_TYPE_REINFORCES,),
            ).fetchone()
            assert spark_count is not None and link_count is not None
            self.assertEqual(int(spark_count["n"]), 2)
            self.assertEqual(int(link_count["n"]), 1)

            link = conn.execute(
                """
                SELECT from_spark_id, to_spark_id, confidence
                FROM spark_links WHERE link_type = ?
                """,
                (sparks.SPARK_LINK_TYPE_REINFORCES,),
            ).fetchone()
            assert link is not None
            self.assertEqual(int(link["from_spark_id"]), second.spark_id)
            self.assertEqual(int(link["to_spark_id"]), first.spark_id)
        finally:
            conn.close()

    def test_distinct_sparks_both_saved(self) -> None:
        left_vec = _vec_384(1.0, 0.0)
        right_vec = _vec_384(0.0, 1.0)

        def fake_embed(text: str) -> list[float] | None:
            if "alpha" in text:
                return left_vec
            return right_vec

        conn = crowley.connect_db()
        try:
            with mock.patch.object(crowley, "embed_text", side_effect=fake_embed):
                first = self._upsert(conn, _valid_spark(content="alpha topic spark"))
                conn.execute(
                    "UPDATE sparks SET embedding_blob = ? WHERE id = ?",
                    (_pack_vec(left_vec), first.spark_id),
                )
                second = self._upsert(
                    conn,
                    _valid_spark(content="beta topic spark"),
                    memory_item_id=2,
                )
            self.assertEqual(first.action, "inserted")
            self.assertEqual(second.action, "inserted")
            self.assertNotEqual(first.spark_id, second.spark_id)

            link_count = conn.execute("SELECT COUNT(*) AS n FROM spark_links").fetchone()
            assert link_count is not None
            self.assertEqual(int(link_count["n"]), 0)
        finally:
            conn.close()

    def test_dedup_runs_before_insert_on_merge(self) -> None:
        conn = crowley.connect_db()
        try:
            first = self._upsert(conn, _valid_spark())
            with mock.patch.object(sparks, "insert_spark", wraps=sparks.insert_spark) as insert_mock:
                second = self._upsert(
                    conn,
                    _valid_spark(),
                    memory_item_id=2,
                )
            self.assertEqual(second.action, "merged")
            insert_mock.assert_not_called()
        finally:
            conn.close()

    def test_merge_returns_keeper_id(self) -> None:
        conn = crowley.connect_db()
        try:
            first = self._upsert(conn, _valid_spark())
            second = self._upsert(conn, _valid_spark(), memory_item_id=2)
            self.assertEqual(second.action, "merged")
            self.assertEqual(second.spark_id, first.spark_id)
            self.assertEqual(second.keeper_id, first.spark_id)
        finally:
            conn.close()

    def test_embed_off_exact_content_merge(self) -> None:
        conn = crowley.connect_db()
        try:
            with mock.patch.object(crowley, "embed_text", return_value=None):
                first = self._upsert(conn, _valid_spark())
                second = self._upsert(conn, _valid_spark(), memory_item_id=2)
            self.assertEqual(second.action, "merged")
            count = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            assert count is not None
            self.assertEqual(int(count["n"]), 1)
        finally:
            conn.close()

    def test_reinforces_updates_existing_link(self) -> None:
        conn = crowley.connect_db()
        try:
            keeper = self._upsert(conn, _valid_spark(content="keeper spark"))
            with mock.patch.object(
                crowley,
                "_cosine_similarity",
                return_value=0.90,
            ), mock.patch.object(
                crowley,
                "embed_text",
                return_value=_vec_384(1.0),
            ):
                conn.execute(
                    "UPDATE sparks SET embedding_blob = ? WHERE id = ?",
                    (_pack_vec(_vec_384(1.0)), keeper.spark_id),
                )
                linked = self._upsert(
                    conn,
                    _valid_spark(content="another near spark"),
                    memory_item_id=3,
                )
            self.assertEqual(linked.action, "linked")

            before = conn.execute(
                "SELECT confidence FROM spark_links WHERE from_spark_id = ? AND to_spark_id = ?",
                (linked.spark_id, keeper.spark_id),
            ).fetchone()
            assert before is not None
            before_conf = float(before["confidence"])

            sparks._upsert_reinforces_link(
                conn,
                linked.spark_id,
                keeper.spark_id,
                confidence=before_conf,
            )
            after = conn.execute(
                "SELECT COUNT(*) AS n FROM spark_links WHERE from_spark_id = ? AND to_spark_id = ?",
                (linked.spark_id, keeper.spark_id),
            ).fetchone()
            row = conn.execute(
                "SELECT confidence FROM spark_links WHERE from_spark_id = ? AND to_spark_id = ?",
                (linked.spark_id, keeper.spark_id),
            ).fetchone()
            assert after is not None and row is not None
            self.assertEqual(int(after["n"]), 1)
            self.assertGreater(float(row["confidence"]), before_conf)
        finally:
            conn.close()

    def test_candidate_limit_applied(self) -> None:
        conn = crowley.connect_db()
        try:
            for idx in range(sparks.MAX_DEDUP_CANDIDATES + 25):
                sparks.insert_spark(
                    conn,
                    _valid_spark(content=f"seed spark number {idx}"),
                    source_memory_item_id=idx + 10,
                    project_id=None,
                    trust_state="candidate",
                    embedding_blob=_pack_vec(_vec_384(0.1, float(idx))),
                    embed_model="test",
                    embed_dim=crowley.EMBED_DIM,
                )

            sim_calls = 0

            def counting_sim(left: list[float], right: list[float]) -> float:
                nonlocal sim_calls
                sim_calls += 1
                return 0.0

            with mock.patch.object(crowley, "_cosine_similarity", side_effect=counting_sim):
                with mock.patch.object(crowley, "embed_text", return_value=_vec_384(1.0, 0.0)):
                    result = self._upsert(
                        conn,
                        _valid_spark(content="brand new unmatched spark"),
                        memory_item_id=999,
                    )
            self.assertEqual(result.action, "inserted")
            self.assertLessEqual(sim_calls, sparks.MAX_DEDUP_CANDIDATES)
        finally:
            conn.close()

    def test_content_equality_precedes_embedding_noise(self) -> None:
        conn = crowley.connect_db()
        try:
            keeper_vec = _vec_384(1.0, 0.0)
            noisy_vec = _vec_384(0.0, 1.0)

            with mock.patch.object(crowley, "embed_text", return_value=noisy_vec):
                first = self._upsert(conn, _valid_spark(content="same normalized content"))
                conn.execute(
                    "UPDATE sparks SET embedding_blob = ? WHERE id = ?",
                    (_pack_vec(keeper_vec), first.spark_id),
                )
                second = self._upsert(
                    conn,
                    _valid_spark(content="same   normalized   content"),
                    memory_item_id=2,
                )
            self.assertEqual(second.action, "merged")
            count = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            assert count is not None
            self.assertEqual(int(count["n"]), 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
