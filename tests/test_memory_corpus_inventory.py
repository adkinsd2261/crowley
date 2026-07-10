"""V4.3.1 T1 — memory corpus inventory (read-only)."""

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
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryCorpusInventoryTests(IsolatedDbTestCase):
    def test_inventory_is_read_only_and_schema_tolerant(self) -> None:
        crowley.save_memory_item(
            "decision",
            "Sparks are the living store; memory_items remain receipts.",
            summary="Sparks are the living store; memory_items remain receipts.",
            source="canon",
            importance=5,
            pinned=True,
            status="active",
            agent_id="system",
        )
        crowley.save_memory_item(
            "project_update",
            "Project update noise row for inventory counts only in this test.",
            summary="Project update noise row for inventory counts only in this test.",
            source="manual",
            importance=2,
            status="active",
        )

        before_items = crowley.connect_db()
        try:
            n_before = int(
                before_items.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()[
                    "n"
                ]
            )
            n_sparks_before = int(
                before_items.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()["n"]
            )
        finally:
            before_items.close()

        report = msm.build_inventory()
        self.assertTrue(report["read_only"])
        self.assertGreaterEqual(int(report["memory_items_total"]), 2)
        self.assertGreaterEqual(int(report["memory_items_active"]), 2)
        self.assertIn("sparks_total", report)
        self.assertIn("sparks_active", report)
        self.assertIn("sparks_pinned", report)
        self.assertIn("active_memory_items_without_spark_lineage", report)
        self.assertGreaterEqual(
            int(report["active_memory_items_without_spark_lineage"]), 2
        )
        self.assertIsInstance(report["memory_items_by_type"], list)
        self.assertIsInstance(report["memory_items_by_status"], list)
        self.assertIsInstance(report["memory_items_by_source"], list)
        self.assertIsInstance(report["memory_items_by_importance"], list)
        self.assertIsInstance(report["memory_items_by_pinned"], list)
        self.assertTrue(report["policy"]["no_bulk_dump"])
        self.assertTrue(report["policy"]["no_memory_items_delete"])

        after = crowley.connect_db()
        try:
            n_after = int(
                after.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()["n"]
            )
            n_sparks_after = int(
                after.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()["n"]
            )
        finally:
            after.close()
        self.assertEqual(n_before, n_after)
        self.assertEqual(n_sparks_before, n_sparks_after)

    def test_inventory_tolerates_missing_optional_tables(self) -> None:
        """Schema-tolerant: inventory still returns core keys on empty DB."""
        report = msm.build_inventory()
        self.assertEqual(int(report["memory_items_total"]), 0)
        self.assertEqual(int(report["sparks_total"]), 0)
        self.assertTrue(report["cold_start_retrieval"])

    def test_inventory_does_not_call_write_apis(self) -> None:
        with mock.patch.object(crowley, "save_memory_item") as save_mock:
            msm.build_inventory()
            save_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
