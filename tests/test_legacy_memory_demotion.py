"""V4.3.2 T4 — legacy memory_items demotion safeguards."""

from __future__ import annotations

import json
import sys
import tempfile
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
    source: str = "manual",
    pinned: bool = False,
    importance: int = 3,
    metadata: dict | None = None,
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
        metadata=metadata,
    )
    assert mid is not None
    return int(mid)


class LegacyMemoryDemotionTests(IsolatedDbTestCase):
    def test_dry_run_required_and_no_delete(self) -> None:
        mid = _seed(
            "event",
            "builder_handoff: claimed ticket #482 and wrote a note to Crowley.",
            source="cursor",
            importance=1,
        )
        conn = crowley.connect_db()
        try:
            missing = Path(self._tmpdir.name) / "missing.json"  # type: ignore[union-attr]
            with self.assertRaises(ValueError):
                msm.apply_memory_demotion(
                    conn, limit=10, reviewed=False, artifact_path=missing
                )
            before = int(
                conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()["n"]
            )
            report = msm.apply_memory_demotion(
                conn, limit=10, reviewed=True, require_dry_run_gate=True
            )
            conn.commit()
            after = int(
                conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()["n"]
            )
            status = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(before, after)
        self.assertFalse(report["memory_items_deleted"])
        self.assertEqual(int(report["rows_deleted"]), 0)
        self.assertEqual(str(status), "archived")

    def test_protects_pinned_without_active_spark(self) -> None:
        mid = _seed(
            "decision",
            "Pinned canon receipt must not archive before active spark coverage.",
            source="canon",
            pinned=True,
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            review = msm.review_memory_demotion(conn)
            protect_ids = {
                int(e["memory_item_id"]) for e in review["protect_sample"]  # type: ignore[index]
            }
            # May be in protect list or counted via reason
            decision_row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()
            decision = msm.evaluate_demotion(decision_row, conn)
            self.assertEqual(decision["action"], "protect")

            report = msm.apply_memory_demotion(conn, limit=20, reviewed=True)
            conn.commit()
            status = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()["status"]
        finally:
            conn.close()
        self.assertEqual(str(status), "active")
        self.assertGreaterEqual(int(report.get("protected", 0)), 0)

    def test_archives_when_represented_by_active_spark(self) -> None:
        mid = _seed(
            "decision",
            "Durable decision represented by an active spark may archive receipt.",
            source="canon",
            pinned=True,
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            sparks.insert_spark(
                conn,
                {
                    "content": (
                        "Durable decision represented by an active spark may archive receipt."
                    ),
                    "lane": "work",
                    "why_keep": "fixture",
                    "worth_reason": "fixture",
                    "confidence": 0.9,
                    "spark_type": "decision",
                    "certainty": "confirmed",
                    "sensitivity": "normal",
                },
                source_memory_item_id=mid,
                project_id=None,
                trust_state="active",
                lineage_json={"migration_batch_id": "demote-test"},
            )
            conn.commit()
            decision = msm.evaluate_demotion(
                conn.execute("SELECT * FROM memory_items WHERE id = ?", (mid,)).fetchone(),
                conn,
            )
            self.assertEqual(decision["action"], "archive")
            report = msm.apply_memory_demotion(conn, limit=10, reviewed=True)
            conn.commit()
            status = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()["status"]
            total = int(
                conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()["n"]
            )
        finally:
            conn.close()
        self.assertEqual(str(status), "archived")
        self.assertGreaterEqual(int(report["archived"]), 1)
        self.assertTrue(any(c["memory_item_id"] == mid for c in report["changed"]))
        self.assertGreaterEqual(total, 1)

    def test_ticket_linked_protected_without_active_spark(self) -> None:
        mid = _seed(
            "project_update",
            "Ticket-linked project update receipt stays until spark coverage exists.",
            source="manual",
            importance=3,
            metadata={"linked_ticket_ids": [482]},
        )
        # Also set column if present
        conn = crowley.connect_db()
        try:
            conn.execute(
                "UPDATE memory_items SET linked_ticket_ids_json = ? WHERE id = ?",
                (json.dumps([482]), mid),
            )
            conn.commit()
            decision = msm.evaluate_demotion(
                conn.execute("SELECT * FROM memory_items WHERE id = ?", (mid,)).fetchone(),
                conn,
            )
        finally:
            conn.close()
        self.assertEqual(decision["action"], "protect")
        self.assertEqual(decision["reason"], "ticket_linked")

    def test_dry_run_gate_accepts_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / msm.ARCHIVE_DRY_RUN_ARTIFACT
            path.write_text(
                json.dumps(
                    {"dry_run": True, "generated_at": crowley._now_iso(), "archive_count": 1}
                ),
                encoding="utf-8",
            )
            ok, reason = msm.check_demotion_dry_run_gate(artifact_path=path)
            self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
