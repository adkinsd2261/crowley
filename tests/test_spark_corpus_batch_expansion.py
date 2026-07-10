"""V4.3.2 T2 — multi-batch spark expansion with dry-run gate."""

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
from db_helpers import IsolatedDbTestCase  # noqa: E402


def _seed(
    memory_type: str,
    content: str,
    *,
    source: str = "manual",
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


class SparkCorpusBatchExpansionTests(IsolatedDbTestCase):
    def test_apply_refuses_without_dry_run_or_reviewed(self) -> None:
        _seed(
            "lesson",
            "Batch expansion requires a dry-run artifact before apply mode.",
        )
        conn = crowley.connect_db()
        try:
            missing = Path(self._tmpdir.name) / "missing_dryrun.json"  # type: ignore[union-attr]
            with self.assertRaises(ValueError) as ctx:
                msm.apply_multi_batch(
                    conn,
                    limit=5,
                    max_batches=1,
                    reviewed=False,
                    artifact_path=missing,
                    promote_policy=False,
                )
            self.assertIn("apply refused", str(ctx.exception))
        finally:
            conn.close()

    def test_multi_batch_idempotent_and_capped(self) -> None:
        for i in range(8):
            _seed(
                "constraint",
                f"Durable constraint number {i} for multi-batch expansion coverage.",
                source="manual",
                importance=4,
            )
        conn = crowley.connect_db()
        try:
            with self.assertRaises(ValueError):
                msm.apply_multi_batch(
                    conn,
                    limit=msm.DEFAULT_APPLY_LIMIT_CAP + 1,
                    reviewed=True,
                    require_dry_run_gate=True,
                )

            first = msm.apply_multi_batch(
                conn,
                limit=3,
                max_batches=2,
                reviewed=True,
                promote_policy=False,
                batch_id_prefix="test-exp",
            )
            conn.commit()
            self.assertEqual(int(first["batches_run"]), 2)
            self.assertEqual(int(first["limit_per_batch"]), 3)
            self.assertFalse(first["memory_items_deleted"])
            self.assertFalse(first["memory_items_archived"])
            self.assertEqual(
                first["before"]["memory_items_total"],
                first["after"]["memory_items_total"],
            )
            self.assertGreaterEqual(int(first["totals"]["inserted"]), 1)
            batch_ids = [b["migration_batch_id"] for b in first["batches"]]
            self.assertEqual(len(set(batch_ids)), len(batch_ids))

            # Lineage preserved
            row = conn.execute(
                """
                SELECT source_memory_item_id, lineage_json FROM sparks
                WHERE source_memory_item_id IS NOT NULL LIMIT 1
                """
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertIn("test-exp", str(row["lineage_json"]))

            sparks_after_first = int(first["after"]["sparks_total"])
            second = msm.apply_multi_batch(
                conn,
                limit=3,
                max_batches=2,
                reviewed=True,
                promote_policy=False,
                batch_id_prefix="test-exp2",
            )
            conn.commit()
            # Idempotent: already-linked rows skipped; may insert remaining unlinked
            # but re-running same pool should not duplicate source links
            linked = conn.execute(
                """
                SELECT source_memory_item_id, COUNT(*) AS n FROM sparks
                WHERE source_memory_item_id IS NOT NULL
                GROUP BY source_memory_item_id
                HAVING n > 1
                """
            ).fetchall()
            self.assertEqual(linked, [])
            self.assertGreaterEqual(
                int(second["after"]["sparks_total"]), sparks_after_first
            )
        finally:
            conn.close()

    def test_dry_run_gate_accepts_fresh_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "memory_to_spark_dryrun.json"
            path.write_text(
                json.dumps(
                    {
                        "dry_run": True,
                        "generated_at": crowley._now_iso(),
                        "proposed_spark_count": 3,
                    }
                ),
                encoding="utf-8",
            )
            ok, reason = msm.check_dry_run_gate(artifact_path=path)
            self.assertTrue(ok)
            self.assertIn("dry_run_artifact_ok", reason)

    def test_cli_apply_requires_limit(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "extract_memory_items_to_sparks",
            ROOT / "scripts" / "extract_memory_items_to_sparks.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        old = sys.argv
        try:
            spec.loader.exec_module(mod)
            sys.argv = ["extract_memory_items_to_sparks.py", "--apply"]
            code = mod.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
