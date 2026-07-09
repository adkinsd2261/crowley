#!/usr/bin/env python3
"""V4 T16 — spark lifecycle maintenance and manual seed tests."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import cognitive_maintenance  # noqa: E402
import crowley  # noqa: E402
import spark_lifecycle  # noqa: E402
import sparks  # noqa: E402
import system_integrity  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from memory_tiers import MIN_CONFIDENCE  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Lifecycle maintenance keeps stale sparks out of active recall.",
        "lane": "work",
        "why_keep": "Supports operator hygiene without hard deletes.",
        "worth_reason": "Required for V4 cognitive maintenance.",
        "confidence": 0.8,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


class SparkLifecycleMaintenanceTests(IsolatedDbTestCase):
    def _project_id(self) -> int:
        row = crowley.get_active_project()
        assert row is not None
        return int(row["id"])

    def _insert(
        self,
        conn,
        *,
        trust_state: str = "active",
        access_count: int = 0,
        base_confidence: float = 0.8,
        created_at: str | None = None,
    ) -> int:
        spark_id = sparks.insert_spark(
            conn,
            _valid_spark(confidence=base_confidence),
            source_memory_item_id=1,
            project_id=self._project_id(),
            trust_state=trust_state,
        )
        if created_at is not None:
            conn.execute(
                """
                UPDATE sparks
                SET created_at = ?, base_confidence = ?, access_count = ?
                WHERE id = ?
                """,
                (created_at, base_confidence, access_count, spark_id),
            )
        else:
            conn.execute(
                "UPDATE sparks SET access_count = ?, base_confidence = ? WHERE id = ?",
                (access_count, base_confidence, spark_id),
            )
        return spark_id

    def test_low_usage_transitions_to_stale(self) -> None:
        conn = crowley.connect_db()
        try:
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).isoformat()
            spark_id = self._insert(
                conn,
                access_count=0,
                created_at=old_created,
            )
            result = spark_lifecycle.run_spark_lifecycle_maintenance(
                conn,
                dry_run=False,
                project_id=self._project_id(),
            )
            conn.commit()
            row = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIn(spark_id, result.stale_candidates)
            self.assertEqual(result.stale_applied, 1)
            self.assertEqual(str(row["trust_state"]), "stale")
        finally:
            conn.close()

    def test_pinned_spark_not_transitioned(self) -> None:
        conn = crowley.connect_db()
        try:
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).isoformat()
            spark_id = self._insert(
                conn,
                trust_state="pinned",
                created_at=old_created,
            )
            result = spark_lifecycle.run_spark_lifecycle_maintenance(
                conn,
                dry_run=False,
                project_id=self._project_id(),
            )
            conn.commit()
            row = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertNotIn(spark_id, result.stale_candidates)
            self.assertEqual(str(row["trust_state"]), "pinned")
        finally:
            conn.close()

    def test_stale_low_confidence_transitions_to_rejected(self) -> None:
        conn = crowley.connect_db()
        try:
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=120)
            ).isoformat()
            spark_id = self._insert(
                conn,
                trust_state="stale",
                base_confidence=0.8,
                created_at=old_created,
            )
            result = spark_lifecycle.run_spark_lifecycle_maintenance(
                conn,
                dry_run=False,
                project_id=self._project_id(),
            )
            conn.commit()
            row = conn.execute(
                "SELECT trust_state, confidence FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert row is not None
            self.assertIn(spark_id, result.rejected_candidates)
            self.assertEqual(result.rejected_applied, 1)
            self.assertEqual(str(row["trust_state"]), "rejected")
            self.assertLessEqual(float(row["confidence"]), MIN_CONFIDENCE + 0.01)
        finally:
            conn.close()

    def test_rejected_row_retained(self) -> None:
        conn = crowley.connect_db()
        try:
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=120)
            ).isoformat()
            spark_id = self._insert(
                conn,
                trust_state="stale",
                created_at=old_created,
            )
            spark_lifecycle.run_spark_lifecycle_maintenance(
                conn,
                dry_run=False,
                project_id=self._project_id(),
            )
            conn.commit()
            count = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            assert count is not None
            self.assertEqual(int(count["n"]), 1)
            row = conn.execute("SELECT trust_state FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            assert row is not None
            self.assertEqual(str(row["trust_state"]), "rejected")
        finally:
            conn.close()

    def test_dry_run_does_not_mutate(self) -> None:
        conn = crowley.connect_db()
        try:
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).isoformat()
            spark_id = self._insert(conn, created_at=old_created)
            before = conn.execute(
                "SELECT trust_state, confidence, updated_at FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            result = spark_lifecycle.run_spark_lifecycle_maintenance(
                conn,
                dry_run=True,
                project_id=self._project_id(),
            )
            after = conn.execute(
                "SELECT trust_state, confidence, updated_at FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert before is not None and after is not None
            self.assertIn(spark_id, result.stale_candidates)
            self.assertEqual(result.stale_applied, 0)
            self.assertEqual(before["trust_state"], after["trust_state"])
            self.assertEqual(before["confidence"], after["confidence"])
            self.assertEqual(before["updated_at"], after["updated_at"])
        finally:
            conn.close()

    def test_manual_seed_promotes_to_active_and_links_receipt(self) -> None:
        result = cognitive_maintenance.seed_manual_spark(
            _valid_spark(content="manual seed spark for maintenance tests"),
            project=crowley.DEFAULT_PROJECT_SLUG,
            source="cursor",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["trust_state"], "active")
        memory_item_id = int(result["memory_item_id"])
        spark_id = int(result["spark_id"])

        conn = crowley.connect_db()
        try:
            spark = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            memory = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (memory_item_id,),
            ).fetchone()
            assert spark is not None and memory is not None
            self.assertEqual(str(spark["trust_state"]), "active")
            self.assertEqual(int(spark["source_memory_item_id"]), memory_item_id)
            self.assertIn("Cognitive manual spark seed", str(memory["summary"]))
        finally:
            conn.close()

    def test_invalid_manual_seed_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cognitive_maintenance.seed_manual_spark(
                {"content": "", "lane": "work", "why_keep": "x", "worth_reason": "y", "confidence": 0.5},
                project=crowley.DEFAULT_PROJECT_SLUG,
            )

    def test_maintenance_api_defaults_dry_run(self) -> None:
        conn = crowley.connect_db()
        try:
            old_created = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).isoformat()
            spark_id = self._insert(conn, created_at=old_created)
            before = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            conn.commit()
        finally:
            conn.close()

        client = TestClient(crowley_app.app)
        res = client.post("/api/cognitive/maintenance", json={})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertTrue(data["dry_run"])
        self.assertIn(spark_id, data["stale_candidates"])
        self.assertEqual(data["stale_applied"], 0)

        conn = crowley.connect_db()
        try:
            after = conn.execute(
                "SELECT trust_state FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
            assert before is not None and after is not None
            self.assertEqual(before["trust_state"], after["trust_state"])
        finally:
            conn.close()

    def test_spark_seed_api_rejects_invalid_payload(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/cognitive/sparks",
            json={
                "content": "",
                "lane": "work",
                "why_keep": "missing content",
                "worth_reason": "invalid",
                "confidence": 0.5,
            },
        )
        self.assertEqual(res.status_code, 422, res.text)

    def test_dispatch_invariant_blocks_maintenance(self) -> None:
        client = TestClient(crowley_app.app)
        with mock.patch.object(
            system_integrity,
            "enforce_dispatch_invariants",
            return_value=(False, {"status": "error", "error": "invariant_violation"}),
        ):
            res = client.post("/api/cognitive/maintenance", json={"dry_run": True})
        self.assertEqual(res.status_code, 428, res.text)


if __name__ == "__main__":
    unittest.main()
