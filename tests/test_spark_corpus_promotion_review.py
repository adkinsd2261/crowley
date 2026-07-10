"""V4.3.2 T3 — promotion review for active/pinned spark coverage."""

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


def _seed_memory(
    memory_type: str,
    content: str,
    *,
    source: str = "manual",
    pinned: bool = False,
    importance: int = 4,
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


def _insert_candidate(
    conn,
    *,
    content: str,
    memory_id: int,
    spark_type: str = "decision",
    certainty: str = "confirmed",
    confidence: float = 0.9,
    lane: str = "work",
) -> int:
    return sparks.insert_spark(
        conn,
        {
            "content": content,
            "lane": lane,
            "why_keep": "Promotion review fixture.",
            "worth_reason": "Tests durable promotion policy.",
            "confidence": confidence,
            "spark_type": spark_type,
            "certainty": certainty,
            "sensitivity": "normal",
        },
        source_memory_item_id=memory_id,
        project_id=None,
        trust_state="candidate",
        lineage_json={
            "migration": "v4.3.2_spark_corpus",
            "migration_batch_id": "promo-test",
            "source_memory_item_id": memory_id,
        },
    )


class SparkCorpusPromotionReviewTests(IsolatedDbTestCase):
    def test_review_dry_run_lists_promote_and_holds(self) -> None:
        durable_mid = _seed_memory(
            "constraint",
            "Sparks are the living store; memory_items remain receipts only.",
            source="manual",
        )
        chatter_mid = _seed_memory(
            "decision",
            "APPROVE #360 plan for Cursor implementation with amendments now.",
            source="codex",
        )
        conn = crowley.connect_db()
        try:
            promote_id = _insert_candidate(
                conn,
                content="Sparks are the living store; memory_items remain receipts only.",
                memory_id=durable_mid,
                spark_type="fact",
            )
            hold_id = _insert_candidate(
                conn,
                content="APPROVE #360 plan for Cursor implementation with amendments now.",
                memory_id=chatter_mid,
            )
            conn.commit()
            report = msm.review_migrated_sparks(conn)
        finally:
            conn.close()

        self.assertTrue(report["dry_run"])
        promote_ids = {int(e["spark_id"]) for e in report["promote"]}  # type: ignore[index]
        self.assertIn(promote_id, promote_ids)
        self.assertNotIn(hold_id, promote_ids)
        self.assertGreaterEqual(int(report["hold_count"]), 1)
        self.assertIn("reason_counts", report)
        # No writes
        conn = crowley.connect_db()
        try:
            trust = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?", (promote_id,)
            ).fetchone()["trust_state"]
        finally:
            conn.close()
        self.assertEqual(str(trust), "candidate")

    def test_apply_requires_limit_and_preserves_lineage(self) -> None:
        mid = _seed_memory(
            "decision",
            "Pinned canon decision about spark-first cognitive memory authority.",
            source="canon",
            pinned=True,
            importance=5,
        )
        conn = crowley.connect_db()
        try:
            with self.assertRaises(ValueError):
                msm.apply_promotion_review(conn, limit=0)
            with self.assertRaises(ValueError):
                msm.apply_promotion_review(
                    conn, limit=msm.PROMOTION_APPLY_LIMIT_CAP + 1
                )

            spark_id = _insert_candidate(
                conn,
                content="Pinned canon decision about spark-first cognitive memory authority.",
                memory_id=mid,
            )
            conn.commit()
            report = msm.apply_promotion_review(conn, limit=10)
            conn.commit()
            row = conn.execute(
                """
                SELECT trust_state, source_memory_item_id, lineage_json
                FROM sparks WHERE id = ?
                """,
                (spark_id,),
            ).fetchone()
        finally:
            conn.close()

        self.assertFalse(report["dry_run"])
        self.assertGreaterEqual(int(report["promoted"]), 1)
        self.assertIn(str(row["trust_state"]), {"active", "pinned"})
        self.assertEqual(int(row["source_memory_item_id"]), mid)
        self.assertIn("promo-test", str(row["lineage_json"]))

    def test_ticket_chatter_held_unless_whitelisted(self) -> None:
        mid = _seed_memory(
            "decision",
            "DENY #361 until the Actions registry contract regression is fixed.",
            source="codex",
        )
        conn = crowley.connect_db()
        try:
            spark_id = _insert_candidate(
                conn,
                content="DENY #361 until the Actions registry contract regression is fixed.",
                memory_id=mid,
            )
            conn.commit()
            review = msm.review_migrated_sparks(conn)
            self.assertNotIn(
                spark_id, {int(e["spark_id"]) for e in review["promote"]}  # type: ignore[index]
            )
            # Whitelist forces promote listing
            forced = msm.review_migrated_sparks(
                conn, whitelist_ids=frozenset({spark_id})
            )
            self.assertIn(
                spark_id, {int(e["spark_id"]) for e in forced["promote"]}  # type: ignore[index]
            )
            # Without apply, still candidate — no broad auto-promotion
            trust = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?", (spark_id,)
            ).fetchone()["trust_state"]
            self.assertEqual(str(trust), "candidate")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
