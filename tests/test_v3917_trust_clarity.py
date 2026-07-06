#!/usr/bin/env python3
"""V3.9.17 #115–#122 memory tier, conflict, clarity tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import conflict_engine  # noqa: E402
import crowley  # noqa: E402
import memory_tiers  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryTierTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_save_assigns_memory_tier(self) -> None:
        item_id = crowley.save_memory_item(
            "lesson",
            "Tier probe working memory.",
            source="cursor",
            project_id=self.project_id,
            agent_id="cursor",
        )
        assert item_id is not None
        api = crowley.get_memory_item_api_by_id(int(item_id))
        assert api is not None
        self.assertIn(api["memory_tier"], memory_tiers.MEMORY_TIERS)

    def test_promote_to_canonical(self) -> None:
        item_id = crowley.save_memory_item(
            "lesson",
            "Promotion probe.",
            source="cursor",
            project_id=self.project_id,
            agent_id="cursor",
        )
        assert item_id is not None
        result = memory_tiers.promote_memory_tier(int(item_id), agent_id="codex")
        self.assertTrue(result["promoted"])
        api = crowley.get_memory_item_api_by_id(int(item_id))
        assert api is not None
        self.assertEqual(api["memory_tier"], "canonical")

    def test_list_filter_by_memory_tier(self) -> None:
        crowley.save_memory_item(
            "lesson",
            "Canonical tier filter probe unique text.",
            source="codex",
            project_id=self.project_id,
            agent_id="codex",
            pinned=True,
        )
        rows, total = crowley.list_memory_items(memory_tier="canonical", limit=20)
        self.assertGreaterEqual(total, 1)
        for row in rows:
            api = crowley._memory_item_api_dict(row)
            self.assertEqual(api["memory_tier"], "canonical")

    def test_decay_and_gc(self) -> None:
        gc = crowley.run_memory_garbage_collection(dry_run=True)
        self.assertIn("duplicates_pruned", gc)
        decay = memory_tiers.run_memory_decay(project_id=self.project_id, dry_run=True)
        self.assertTrue(decay["ok"])


class ConflictEngineTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        conflict_engine.ensure_conflicts_table(self.conn)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_detect_and_resolve_conflict(self) -> None:
        id_a = crowley.save_memory_item(
            "constraint",
            "Conflict topic alpha decision path.",
            source="codex",
            project_id=self.project_id,
            agent_id="codex",
        )
        id_b = crowley.save_memory_item(
            "constraint",
            "Conflict topic alpha opposite decision path.",
            source="chatgpt",
            project_id=self.project_id,
            agent_id="chatgpt",
        )
        assert id_a and id_b
        conflicts = conflict_engine.detect_memory_conflicts(project_id=self.project_id)
        self.assertGreaterEqual(len(conflicts), 1)
        conflict_id = int(conflicts[0]["id"])
        result = conflict_engine.resolve_memory_conflict(conflict_id, agent_id="codex")
        self.assertTrue(result["ok"])
        self.assertIn("winner_memory_id", result["resolution"])


class ClarityApiTests(IsolatedDbTestCase):
    def test_session_diff_and_simple_mode(self) -> None:
        diff = crowley.build_session_diff()
        self.assertIn("counts", diff)
        self.assertIn("tickets", diff)
        simple = crowley.build_simple_mode_payload()
        self.assertEqual(simple["mode"], "simple")
        self.assertIn("hidden_surfaces", simple)

    def test_retrieval_explainability_api(self) -> None:
        crowley.save_memory_item(
            "lesson",
            "Explainability API probe for retrieval signals.",
            source="cursor",
            project_id=crowley._active_project_id(crowley.connect_db()),
            agent_id="cursor",
        )
        payload = crowley.build_retrieval_explainability_api(
            "Explainability API probe",
            limit=5,
        )
        self.assertIn("signals", payload)
        self.assertIn("retrieval_mode", payload)


if __name__ == "__main__":
    unittest.main()
