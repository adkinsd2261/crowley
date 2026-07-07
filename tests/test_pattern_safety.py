#!/usr/bin/env python3
"""V4 T12 — pattern safety gates tests."""

from __future__ import annotations

import inspect
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import patterns  # noqa: E402
import spark_extraction  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _valid_spark(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content": "Pattern safety keeps derived artifacts controlled.",
        "lane": "work",
        "why_keep": "Prevents patterns from driving memory state.",
        "worth_reason": "Supports safe pattern promotion.",
        "confidence": 0.7,
        "sensitivity": "normal",
    }
    base.update(overrides)
    return base


def _unit_vector(axis: int = 0) -> list[float]:
    vector = [0.0] * crowley.EMBED_DIM
    vector[axis] = 1.0
    return vector


class PatternSafetyTests(IsolatedDbTestCase):
    def _insert(
        self,
        conn,
        *,
        content: str,
        confidence: float = 0.7,
    ) -> int:
        spark_id = sparks.insert_spark(
            conn,
            _valid_spark(content=content, confidence=confidence),
            source_memory_item_id=1,
            project_id=None,
            trust_state="active",
        )
        sparks.index_spark_embedding(conn, spark_id, _unit_vector(), "test-model")
        return spark_id

    def _cluster(self, conn, label: str, confidence: float = 0.7) -> list[int]:
        return [
            self._insert(conn, content=f"{label} alpha", confidence=confidence),
            self._insert(conn, content=f"{label} bravo", confidence=confidence),
            self._insert(conn, content=f"{label} charlie", confidence=confidence),
        ]

    def _pattern_row(self, conn, pattern_id: int):
        return conn.execute(
            "SELECT * FROM patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()

    def test_safety_wrapper_auto_promotes_valid_pattern_to_active(self) -> None:
        conn = crowley.connect_db()
        try:
            ids = self._cluster(conn, "active promotion")

            result = patterns.create_pattern_with_safety(conn, ids)

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.action, "created")
            assert result.pattern_id is not None
            row = self._pattern_row(conn, result.pattern_id)
            assert row is not None
            self.assertEqual(row["trust_state"], patterns.PATTERN_ACTIVE_TRUST_STATE)
        finally:
            conn.close()

    def test_canon_promotion_blocked(self) -> None:
        conn = crowley.connect_db()
        try:
            created = patterns.create_pattern_from_sparks(
                conn,
                self._cluster(conn, "canon"),
            )
            assert created.pattern_id is not None

            result = patterns.promote_pattern_if_safe(
                conn,
                created.pattern_id,
                target_state="canon",
            )

            self.assertFalse(result.ok)
            row = self._pattern_row(conn, created.pattern_id)
            assert row is not None
            self.assertEqual(row["trust_state"], patterns.PATTERN_TRUST_STATE_CANDIDATE)
        finally:
            conn.close()

    def test_promotion_target_requires_exact_active(self) -> None:
        conn = crowley.connect_db()
        try:
            created = patterns.create_pattern_from_sparks(
                conn,
                self._cluster(conn, "strict target"),
            )
            assert created.pattern_id is not None

            result = patterns.promote_pattern_if_safe(
                conn,
                created.pattern_id,
                target_state="Active",
            )

            self.assertFalse(result.ok)
            row = self._pattern_row(conn, created.pattern_id)
            assert row is not None
            self.assertEqual(row["trust_state"], patterns.PATTERN_TRUST_STATE_CANDIDATE)
        finally:
            conn.close()

    def test_duplicate_candidate_promoted_without_recomputing_fields(self) -> None:
        conn = crowley.connect_db()
        try:
            ids = self._cluster(conn, "duplicate promotion")
            created = patterns.create_pattern_from_sparks(conn, ids)
            assert created.pattern_id is not None
            conn.execute(
                """
                UPDATE patterns
                SET reasoning = ?, content = ?
                WHERE id = ?
                """,
                ("custom reasoning", "custom content", created.pattern_id),
            )

            result = patterns.create_pattern_with_safety(conn, list(reversed(ids)))

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.action, "promoted")
            row = self._pattern_row(conn, created.pattern_id)
            assert row is not None
            self.assertEqual(row["trust_state"], patterns.PATTERN_ACTIVE_TRUST_STATE)
            self.assertEqual(row["reasoning"], "custom reasoning")
            self.assertEqual(row["content"], "custom content")
        finally:
            conn.close()

    def test_global_rate_limit_rejects_sixth_new_pattern(self) -> None:
        conn = crowley.connect_db()
        try:
            for i in range(patterns.PATTERN_RATE_LIMIT_PER_HOUR):
                result = patterns.create_pattern_with_safety(
                    conn,
                    self._cluster(conn, f"rate {i}"),
                )
                self.assertTrue(result.ok, result.errors)

            sixth = patterns.create_pattern_with_safety(
                conn,
                self._cluster(conn, "rate sixth"),
            )

            self.assertFalse(sixth.ok)
            self.assertIn("rate limit", sixth.errors[0])
            row = conn.execute("SELECT COUNT(*) AS n FROM patterns").fetchone()
            assert row is not None
            self.assertEqual(int(row["n"]), patterns.PATTERN_RATE_LIMIT_PER_HOUR)
        finally:
            conn.close()

    def test_duplicate_path_bypasses_rate_limit_and_promotes_candidate(self) -> None:
        conn = crowley.connect_db()
        try:
            duplicate_ids = self._cluster(conn, "duplicate at limit")
            created = patterns.create_pattern_from_sparks(conn, duplicate_ids)
            assert created.pattern_id is not None
            for i in range(patterns.PATTERN_RATE_LIMIT_PER_HOUR - 1):
                result = patterns.create_pattern_with_safety(
                    conn,
                    self._cluster(conn, f"filler {i}"),
                )
                self.assertTrue(result.ok, result.errors)

            result = patterns.create_pattern_with_safety(conn, duplicate_ids)

            self.assertTrue(result.ok, result.errors)
            self.assertEqual(result.action, "promoted")
            row = self._pattern_row(conn, created.pattern_id)
            assert row is not None
            self.assertEqual(row["trust_state"], patterns.PATTERN_ACTIVE_TRUST_STATE)
        finally:
            conn.close()

    def test_duplicate_existing_unsupported_state_rejected(self) -> None:
        conn = crowley.connect_db()
        try:
            ids = self._cluster(conn, "unsupported duplicate")
            created = patterns.create_pattern_from_sparks(conn, ids)
            assert created.pattern_id is not None
            conn.execute(
                "UPDATE patterns SET trust_state = 'stale' WHERE id = ?",
                (created.pattern_id,),
            )

            result = patterns.create_pattern_with_safety(conn, ids)

            self.assertFalse(result.ok)
            row = self._pattern_row(conn, created.pattern_id)
            assert row is not None
            self.assertEqual(row["trust_state"], "stale")
        finally:
            conn.close()

    def test_rate_limit_uses_created_at_not_updated_at(self) -> None:
        conn = crowley.connect_db()
        try:
            old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            for i in range(patterns.PATTERN_RATE_LIMIT_PER_HOUR):
                result = patterns.create_pattern_with_safety(
                    conn,
                    self._cluster(conn, f"old {i}"),
                )
                self.assertTrue(result.ok, result.errors)
                assert result.pattern_id is not None
                conn.execute(
                    """
                    UPDATE patterns
                    SET created_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (old, crowley._now_iso(), result.pattern_id),
                )

            fresh = patterns.create_pattern_with_safety(
                conn,
                self._cluster(conn, "fresh"),
            )

            self.assertTrue(fresh.ok, fresh.errors)
        finally:
            conn.close()

    def test_promotion_does_not_change_created_at(self) -> None:
        conn = crowley.connect_db()
        try:
            created = patterns.create_pattern_from_sparks(
                conn,
                self._cluster(conn, "created at stable"),
            )
            assert created.pattern_id is not None
            original = self._pattern_row(conn, created.pattern_id)
            assert original is not None

            result = patterns.promote_pattern_if_safe(conn, created.pattern_id)

            self.assertTrue(result.ok, result.errors)
            promoted = self._pattern_row(conn, created.pattern_id)
            assert promoted is not None
            self.assertEqual(promoted["created_at"], original["created_at"])
            self.assertEqual(promoted["trust_state"], patterns.PATTERN_ACTIVE_TRUST_STATE)
        finally:
            conn.close()

    def test_safety_wrapper_does_not_modify_source_spark_confidence(self) -> None:
        conn = crowley.connect_db()
        try:
            ids = self._cluster(conn, "confidence stable", confidence=0.73)
            before = {
                int(row["id"]): (
                    float(row["confidence"]),
                    float(row["base_confidence"]),
                )
                for row in conn.execute(
                    "SELECT id, confidence, base_confidence FROM sparks"
                ).fetchall()
            }

            result = patterns.create_pattern_with_safety(conn, ids)

            self.assertTrue(result.ok, result.errors)
            after = {
                int(row["id"]): (
                    float(row["confidence"]),
                    float(row["base_confidence"]),
                )
                for row in conn.execute(
                    "SELECT id, confidence, base_confidence FROM sparks"
                ).fetchall()
            }
            self.assertEqual(after, before)
        finally:
            conn.close()

    def test_lifecycle_boost_exposed_but_not_applied(self) -> None:
        self.assertEqual(patterns.pattern_lifecycle_boost(), 0.05)

    def test_extraction_still_does_not_read_patterns(self) -> None:
        source = inspect.getsource(spark_extraction)
        self.assertNotIn("patterns", source.lower())

    def test_atomic_create_rolls_back_if_promotion_fails(self) -> None:
        conn = crowley.connect_db()
        try:
            with mock.patch.object(
                patterns,
                "promote_pattern_if_safe",
                return_value=patterns.PatternCreationResult(
                    ok=False,
                    errors=["forced promotion failure"],
                ),
            ):
                result = patterns.create_pattern_with_safety(
                    conn,
                    self._cluster(conn, "rollback"),
                )

            self.assertFalse(result.ok)
            row = conn.execute("SELECT COUNT(*) AS n FROM patterns").fetchone()
            assert row is not None
            self.assertEqual(int(row["n"]), 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
