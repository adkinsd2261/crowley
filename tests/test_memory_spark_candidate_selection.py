"""V4.3.1 T2 — deterministic memory→spark candidate selection."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

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


class MemorySparkCandidateSelectionTests(IsolatedDbTestCase):
    def test_selector_is_dry_run_read_only(self) -> None:
        _seed(
            "decision",
            "Pinned canon decisions migrate first into the spark corpus.",
            source="canon",
            pinned=True,
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            report = msm.select_candidates(conn, limit=20)
            sparks_n = int(conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()["n"])
        finally:
            conn.close()
        self.assertTrue(report["dry_run"])
        self.assertEqual(sparks_n, 0)
        self.assertGreaterEqual(int(report["included_count"]), 1)

    def test_excludes_merged_rejected_staged_and_already_linked(self) -> None:
        keep = _seed(
            "decision",
            "Keep this durable decision for migration candidate selection.",
            source="canon",
            pinned=True,
        )
        _seed(
            "decision",
            "Merged decision should be excluded from migration candidates.",
            status="merged",
        )
        _seed(
            "constraint",
            "Rejected constraint should be excluded from migration candidates.",
            status="rejected",
        )
        _seed(
            "lesson",
            "Staged lesson should be excluded from migration candidates now.",
            status="staged",
        )
        linked = _seed(
            "preference",
            "Already linked preference must be excluded from candidate list.",
            source="manual",
        )
        conn = crowley.connect_db()
        try:
            sparks.insert_spark(
                conn,
                {
                    "content": "Already linked preference must be excluded from candidate list.",
                    "lane": "operating_style",
                    "why_keep": "fixture",
                    "worth_reason": "fixture lineage",
                    "confidence": 0.8,
                    "spark_type": "intent",
                    "certainty": "confirmed",
                    "sensitivity": "normal",
                },
                source_memory_item_id=linked,
                project_id=None,
                trust_state="candidate",
            )
            conn.commit()
            report = msm.select_candidates(conn, limit=50)
        finally:
            conn.close()

        ids = {int(c["memory_item_id"]) for c in report["candidates"]}  # type: ignore[index]
        self.assertIn(keep, ids)
        self.assertNotIn(linked, ids)
        skip = report["skip_reason_counts"]
        self.assertGreaterEqual(int(skip.get("status_merged", 0)), 1)
        self.assertGreaterEqual(int(skip.get("status_rejected", 0)), 1)
        self.assertGreaterEqual(int(skip.get("status_staged", 0)), 1)
        self.assertGreaterEqual(int(skip.get("already_linked", 0)), 1)

    def test_pinned_canon_and_decisions_rank_first(self) -> None:
        low = _seed(
            "summary",
            "Ordinary summary ranks after pinned canon and durable decisions.",
            source="implicit",
            importance=2,
        )
        decision = _seed(
            "decision",
            "Durable project decision that should rank near the top of candidates.",
            source="manual",
            importance=4,
        )
        pinned = _seed(
            "summary",
            "Pinned canon summary of current Crowley architecture direction.",
            source="canon",
            pinned=True,
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            report = msm.select_candidates(conn, limit=10)
        finally:
            conn.close()
        ids = [int(c["memory_item_id"]) for c in report["candidates"]]  # type: ignore[index]
        self.assertTrue(ids)
        self.assertEqual(ids[0], pinned)
        self.assertIn(decision, ids)
        # low may or may not be included depending on type rules; if included, after
        if low in ids:
            self.assertGreater(ids.index(low), ids.index(pinned))

    def test_skips_handoff_and_sidequest_noise(self) -> None:
        _seed(
            "project_update",
            "builder_handoff: claimed ticket #469 and ran cursor_sync --after.",
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
            "decision",
            "Migrate value not rows; memory_items remain receipts and fallback.",
            source="canon",
            pinned=True,
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            report = msm.select_candidates(conn, limit=20)
        finally:
            conn.close()
        ids = {int(c["memory_item_id"]) for c in report["candidates"]}  # type: ignore[index]
        self.assertIn(keep, ids)
        skip = report["skip_reason_counts"]
        self.assertTrue(
            int(skip.get("handoff_receipt", 0))
            + int(skip.get("sidequest_noise", 0))
            + int(skip.get("low_signal_project_update", 0))
            + int(skip.get("type_excluded", 0))
            >= 1
        )
        self.assertIn("include_reason_counts", report)
        self.assertIn("skip_reason_counts", report)


if __name__ == "__main__":
    unittest.main()
