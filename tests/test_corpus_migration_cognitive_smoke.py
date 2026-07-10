"""V4.3.1 T5 — cognitive context smoke for migrated sparks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import context_orchestration  # noqa: E402
import crowley  # noqa: E402
import memory_spark_migration as msm  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class CorpusMigrationCognitiveSmokeTests(IsolatedDbTestCase):
    def test_cognitive_context_returns_migrated_sparks_with_lineage(self) -> None:
        mid = crowley.save_memory_item(
            "decision",
            "Crowley keeps sparks as the living store before V4.4 chat wire.",
            summary="Crowley keeps sparks as the living store before V4.4 chat wire.",
            source="canon",
            importance=5,
            pinned=True,
            status="active",
            confidence=0.95,
            agent_id="system",
        )
        assert mid is not None
        conn = crowley.connect_db()
        try:
            report = msm.apply_extract_batch(
                conn,
                limit=5,
                batch_id="smoke-batch",
                promote_policy=True,
            )
            conn.commit()
            self.assertGreaterEqual(int(report["inserted"]), 1)

            # Raise active count above cold-start threshold with fillers that
            # share the same project so retrieval stays on spark path.
            project = crowley.get_active_project()
            project_id = int(project["id"]) if project is not None else None
            for idx in range(10):
                sparks.insert_spark(
                    conn,
                    {
                        "content": (
                            f"Active filler spark {idx} for cognitive smoke coverage."
                        ),
                        "lane": "work",
                        "why_keep": "Raises active spark count above cold-start.",
                        "worth_reason": "Keeps smoke on spark retrieval path.",
                        "confidence": 0.8,
                        "sensitivity": "normal",
                    },
                    source_memory_item_id=int(mid),
                    project_id=project_id,
                    trust_state="active",
                    lineage_json={
                        "migration": "v4.3.1_spark_corpus",
                        "migration_batch_id": "smoke-filler",
                        "source_memory_item_id": int(mid),
                    },
                )
            conn.commit()

            payload = context_orchestration.build_cognitive_context(
                "living store before V4.4 chat wire",
                lanes="work",
                project_id=project_id,
                conn=conn,
            )
        finally:
            conn.close()

        core = payload.get("core_sparks") or []
        self.assertTrue(core, payload)
        # At least one spark should carry migration lineage via source id
        lineage = (payload.get("trace") or {}).get("lineage") or []
        migrated = [
            item
            for item in lineage
            if int(item.get("source_memory_item_id") or 0) == int(mid)
        ]
        self.assertTrue(migrated, lineage)
        for item in migrated:
            lin = item.get("lineage") or {}
            self.assertTrue(
                "migration" in lin
                or "migration_batch_id" in lin
                or "memory_item_id" in lin
                or "source_memory_item_id" in lin
            )

    def test_cold_start_fallback_still_available(self) -> None:
        """Empty spark corpus still allows cognitive context without crash."""
        conn = crowley.connect_db()
        try:
            payload = context_orchestration.build_cognitive_context(
                "anything",
                conn=conn,
            )
        finally:
            conn.close()
        self.assertIn("core_sparks", payload)
        self.assertIn("supporting_sparks", payload)
        # Cold-start path may use memory_items fallback; must not raise.
        self.assertIsInstance(payload.get("core_sparks"), list)
        self.assertTrue((payload.get("trace") or {}).get("fallback_used"))


if __name__ == "__main__":
    unittest.main()
