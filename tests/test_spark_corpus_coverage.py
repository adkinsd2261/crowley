"""V4.3.2 T1 — corpus coverage targets and candidate tiers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import memory_spark_migration as msm  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _seed(
    memory_type: str,
    content: str,
    *,
    status: str = "active",
    source: str = "manual",
    importance: int = 3,
    pinned: bool = False,
) -> int:
    mid = crowley.save_memory_item(
        memory_type,
        content,
        summary=content,
        source=source,
        importance=importance,
        pinned=pinned,
        status=status,
        confidence=0.9,
        agent_id="system" if pinned else None,
    )
    assert mid is not None
    return int(mid)


class SparkCorpusCoverageTests(IsolatedDbTestCase):
    def test_coverage_report_includes_targets_and_progress(self) -> None:
        _seed(
            "decision",
            "Canon pinned decision for coverage target progress tracking.",
            source="canon",
            pinned=True,
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            report = msm.build_coverage_report(conn)
        finally:
            conn.close()
        self.assertTrue(report["read_only"])
        self.assertIn("active_or_pinned_sparks_min", report["targets"])
        self.assertIn("total_sparks_with_lineage_min", report["targets"])
        self.assertIn("active_or_pinned_sparks", report["progress"])
        self.assertIn("gaps", report)
        self.assertIn("tier_remaining", report)
        self.assertGreaterEqual(int(report["candidate_include_count"]), 1)

    def test_tier_a_and_b_rank_before_ticket_chatter(self) -> None:
        tier_a = _seed(
            "decision",
            "Pinned canon current-state decision about spark-first memory log.",
            source="canon",
            pinned=True,
            importance=5,
        )
        tier_b = _seed(
            "constraint",
            "Do not bulk dump memory_items; migrate value with bounded batches.",
            source="manual",
            importance=4,
        )
        chatter = _seed(
            "decision",
            "APPROVE #360 plan for Cursor implementation with amendments.",
            source="codex",
            importance=4,
        )
        conn = crowley.connect_db()
        try:
            report = msm.select_candidates(conn, limit=20)
        finally:
            conn.close()
        ids = [int(c["memory_item_id"]) for c in report["candidates"]]  # type: ignore[index]
        tiers = {int(c["memory_item_id"]): c["tier"] for c in report["candidates"]}  # type: ignore[index]
        self.assertIn(tier_a, ids)
        self.assertIn(tier_b, ids)
        self.assertNotIn(chatter, ids)
        self.assertEqual(tiers[tier_a], "A")
        self.assertEqual(tiers[tier_b], "B")
        # A before B
        self.assertLess(ids.index(tier_a), ids.index(tier_b))
        skip = report["skip_reason_counts"]
        self.assertGreaterEqual(int(skip.get("ticket_chatter", 0)), 1)

    def test_tier_d_excludes_receipts_qa_and_sidequest(self) -> None:
        _seed(
            "project_update",
            "builder_handoff: claimed ticket #479 and ran cursor_sync --after.",
            source="cursor",
            importance=2,
        )
        _seed(
            "event",
            "Recovery complete: codebase is back; side-quest discarded/quarantined.",
            source="codex",
            importance=2,
        )
        keep = _seed(
            "lesson",
            "Tiered migration keeps receipts out of the living spark store.",
            source="manual",
            importance=4,
        )
        conn = crowley.connect_db()
        try:
            report = msm.select_candidates(conn, limit=20)
        finally:
            conn.close()
        ids = {int(c["memory_item_id"]) for c in report["candidates"]}  # type: ignore[index]
        self.assertIn(keep, ids)
        self.assertEqual(
            next(c["tier"] for c in report["candidates"] if int(c["memory_item_id"]) == keep),
            "B",
        )
        remaining = report["tier_remaining"]
        self.assertIn("A", remaining)
        self.assertIn("B", remaining)
        self.assertIn("C", remaining)
        self.assertIn("D", remaining)

    def test_tier_filter_limits_to_requested_tiers(self) -> None:
        _seed(
            "decision",
            "Tier A only filter should exclude ordinary tier B lessons here.",
            source="canon",
            pinned=True,
            importance=5,
        )
        _seed(
            "lesson",
            "Ordinary durable lesson belongs in tier B not tier A filter.",
            source="manual",
            importance=4,
        )
        conn = crowley.connect_db()
        try:
            report = msm.select_candidates(conn, limit=20, tiers=frozenset({"A"}))
        finally:
            conn.close()
        self.assertEqual(report["allowed_tiers"], ["A"])
        for cand in report["candidates"]:
            self.assertEqual(cand["tier"], "A")


if __name__ == "__main__":
    unittest.main()
