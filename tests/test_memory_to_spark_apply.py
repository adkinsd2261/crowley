"""V4.3.1 T4 — small apply batch with idempotent dedup and trust policy."""

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
    source: str = "canon",
    importance: int = 5,
    pinned: bool = True,
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


class MemoryToSparkApplyTests(IsolatedDbTestCase):
    def test_apply_refuses_unbounded_limit(self) -> None:
        conn = crowley.connect_db()
        try:
            with self.assertRaises(ValueError):
                msm.apply_extract_batch(conn, limit=0)
            with self.assertRaises(ValueError):
                msm.apply_extract_batch(conn, limit=msm.DEFAULT_APPLY_LIMIT_CAP + 1)
        finally:
            conn.close()

    def test_apply_inserts_with_lineage_default_candidate(self) -> None:
        mid = _seed(
            "lesson",
            "Apply path preserves source_memory_item_id and migration lineage.",
            source="manual",
            pinned=False,
            importance=4,
        )
        conn = crowley.connect_db()
        try:
            report = msm.apply_extract_batch(
                conn, limit=10, promote_policy=False, batch_id="apply-1"
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT source_memory_item_id, trust_state, lineage_json
                FROM sparks WHERE source_memory_item_id = ?
                """,
                (mid,),
            ).fetchone()
        finally:
            conn.close()
        self.assertFalse(report["dry_run"])
        self.assertFalse(report["memory_items_mutated"])
        self.assertGreaterEqual(int(report["inserted"]), 1)
        self.assertIsNotNone(row)
        self.assertEqual(int(row["source_memory_item_id"]), mid)
        self.assertEqual(str(row["trust_state"]), "candidate")
        self.assertIn("apply-1", str(row["lineage_json"]))
        self.assertIn("inserted", report)
        self.assertIn("linked", report)
        self.assertIn("merged", report)
        self.assertIn("promoted", report)
        self.assertIn("rejected", report)
        self.assertIn("skipped", report)

    def test_apply_is_idempotent_and_does_not_delete_memory_items(self) -> None:
        mid = _seed(
            "decision",
            "Idempotent apply must not insert duplicate sparks for same memory.",
            source="canon",
            pinned=True,
        )
        conn = crowley.connect_db()
        try:
            first = msm.apply_extract_batch(conn, limit=5, batch_id="idem-1")
            conn.commit()
            second = msm.apply_extract_batch(conn, limit=5, batch_id="idem-2")
            conn.commit()
            spark_n = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM sparks WHERE source_memory_item_id = ?",
                    (mid,),
                ).fetchone()["n"]
            )
            mem = conn.execute(
                "SELECT status FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()
        finally:
            conn.close()
        self.assertGreaterEqual(int(first["inserted"]) + int(first.get("merged", 0)), 1)
        self.assertEqual(spark_n, 1)
        self.assertEqual(int(second.get("inserted", 0)), 0)
        self.assertGreaterEqual(int(second["skipped"]), 1)
        self.assertEqual(str(mem["status"]), "active")

    def test_only_policy_promotes_active_or_pinned(self) -> None:
        decision = _seed(
            "decision",
            "Canon pinned decisions may promote under documented migration policy.",
            source="canon",
            pinned=True,
        )
        lesson = _seed(
            "lesson",
            "Ordinary lessons stay candidate unless policy explicitly promotes.",
            source="manual",
            pinned=False,
            importance=4,
        )
        conn = crowley.connect_db()
        try:
            report = msm.apply_extract_batch(conn, limit=10, promote_policy=True)
            conn.commit()
            d_trust = conn.execute(
                "SELECT trust_state FROM sparks WHERE source_memory_item_id = ?",
                (decision,),
            ).fetchone()["trust_state"]
            l_trust = conn.execute(
                "SELECT trust_state FROM sparks WHERE source_memory_item_id = ?",
                (lesson,),
            ).fetchone()["trust_state"]
        finally:
            conn.close()
        self.assertIn(str(d_trust), {"active", "pinned"})
        self.assertEqual(str(l_trust), "candidate")
        self.assertGreaterEqual(int(report["promoted"]), 1)

    def test_cli_apply_requires_limit(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "extract_memory_items_to_sparks",
            ROOT / "scripts" / "extract_memory_items_to_sparks.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        # Simulate argv
        import sys as _sys

        old = _sys.argv
        try:
            _sys.argv = ["extract_memory_items_to_sparks.py", "--apply"]
            code = mod.main() if False else None  # load first
            spec.loader.exec_module(mod)
            _sys.argv = ["extract_memory_items_to_sparks.py", "--apply"]
            code = mod.main()
        finally:
            _sys.argv = old
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
