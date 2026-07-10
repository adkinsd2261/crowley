#!/usr/bin/env python3
"""V4 acceptance test 2 — clean domain retrieval (V4.3 #362)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import context_orchestration  # noqa: E402
import crowley  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


class V4AcceptanceRetrievalTests(IsolatedDbTestCase):
    """Acceptance 2 for V4.3 Retrieval + Query lock."""

    def test_finance_query_excludes_health_lane(self) -> None:
        """Auto-lane finance query must not return health sparks; cap ≤15."""
        fixture = _load("retrieval_finance_query.json")
        forbidden = set(fixture["forbidden_lanes_in_results"])
        self.assertIn("health", forbidden)

        conn = crowley.connect_db()
        try:
            project_id = crowley._active_project_id(conn)
            for seed in fixture["seed_sparks"]:
                payload = {
                    "content": seed["content"],
                    "lane": seed["lane"],
                    "why_keep": "Acceptance fixture seed for clean retrieval.",
                    "worth_reason": "Supports V4.3 acceptance test 2.",
                    "confidence": seed.get("confidence", 0.8),
                    "spark_type": seed.get("spark_type", "fact"),
                    "certainty": seed.get("certainty", "confirmed"),
                    "sensitivity": "normal",
                }
                validated = sparks.validate_spark(payload)
                self.assertTrue(validated.ok, validated.errors)
                assert validated.spark is not None
                sparks.insert_spark(
                    conn,
                    validated.spark,
                    source_memory_item_id=1,
                    project_id=project_id,
                    trust_state=str(seed.get("trust_state") or "active"),
                )
            conn.commit()

            # Primary path: auto lane inference — no explicit lanes= / lane=.
            payload = context_orchestration.build_cognitive_context(
                str(fixture["finance_query"]),
                conn=conn,
                project_id=project_id,
                depth="medium",
            )
        finally:
            conn.close()

        trace = payload["trace"]
        self.assertEqual(trace["lane_source"], "inferred")
        self.assertEqual(trace["lanes_used"], ["money"])
        self.assertLessEqual(int(trace["retrieved_count"]), int(fixture["max_results"]))
        self.assertLessEqual(int(trace["retrieved_count"]), 15)
        self.assertIn("truncated_count", trace)
        self.assertIsInstance(trace["truncated_count"], int)
        self.assertGreaterEqual(int(trace["truncated_count"]), 0)

        returned = list(payload["core_sparks"]) + list(payload["supporting_sparks"])
        self.assertGreaterEqual(len(returned), 1)
        lanes = {str(item["lane"]) for item in returned}
        self.assertTrue(lanes.issubset({"money"}), lanes)
        self.assertNotIn("health", lanes)
        for item in returned:
            self.assertEqual(item["lane"], "money")
            self.assertNotIn(item["lane"], forbidden)


if __name__ == "__main__":
    unittest.main()
