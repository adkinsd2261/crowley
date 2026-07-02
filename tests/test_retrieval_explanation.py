#!/usr/bin/env python3
"""V3.9.2 retrieval explanation payload tests."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _unit_embedding(dim: int = crowley.EMBED_DIM) -> list[float]:
    vector = [0.0] * dim
    vector[0] = 1.0
    return vector


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


EXPLANATION_KEYS = {
    "source",
    "memory_type",
    "status",
    "pinned",
    "is_canon",
    "score",
    "score_breakdown",
    "retrieval_mode",
    "provenance",
    "provenance_available",
}


class RetrievalExplanationTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        self.probe = f"retrieval explanation probe {crowley._now_iso()}"
        self.memory_id: int | None = None
        self._original_embed_text = crowley.embed_text
        crowley.embed_text = lambda _text: None  # type: ignore[assignment]

    def tearDown(self) -> None:
        crowley.embed_text = self._original_embed_text  # type: ignore[assignment]
        if self.memory_id is not None:
            self.conn.execute("DELETE FROM memory_items WHERE id = ?", (self.memory_id,))
            self.conn.commit()
        self.conn.close()
        super().tearDown()

    def _insert_probe(self, *, content: str, **kwargs: object) -> int:
        now = crowley._now_iso()
        embedding = kwargs.get("embedding")
        embedding_blob = _pack(embedding) if isinstance(embedding, list) else None
        cur = self.conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence, decision_id, embedding_blob
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0.9, ?, ?)
            """,
            (
                now,
                now,
                self.project_id,
                str(kwargs.get("memory_type", "event")),
                content,
                kwargs.get("summary"),
                int(kwargs.get("importance", 3)),
                str(kwargs.get("source", "cursor")),
                1 if kwargs.get("pinned") else 0,
                kwargs.get("decision_id"),
                embedding_blob,
            ),
        )
        self.conn.commit()
        self.memory_id = int(cur.lastrowid)
        return self.memory_id

    def _assert_explanation_shape(self, item: dict[str, object], *, mode: str) -> None:
        for key in (
            "source",
            "memory_type",
            "score",
            "status",
            "pinned",
            "is_canon",
            "provenance",
            "provenance_available",
            "explanation",
        ):
            self.assertIn(key, item, msg=f"missing top-level {key}")

        explanation = item["explanation"]
        assert isinstance(explanation, dict)
        self.assertEqual(set(explanation.keys()), EXPLANATION_KEYS)
        self.assertEqual(explanation["retrieval_mode"], mode)
        self.assertIsInstance(explanation["score_breakdown"], dict)

        provenance = explanation["provenance"]
        assert isinstance(provenance, dict)
        self.assertIn("memory_item_id", provenance)

        available = explanation["provenance_available"]
        assert isinstance(available, dict)
        self.assertEqual(int(available["memory_item_id"]), int(item["id"]))

    def test_vector_keyword_explanation_payload(self) -> None:
        vector = _unit_embedding()
        memory_id = self._insert_probe(
            content=f"{self.probe} vector keyword explanation ticket ten",
            decision_id=42,
            embedding=vector,
        )
        crowley.embed_text = lambda _text: vector  # type: ignore[assignment]
        results = crowley.retrieve_memories(self.probe, limit=50, project_id=self.project_id)
        self.assertEqual(crowley.get_last_retrieval_mode(), "vector+keyword")
        self.assertGreaterEqual(len(results), 1)
        hit = next((item for item in results if int(item["id"]) == memory_id), None)
        self.assertIsNotNone(hit, msg=f"probe memory #{memory_id} not in retrieval results")
        assert hit is not None
        mode = crowley.get_last_retrieval_mode()
        self._assert_explanation_shape(hit, mode=mode)
        self.assertEqual(hit["status"], "active")
        self.assertFalse(bool(hit["is_canon"]))
        explanation = hit["explanation"]
        assert isinstance(explanation, dict)
        self.assertEqual(explanation["provenance"]["decision_id"], 42)
        self.assertEqual(explanation["provenance_available"]["decision_id"], 42)

    def test_keyword_fallback_explanation_payload(self) -> None:
        memory_id = self._insert_probe(
            content=f"{self.probe} keyword fallback explanation only path",
        )
        results = crowley.retrieve_memories(self.probe, limit=50, project_id=self.project_id)
        self.assertEqual(crowley.get_last_retrieval_mode(), "keyword-only fallback")
        hit = next((item for item in results if int(item["id"]) == memory_id), None)
        self.assertIsNotNone(hit)
        assert hit is not None
        self._assert_explanation_shape(hit, mode="keyword-only fallback")
        explanation = hit["explanation"]
        assert isinstance(explanation, dict)
        self.assertEqual(float(explanation["score_breakdown"]["semantic"]), 0.0)

    def test_retrieve_memories_api_includes_explanations(self) -> None:
        self._insert_probe(content=f"{self.probe} api retrieve explanation payload")
        payload = crowley.retrieve_memories_api(self.probe, limit=3)
        self.assertIn("retrieval_mode", payload)
        results = payload["results"]
        assert isinstance(results, list)
        self.assertGreaterEqual(len(results), 1)
        self._assert_explanation_shape(
            results[0],
            mode=str(payload["retrieval_mode"]),
        )

    def test_canon_flag_on_canon_row(self) -> None:
        memory_id = self._insert_probe(
            content="Canon: Project\n\nQA canon explanation probe docs/WHERE_WE_ARE.md",
            memory_type="summary",
            source="crowley",
            pinned=True,
        )
        results = crowley.retrieve_memories("Canon explanation probe", limit=20, project_id=self.project_id)
        hit = next((item for item in results if int(item["id"]) == memory_id), None)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(bool(hit["is_canon"]))
        explanation = hit["explanation"]
        assert isinstance(explanation, dict)
        self.assertTrue(bool(explanation["is_canon"]))


if __name__ == "__main__":
    unittest.main()
