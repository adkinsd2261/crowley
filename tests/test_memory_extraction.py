#!/usr/bin/env python3
"""V4.1 — memory store/retrieval extraction compatibility tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import memory_embeddings  # noqa: E402
import memory_retrieval  # noqa: E402
import memory_store  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryExtractionTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_quality_gate_uses_shared_outcome_type(self) -> None:
        outcome = crowley.evaluate_memory_quality_gate(
            "decision",
            "Decision: memory extraction keeps Crowley facade compatibility.",
            summary="Memory extraction facade compatibility was verified.",
            source="manual",
            project_id=self.project_id,
        )
        self.assertIsInstance(outcome, memory_store.MemoryGateOutcome)
        self.assertTrue(outcome.allowed)

    def test_memory_store_and_retrieval_modules_back_facade(self) -> None:
        memory_id = memory_store.save_memory_item(
            crowley,
            "decision",
            "Decision: T6 memory extraction owns store and retrieval behavior.",
            summary="T6 memory extraction owns store and retrieval behavior.",
            source="manual",
            project_id=self.project_id,
            conn=self.conn,
        )
        self.assertIsNotNone(memory_id)
        self.conn.commit()

        results = crowley.retrieve_memories(
            "T6 memory extraction retrieval behavior",
            project_id=self.project_id,
            limit=5,
        )
        ids = {int(item["id"]) for item in results}
        self.assertIn(int(memory_id), ids)
        direct = memory_retrieval.retrieve_memories(
            crowley,
            "T6 memory extraction retrieval behavior",
            5,
            project_id=self.project_id,
        )
        self.assertEqual([item["id"] for item in direct], [item["id"] for item in results])

    def test_embedding_provider_facade_uses_extracted_module(self) -> None:
        self.assertEqual(crowley._memory_embed_provider(), "off")
        self.assertEqual(memory_embeddings.memory_embed_provider(crowley), "off")


if __name__ == "__main__":
    import unittest

    unittest.main()
