#!/usr/bin/env python3
"""V4.2 T4 — spark promotion policy tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import context_resolution  # noqa: E402
import crowley  # noqa: E402
import spark_lifecycle  # noqa: E402
import spark_retrieval  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Promotion policy keeps confirmed sparks retrieval-ready.",
        "lane": "work",
        "why_keep": "Validates candidate to active transitions.",
        "worth_reason": "Supports V4.2 promotion policy.",
        "confidence": 0.8,
        "sensitivity": "normal",
        "certainty": "confirmed",
    }
    base.update(overrides)
    return base


class SparkPromotionTests(IsolatedDbTestCase):
    def _project_id(self) -> int:
        row = crowley.get_active_project()
        assert row is not None
        return int(row["id"])

    def _insert(
        self,
        conn,
        *,
        trust_state: str = "candidate",
        certainty: str = "confirmed",
        sensitivity: str = "normal",
        confidence: float = 0.8,
        project_id: int | None = None,
    ) -> int:
        spark_id = sparks.insert_spark(
            conn,
            _valid_spark(
                confidence=confidence,
                sensitivity=sensitivity,
                certainty=certainty,
            ),
            source_memory_item_id=1,
            project_id=project_id if project_id is not None else self._project_id(),
            trust_state=trust_state,
        )
        conn.commit()
        return spark_id

    def test_auto_promote_confirmed_candidate(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn)
            result = spark_lifecycle.promote_spark_to_active(conn, spark_id)
            conn.commit()
            row = conn.execute(
                "SELECT trust_state, lineage_json FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertTrue(result.ok)
            self.assertEqual(str(row["trust_state"]), "active")
            lineage = json.loads(str(row["lineage_json"] or "{}"))
            self.assertEqual(lineage.get("promotion_source"), "auto_ingest")
            self.assertIn("promoted_at", lineage)
        finally:
            conn.close()

    def test_tentative_stays_candidate_on_auto_promote(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, certainty="tentative")
            result = spark_lifecycle.promote_spark_to_active(conn, spark_id)
            row = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertFalse(result.ok)
            self.assertEqual(result.reason, "tentative")
            self.assertEqual(str(row["trust_state"]), "candidate")
        finally:
            conn.close()

    def test_exploratory_stays_candidate_on_auto_promote(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, certainty="exploratory")
            result = spark_lifecycle.promote_spark_to_active(conn, spark_id)
            self.assertFalse(result.ok)
            self.assertEqual(result.reason, "exploratory")
        finally:
            conn.close()

    def test_sensitive_confirmed_not_auto_promoted(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, sensitivity="sensitive")
            result = spark_lifecycle.promote_spark_to_active(conn, spark_id)
            self.assertFalse(result.ok)
            self.assertEqual(result.reason, "sensitive")
        finally:
            conn.close()

    def test_manual_promote_tentative_candidate(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn, certainty="tentative")
            result = spark_lifecycle.promote_spark_to_active(
                conn,
                spark_id,
                manual=True,
                promoted_by="test",
                promotion_source="cognitive_seed",
            )
            conn.commit()
            row = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertTrue(result.ok)
            self.assertEqual(str(row["trust_state"]), "active")
        finally:
            conn.close()

    def test_dry_run_does_not_mutate(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn)
            result = spark_lifecycle.promote_spark_to_active(conn, spark_id, dry_run=True)
            row = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(str(row["trust_state"]), "candidate")
        finally:
            conn.close()

    def test_maintenance_reports_promotion_candidates(self) -> None:
        conn = crowley.connect_db()
        try:
            spark_id = self._insert(conn)
            result = spark_lifecycle.run_spark_lifecycle_maintenance(
                conn,
                dry_run=True,
                project_id=self._project_id(),
            )
            self.assertIn(spark_id, result.promotion_candidates)
            self.assertEqual(result.promotions_applied, 0)
        finally:
            conn.close()

    def test_count_cold_start_sparks_includes_confirmed_candidates(self) -> None:
        conn = crowley.connect_db()
        try:
            project_id = self._project_id()
            for index in range(8):
                self._insert(
                    conn,
                    certainty="confirmed",
                    trust_state="candidate",
                    project_id=project_id,
                )
            active_count = context_resolution.count_active_sparks(
                conn,
                project_id=project_id,
            )
            cold_start_count = context_resolution.count_cold_start_sparks(
                conn,
                project_id=project_id,
            )
            self.assertEqual(active_count, 0)
            self.assertEqual(cold_start_count, 8)
        finally:
            conn.close()

    def test_confirmed_ranks_above_tentative_with_same_inputs(self) -> None:
        conn = crowley.connect_db()
        try:
            project_id = self._project_id()
            confirmed_id = self._insert(
                conn,
                certainty="confirmed",
                trust_state="active",
                project_id=project_id,
            )
            tentative_id = self._insert(
                conn,
                certainty="tentative",
                trust_state="active",
                project_id=project_id,
            )
            conn.execute(
                """
                UPDATE sparks
                SET base_confidence = 0.8, confidence = 0.8,
                    created_at = '2026-07-01T00:00:00+00:00',
                    updated_at = '2026-07-01T00:00:00+00:00'
                WHERE id IN (?, ?)
                """,
                (confirmed_id, tentative_id),
            )
            conn.commit()
            ranked = spark_retrieval.retrieve_sparks(
                "promotion policy confirmed tentative",
                limit=10,
                project_id=project_id,
                conn=conn,
                bump_access=False,
            )
            scores = {item.spark_id: item.score for item in ranked}
            self.assertGreater(scores[confirmed_id], scores[tentative_id])
            confirmed = next(item for item in ranked if item.spark_id == confirmed_id)
            self.assertIn("certainty_multiplier", confirmed.score_breakdown)
            self.assertEqual(confirmed.score_breakdown["certainty_multiplier"], 1.0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
