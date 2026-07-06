#!/usr/bin/env python3
"""V3.9.19 memory quality tests (#153–#157)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_behavior  # noqa: E402
import crowley  # noqa: E402
import memory_quality  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryQualityUnitTests(unittest.TestCase):
    def test_token_similarity(self) -> None:
        self.assertGreater(
            memory_quality.token_similarity(
                "Never commit secrets to the repository",
                "Do not commit secrets to git repository",
            ),
            0.4,
        )

    def test_assess_retrieval_strength_weak_empty(self) -> None:
        self.assertEqual(memory_quality.assess_retrieval_strength("query", []), "weak")

    def test_assess_retrieval_strength_strong(self) -> None:
        strength = memory_quality.assess_retrieval_strength(
            "query",
            [{"score": 0.7, "score_breakdown": {"semantic": 0.5}}],
        )
        self.assertEqual(strength, "strong")

    def test_agent_sync_checklist_after_completion(self) -> None:
        agent_behavior.reset_request_cycle("sync-check")
        agent_behavior.apply_agent_sync_completion("sync-check")
        result = agent_behavior.validate_retrieval_state("sync-check")
        checklist = result.get("checklist", [])
        self.assertTrue(all(item.get("passed") for item in checklist[:2]))

    def test_validation_ready_after_sync_and_retrieval(self) -> None:
        agent_behavior.reset_request_cycle("sync-ret")
        agent_behavior.apply_agent_sync_completion("sync-ret")
        agent_behavior.record_tool_call("sync-ret", "ticket.list", reason="tickets")
        result = agent_behavior.validate_retrieval_state("sync-ret", intent="tickets")
        self.assertTrue(result.get("ready"))


class MemoryQualityIntegrationTests(IsolatedDbTestCase):
    def test_constraint_dedup_on_ingest(self) -> None:
        conn = crowley.connect_db()
        project_id = crowley._active_project_id(conn)
        assert project_id is not None
        text = "Never push secrets or credentials into git commits"
        first = crowley.save_memory_item(
            "constraint",
            text,
            source="manual",
            project_id=project_id,
        )
        assert first is not None
        second = crowley.save_memory_item(
            "constraint",
            "Do not push secrets or credentials into git commits ever",
            source="manual",
            project_id=project_id,
        )
        self.assertEqual(int(first), int(second))

    def test_summary_semantic_dedup(self) -> None:
        conn = crowley.connect_db()
        project_id = crowley._active_project_id(conn)
        assert project_id is not None
        first = crowley.save_memory_item(
            "summary",
            "Shipped memory quality patch with dedup and retrieval validation",
            source="cursor",
            project_id=project_id,
        )
        assert first is not None
        second = crowley.save_memory_item(
            "summary",
            "Shipped memory quality patch with dedup and retrieval validation today",
            source="cursor",
            project_id=project_id,
        )
        self.assertEqual(int(first), int(second))

    def test_retrieve_payload_includes_strength(self) -> None:
        crowley.save_memory_item(
            "decision",
            "Crowley uses SQLite for local-first memory storage",
            source="manual",
            importance=4,
        )
        payload = crowley.retrieve_memories_api(q="SQLite memory storage", limit=5)
        self.assertIn("retrieval_strength", payload)
        self.assertIn("retrieval_validation", payload)

    def test_lifecycle_cleanup_dry_run(self) -> None:
        report = memory_quality.run_minimal_lifecycle_cleanup(dry_run=True)
        self.assertTrue(report.get("dry_run"))
        self.assertIn("duplicates", report)
        self.assertIn("stale", report)


if __name__ == "__main__":
    unittest.main()
