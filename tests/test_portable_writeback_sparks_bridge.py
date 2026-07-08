#!/usr/bin/env python3
"""V4 T17 — portable writeback dual-write into sparks table."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import portable_writeback_sparks_bridge  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class PortableWritebackSparksBridgeTests(IsolatedDbTestCase):
    def _valid_payload(self) -> dict[str, object]:
        return json.loads((FIXTURES / "portable_writeback_valid.json").read_text())

    def test_valid_writeback_creates_memory_items_and_v4_sparks(self) -> None:
        result = crowley.ingest_terminal_writeback(self._valid_payload())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["spark_ids"]), 2)
        self.assertEqual(len(result["v4_spark_ids"]), 2)
        self.assertEqual(len(result["v4_spark_actions"]), 2)

        conn = crowley.connect_db()
        try:
            for memory_id, v4_id, action in zip(
                result["spark_ids"],
                result["v4_spark_ids"],
                result["v4_spark_actions"],
            ):
                memory = conn.execute(
                    "SELECT * FROM memory_items WHERE id = ?",
                    (memory_id,),
                ).fetchone()
                spark = conn.execute(
                    "SELECT * FROM sparks WHERE id = ?",
                    (v4_id,),
                ).fetchone()
                assert memory is not None and spark is not None
                meta = crowley._memory_item_metadata(memory)
                self.assertEqual(int(meta["v4_spark_id"]), int(v4_id))
                self.assertEqual(meta["v4_spark_action"], action)
                self.assertEqual(int(spark["source_memory_item_id"]), int(memory_id))
                self.assertEqual(str(spark["trust_state"]), "candidate")
                lineage = json.loads(str(spark["lineage_json"]))
                self.assertTrue(lineage.get("portable_writeback"))
                self.assertEqual(
                    int(lineage["session_receipt_id"]),
                    int(result["session_receipt_id"]),
                )
                self.assertEqual(int(lineage["memory_item_id"]), int(memory_id))
        finally:
            conn.close()

    def test_worth_reason_fallback_from_why_keep(self) -> None:
        mapped = portable_writeback_sparks_bridge.portable_spark_to_v4(
            {
                "content": "Portable sparks need worth_reason for V4 validation.",
                "lane": "work",
                "why_keep": "Keeps V4 schema satisfied.",
                "confidence": 0.7,
                "sensitivity": "normal",
            }
        )
        self.assertEqual(mapped["worth_reason"], "Keeps V4 schema satisfied.")

        result = crowley.ingest_terminal_writeback(self._valid_payload())
        conn = crowley.connect_db()
        try:
            spark = conn.execute(
                "SELECT worth_reason FROM sparks WHERE id = ?",
                (result["v4_spark_ids"][0],),
            ).fetchone()
            assert spark is not None
            self.assertTrue(str(spark["worth_reason"]))
        finally:
            conn.close()

    def test_sensitivity_mapped_to_sparks_row(self) -> None:
        result = crowley.ingest_terminal_writeback(self._valid_payload())
        conn = crowley.connect_db()
        try:
            rows = conn.execute(
                """
                SELECT sensitivity, trust_state
                FROM sparks
                WHERE id IN (?, ?)
                ORDER BY id
                """,
                tuple(result["v4_spark_ids"]),
            ).fetchall()
            sensitivities = {str(row["sensitivity"]) for row in rows}
            self.assertIn("normal", sensitivities)
            self.assertIn("sensitive", sensitivities)
            for row in rows:
                self.assertEqual(str(row["trust_state"]), "candidate")
        finally:
            conn.close()

    def test_dedup_merge_returns_keeper_v4_spark_id(self) -> None:
        payload = self._valid_payload()
        first = crowley.ingest_terminal_writeback(payload)
        second = crowley.ingest_terminal_writeback(payload)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(len(first["v4_spark_ids"]), 2)
        self.assertEqual(len(second["v4_spark_ids"]), 2)
        self.assertEqual(first["v4_spark_ids"], second["v4_spark_ids"])
        self.assertTrue(any(action == "merged" for action in second["v4_spark_actions"]))

        conn = crowley.connect_db()
        try:
            count = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            assert count is not None
            self.assertEqual(int(count["n"]), 2)
        finally:
            conn.close()

    def test_invalid_writeback_does_not_create_v4_sparks(self) -> None:
        raw = (FIXTURES / "portable_writeback_invalid_spark.json").read_text()
        conn = crowley.connect_db()
        try:
            before = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            assert before is not None
            before_count = int(before["n"])
        finally:
            conn.close()

        result = crowley.ingest_terminal_writeback(raw)
        self.assertEqual(result["status"], "error")

        conn = crowley.connect_db()
        try:
            after = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
            assert after is not None
            self.assertEqual(int(after["n"]), before_count)
        finally:
            conn.close()

    def test_legacy_portable_ingest_response_fields_preserved(self) -> None:
        result = crowley.ingest_terminal_writeback(self._valid_payload())
        self.assertIn("session_receipt_id", result)
        self.assertIn("spark_ids", result)
        self.assertIn("rejected_sparks", result)
        self.assertIn("skipped_do_not_save", result)
        self.assertIn("metadata", result)


if __name__ == "__main__":
    import unittest

    unittest.main()
