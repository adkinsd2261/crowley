#!/usr/bin/env python3
"""V4 T7 — spark embeddings and spark_vec tests."""

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
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Indexed sparks enable vector retrieval in V4 memory.",
        "lane": "work",
        "why_keep": "Supports semantic search over cognitive sparks.",
        "worth_reason": "Required foundation for T8 retrieval scoring.",
        "confidence": 0.82,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


def _unit_vector(dim: int = crowley.EMBED_DIM, axis: int = 0) -> list[float]:
    vector = [0.0] * dim
    vector[axis] = 1.0
    return vector


def _insert_bare_spark(conn, spark: dict[str, object] | None = None) -> int:
    return sparks.insert_spark(
        conn,
        spark or _valid_spark(),
        source_memory_item_id=1,
        project_id=None,
        trust_state="candidate",
    )


class SparkEmbeddingTests(IsolatedDbTestCase):
    def test_index_spark_embedding_writes_blob(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            vector = _unit_vector()
            with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                ok = sparks.index_spark_embedding(
                    conn, spark_id, vector, "test-model"
                )
            self.assertTrue(ok)
            row = conn.execute(
                "SELECT embedding_blob, embed_model, embed_dim FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIsNotNone(row["embedding_blob"])
            self.assertEqual(row["embed_model"], "test-model")
            self.assertEqual(int(row["embed_dim"]), crowley.EMBED_DIM)
        finally:
            conn.close()

    def test_index_spark_embedding_writes_spark_vec(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            vector = _unit_vector()
            with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=True):
                with mock.patch.object(sparks, "_write_spark_vec_row") as vec_mock:
                    sparks.index_spark_embedding(conn, spark_id, vector, "test-model")
            vec_mock.assert_called_once_with(conn, spark_id, vector)
        finally:
            conn.close()

    def test_index_spark_embedding_reindexes_idempotently(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            vector = _unit_vector()
            with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=True):
                with mock.patch.object(sparks, "_write_spark_vec_row") as vec_mock:
                    sparks.index_spark_embedding(conn, spark_id, vector, "test-model")
                    sparks.index_spark_embedding(conn, spark_id, vector, "test-model")
            self.assertEqual(vec_mock.call_count, 2)
        finally:
            conn.close()

    def test_vec_unavailable_still_writes_blob(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                ok = sparks.index_spark_embedding(
                    conn, spark_id, _unit_vector(), "test-model"
                )
            self.assertTrue(ok)
            row = conn.execute(
                "SELECT embedding_blob FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIsNotNone(row["embedding_blob"])
        finally:
            conn.close()

    def test_embed_and_index_reuses_provided_vector(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            vector = _unit_vector()
            with mock.patch.object(crowley, "embed_text") as embed_mock:
                with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                    ok = sparks.embed_and_index_spark(
                        conn, spark_id, "ignored content", vector=vector
                    )
            self.assertTrue(ok)
            embed_mock.assert_not_called()
        finally:
            conn.close()

    def test_embed_and_index_skips_when_provider_off(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            with mock.patch.object(crowley, "embed_text", return_value=None):
                ok = sparks.embed_and_index_spark(conn, spark_id, "some content")
            self.assertFalse(ok)
            row = conn.execute(
                "SELECT embedding_blob FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIsNone(row["embedding_blob"])
        finally:
            conn.close()

    def test_upsert_on_save_indexes_spark(self) -> None:
        conn = crowley.connect_db()
        try:
            vector = _unit_vector()
            with mock.patch.object(crowley, "embed_text", return_value=vector):
                with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                    result = sparks.upsert_spark_with_dedup(
                        conn,
                        _valid_spark(),
                        source_memory_item_id=1,
                        project_id=None,
                        trust_state="candidate",
                    )
            self.assertEqual(result.action, "inserted")
            row = conn.execute(
                "SELECT embedding_blob, embed_dim FROM sparks WHERE id = ?",
                (result.spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIsNotNone(row["embedding_blob"])
            self.assertEqual(int(row["embed_dim"]), crowley.EMBED_DIM)
        finally:
            conn.close()

    def test_merge_does_not_reindex_keeper(self) -> None:
        conn = crowley.connect_db()
        try:
            keeper_vector = _unit_vector(axis=0)
            with mock.patch.object(crowley, "embed_text", return_value=keeper_vector):
                with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                    first = sparks.upsert_spark_with_dedup(
                        conn,
                        _valid_spark(),
                        source_memory_item_id=1,
                        project_id=None,
                        trust_state="candidate",
                    )
            row = conn.execute(
                "SELECT embedding_blob, updated_at FROM sparks WHERE id = ?",
                (first.spark_id,),
            ).fetchone()
            assert row is not None
            original_blob = row["embedding_blob"]
            original_updated = row["updated_at"]

            with mock.patch.object(crowley, "embed_text", return_value=keeper_vector):
                with mock.patch.object(sparks, "index_spark_embedding") as index_mock:
                    second = sparks.upsert_spark_with_dedup(
                        conn,
                        _valid_spark(),
                        source_memory_item_id=2,
                        project_id=None,
                        trust_state="candidate",
                    )
            self.assertEqual(second.action, "merged")
            index_mock.assert_not_called()
            row2 = conn.execute(
                "SELECT embedding_blob, updated_at FROM sparks WHERE id = ?",
                (first.spark_id,),
            ).fetchone()
            assert row2 is not None
            self.assertEqual(row2["embedding_blob"], original_blob)
            self.assertNotEqual(row2["updated_at"], original_updated)
        finally:
            conn.close()

    def test_backfill_embeds_null_blob_sparks(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(
                conn, _valid_spark(content="backfill target spark content")
            )
            vector = _unit_vector()
            with mock.patch.object(crowley, "_memory_embed_provider", return_value="local"):
                with mock.patch.object(crowley, "embed_text", return_value=vector):
                    with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                        count = sparks.backfill_spark_embeddings(conn, limit=200)
            self.assertEqual(count, 1)
            row = conn.execute(
                "SELECT embedding_blob FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIsNotNone(row["embedding_blob"])
        finally:
            conn.close()

    def test_rejects_wrong_dim_vector(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            ok = sparks.index_spark_embedding(conn, spark_id, [0.1, 0.2, 0.3], "test-model")
            self.assertFalse(ok)
            row = conn.execute(
                "SELECT embedding_blob FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIsNone(row["embedding_blob"])
        finally:
            conn.close()

    def test_ensure_spark_vec_table_caches_per_connection(self) -> None:
        conn = crowley.connect_db()
        try:
            sparks._spark_vec_ready_cache[id(conn)] = True
            with mock.patch.object(crowley, "_try_load_sqlite_vec", return_value=True) as load_mock:
                first = sparks._ensure_spark_vec_table(conn)
                second = sparks._ensure_spark_vec_table(conn)
            self.assertTrue(first)
            self.assertTrue(second)
            load_mock.assert_not_called()
        finally:
            conn.close()

    def test_ensure_spark_vec_table_calls_load_once(self) -> None:
        conn = crowley.connect_db()
        try:
            sparks._spark_vec_ready_cache.pop(id(conn), None)
            with mock.patch.object(crowley, "_try_load_sqlite_vec", return_value=False) as load_mock:
                first = sparks._ensure_spark_vec_table(conn)
                second = sparks._ensure_spark_vec_table(conn)
            self.assertFalse(first)
            self.assertFalse(second)
            load_mock.assert_called_once()
        finally:
            conn.close()

    def test_reindex_same_model_preserves_updated_at(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = _insert_bare_spark(conn)
            vector = _unit_vector()
            with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                sparks.index_spark_embedding(conn, spark_id, vector, "test-model")
            row = conn.execute(
                "SELECT updated_at FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            first_updated = row["updated_at"]
            with mock.patch.object(sparks, "_ensure_spark_vec_table", return_value=False):
                sparks.index_spark_embedding(conn, spark_id, vector, "test-model")
            row2 = conn.execute(
                "SELECT updated_at FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row2 is not None
            self.assertEqual(row2["updated_at"], first_updated)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
