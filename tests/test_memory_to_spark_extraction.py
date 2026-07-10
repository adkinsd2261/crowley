"""V4.3.1 T3 — memory item to spark extraction dry-run."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import memory_spark_migration as msm  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _seed(
    memory_type: str,
    content: str,
    *,
    source: str = "canon",
    importance: int = 4,
    pinned: bool = False,
) -> int:
    mid = crowley.save_memory_item(
        memory_type,
        content,
        summary=content,
        source=source,
        importance=importance,
        pinned=pinned,
        status="active",
        confidence=0.9,
        agent_id="system" if pinned else None,
    )
    assert mid is not None
    return int(mid)


class MemoryToSparkExtractionDryRunTests(IsolatedDbTestCase):
    def test_dry_run_creates_no_sparks_and_no_memory_mutation(self) -> None:
        mid = _seed(
            "decision",
            "Every migrated spark preserves source_memory_item_id and lineage.",
            pinned=True,
        )
        conn = crowley.connect_db()
        try:
            status_before = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()["status"]
            report = msm.dry_run_extract(conn, limit=10, allow_llm=False)
            sparks_n = int(conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()["n"])
            status_after = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()["status"]
        finally:
            conn.close()
        self.assertTrue(report["dry_run"])
        self.assertEqual(sparks_n, 0)
        self.assertEqual(status_before, status_after)
        self.assertGreaterEqual(int(report["proposed_spark_count"]), 1)

    def test_deterministic_short_row_passes_validate_with_lineage(self) -> None:
        mid = _seed(
            "constraint",
            "Do not bulk dump memory_items into sparks; migrate value only.",
            source="canon",
            pinned=True,
        )
        conn = crowley.connect_db()
        try:
            report = msm.dry_run_extract(conn, limit=5, batch_id="test-batch-1")
        finally:
            conn.close()
        found = None
        for item in report["items"]:
            if int(item["memory_item_id"]) == mid:  # type: ignore[index]
                found = item
                break
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["status"], "proposed")
        proposals = found["proposals"]
        self.assertGreaterEqual(len(proposals), 1)  # type: ignore[arg-type]
        prop = proposals[0]  # type: ignore[index]
        spark = prop["spark"]
        validated = sparks.validate_spark(spark)
        self.assertTrue(validated.ok)
        self.assertLessEqual(len(str(spark["content"])), 300)
        self.assertEqual(int(prop["source_memory_item_id"]), mid)
        lineage = prop["lineage_json"]
        self.assertEqual(lineage["migration_batch_id"], "test-batch-1")
        self.assertEqual(int(lineage["source_memory_item_id"]), mid)
        self.assertEqual(str(spark["spark_type"]), "fact")
        self.assertEqual(str(spark["certainty"]), "confirmed")

    def test_long_row_without_llm_stays_tentative_or_skipped(self) -> None:
        long_text = (
            "Ambiguous long project narrative. " * 40
            + "This should not become a confirmed decision spark without LLM."
        )
        mid = _seed("summary", long_text, source="manual", importance=3, pinned=False)
        conn = crowley.connect_db()
        try:
            report = msm.dry_run_extract(conn, limit=10, allow_llm=False)
        finally:
            conn.close()
        found = None
        for item in report["items"]:
            if int(item["memory_item_id"]) == mid:  # type: ignore[index]
                found = item
                break
        # May be skipped as low-signal summary or proposed as tentative clip
        if found is None:
            # excluded at selection — also acceptable for ambiguous long summary
            return
        if found["status"] == "proposed":
            spark = found["proposals"][0]["spark"]  # type: ignore[index]
            self.assertEqual(str(spark["certainty"]), "tentative")
            self.assertLessEqual(float(spark["confidence"]), 0.6)

    def test_secret_content_rejected_by_validation(self) -> None:
        mid = _seed(
            "decision",
            "Rotate key sk-abcdefghijklmnopqrstuvwxyz0123456789 now.",
            source="manual",
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            row = conn.execute("SELECT * FROM memory_items WHERE id = ?", (mid,)).fetchone()
            result = msm.propose_sparks_for_row(row, batch_id="sec")
        finally:
            conn.close()
        self.assertEqual(result["status"], "rejected")

    def test_dry_run_does_not_invoke_upsert(self) -> None:
        _seed(
            "lesson",
            "Dry-run extraction must never call upsert_spark_with_dedup.",
            source="manual",
        )
        with mock.patch.object(sparks, "upsert_spark_with_dedup") as upsert:
            conn = crowley.connect_db()
            try:
                msm.dry_run_extract(conn, limit=5)
            finally:
                conn.close()
            upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
