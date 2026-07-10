"""V4.3.2 T5 — spark-first cognitive context smoke (fallback exceptional)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import context_orchestration  # noqa: E402
import crowley  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class SparkFirstCognitiveSmokeTests(IsolatedDbTestCase):
    def _seed_active_corpus(self, conn, *, n_fillers: int = 10) -> int:
        mid = crowley.save_memory_item(
            "decision",
            "User prefers local-first SQLite over ChromaDB for Crowley memory.",
            summary="User prefers local-first SQLite over ChromaDB for Crowley memory.",
            source="canon",
            importance=5,
            pinned=True,
            status="active",
            confidence=0.95,
            agent_id="system",
        )
        assert mid is not None
        project = crowley.get_active_project()
        project_id = int(project["id"]) if project is not None else None
        sparks.insert_spark(
            conn,
            {
                "content": (
                    "User prefers local-first SQLite over ChromaDB for Crowley memory."
                ),
                "lane": "work",
                "why_keep": "Core operating preference for storage.",
                "worth_reason": "Common Crowley query should resolve from sparks.",
                "confidence": 0.95,
                "spark_type": "decision",
                "certainty": "confirmed",
                "sensitivity": "normal",
            },
            source_memory_item_id=int(mid),
            project_id=project_id,
            trust_state="active",
            lineage_json={
                "migration": "v4.3.2_spark_corpus",
                "migration_batch_id": "smoke-v432",
                "source_memory_item_id": int(mid),
            },
        )
        for idx in range(n_fillers):
            sparks.insert_spark(
                conn,
                {
                    "content": f"Active filler spark {idx} for spark-first smoke coverage.",
                    "lane": "work",
                    "why_keep": "Raises active spark count above cold-start.",
                    "worth_reason": "Keeps retrieval on spark path.",
                    "confidence": 0.8,
                    "sensitivity": "normal",
                },
                source_memory_item_id=int(mid),
                project_id=project_id,
                trust_state="active",
                lineage_json={
                    "migration": "v4.3.2_spark_corpus",
                    "migration_batch_id": "smoke-filler",
                    "source_memory_item_id": int(mid),
                },
            )
        conn.commit()
        return int(mid)

    def test_common_query_uses_sparks_not_fallback(self) -> None:
        conn = crowley.connect_db()
        try:
            mid = self._seed_active_corpus(conn)
            project = crowley.get_active_project()
            project_id = int(project["id"]) if project is not None else None
            payload = context_orchestration.build_cognitive_context(
                "local-first SQLite over ChromaDB",
                lanes="work",
                project_id=project_id,
                conn=conn,
            )
        finally:
            conn.close()

        core = payload.get("core_sparks") or []
        self.assertTrue(core, payload)
        trace = payload.get("trace") or {}
        self.assertFalse(trace.get("fallback_used"), trace)
        self.assertGreaterEqual(int(trace.get("active_spark_count") or 0), 8)
        lineage = trace.get("lineage") or []
        migrated = [
            item
            for item in lineage
            if int(item.get("source_memory_item_id") or 0) == mid
        ]
        self.assertTrue(migrated, lineage)

    def test_fallback_still_available_when_corpus_empty(self) -> None:
        conn = crowley.connect_db()
        try:
            payload = context_orchestration.build_cognitive_context(
                "anything without sparks",
                conn=conn,
            )
        finally:
            conn.close()
        self.assertIn("core_sparks", payload)
        trace = payload.get("trace") or {}
        self.assertTrue(trace.get("fallback_used"))


if __name__ == "__main__":
    unittest.main()
