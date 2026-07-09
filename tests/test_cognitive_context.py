#!/usr/bin/env python3
"""V4 T13 — cognitive context orchestration tests."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import actions_tool_registry  # noqa: E402
import app as crowley_app  # noqa: E402
import context_orchestration  # noqa: E402
import context_resolution  # noqa: E402
import crowley  # noqa: E402
import spark_sanitize  # noqa: E402
import spark_graph  # noqa: E402
import spark_retrieval  # noqa: E402
import sparks  # noqa: E402
from actions_helpers import actions_headers, boot_actions_session  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ACTIONS_KEY = "test-actions-key"


def _retrieval_result(
    spark_id: int,
    *,
    lane: str = "work",
    score: float = 0.5,
) -> spark_retrieval.SparkRetrievalResult:
    return spark_retrieval.SparkRetrievalResult(
        spark_id=spark_id,
        content=f"Spark {spark_id} content",
        lane=lane,
        trust_state="active",
        confidence=0.7,
        score=score,
        score_breakdown={
            "semantic": 0.5,
            "confidence": 0.7,
            "recency": 1.0,
            "graph_reinforcement": 0.0,
        },
    )


class CognitiveContextTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._prior_key = os.environ.get("CROWLEY_ACTION_KEY")
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY

    def tearDown(self) -> None:
        try:
            if self._prior_key is None:
                os.environ.pop("CROWLEY_ACTION_KEY", None)
            else:
                os.environ["CROWLEY_ACTION_KEY"] = self._prior_key
        finally:
            super().tearDown()

    def test_build_context_splits_ranked_results_without_padding(self) -> None:
        conn = crowley.connect_db()
        try:
            ranked = [
                _retrieval_result(1, score=0.9),
                _retrieval_result(2, score=0.8),
            ]
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=ranked,
            ) as retrieve_mock:
                payload = context_orchestration.build_cognitive_context(
                    "query",
                    limit=3,
                    conn=conn,
                )

            retrieve_mock.assert_called_once()
            kwargs = retrieve_mock.call_args.kwargs
            self.assertEqual(
                kwargs["expand_hops"],
                spark_graph.SPARK_EXPANSION_HOPS_MEDIUM,
            )
            self.assertEqual(kwargs["limit"], 23)
            self.assertEqual(len(payload["core_sparks"]), 2)
            self.assertEqual(payload["supporting_sparks"], [])
            self.assertEqual(payload["confidence"], 0.85)
            self.assertEqual(payload["trace"]["core_count"], 2)
            self.assertEqual(payload["trace"]["supporting_count"], 0)
        finally:
            conn.close()

    def test_supporting_slice_comes_from_ranked_results(self) -> None:
        conn = crowley.connect_db()
        try:
            ranked = [
                _retrieval_result(1, score=0.9),
                _retrieval_result(2, score=0.8),
                _retrieval_result(3, score=0.7),
                _retrieval_result(4, score=0.6),
            ]
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=ranked,
            ):
                payload = context_orchestration.build_cognitive_context(
                    "query",
                    limit=2,
                    supporting_limit=2,
                    conn=conn,
                )

            self.assertEqual(
                [item["spark_id"] for item in payload["core_sparks"]],
                [1, 2],
            )
            self.assertEqual(
                [item["spark_id"] for item in payload["supporting_sparks"]],
                [3, 4],
            )
        finally:
            conn.close()

    def test_active_patterns_attached_by_int_intersection(self) -> None:
        conn = crowley.connect_db()
        try:
            now = crowley._now_iso()
            conn.execute(
                """
                INSERT INTO patterns (
                    content, lane, source_spark_ids_json, reasoning,
                    confidence, trust_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "active matching pattern",
                    "work",
                    json.dumps(["2", 99], separators=(",", ":")),
                    "reason",
                    0.8,
                    "active",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO patterns (
                    content, lane, source_spark_ids_json, reasoning,
                    confidence, trust_state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "candidate ignored pattern",
                    "work",
                    json.dumps([2], separators=(",", ":")),
                    "reason",
                    0.8,
                    "candidate",
                    now,
                    now,
                ),
            )
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[_retrieval_result(2, score=0.8)],
            ):
                payload = context_orchestration.build_cognitive_context(
                    "query",
                    limit=1,
                    conn=conn,
                )

            self.assertEqual(len(payload["patterns"]), 1)
            pattern_content = payload["patterns"][0]["content"]
            self.assertIn(spark_sanitize.MEMORY_DATA_BEGIN, pattern_content)
            self.assertIn("active matching pattern", pattern_content)
            self.assertEqual(payload["patterns"][0]["source_spark_ids"], [2, 99])
        finally:
            conn.close()

    def test_lane_filter_validated_and_trace_sorted(self) -> None:
        conn = crowley.connect_db()
        try:
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[],
            ) as retrieve_mock:
                payload = context_orchestration.build_cognitive_context(
                    "",
                    lanes="work,learning",
                    conn=conn,
                )

            kwargs = retrieve_mock.call_args.kwargs
            self.assertEqual(kwargs["lanes"], frozenset({"learning", "work"}))
            self.assertEqual(payload["trace"]["lanes_used"], ["learning", "work"])
            self.assertEqual(payload["confidence"], 0.0)
        finally:
            conn.close()

    def test_invalid_lane_rejected(self) -> None:
        with self.assertRaises(ValueError):
            context_orchestration.build_cognitive_context("query", lanes="badlane")

    def test_project_id_passed_to_retrieval(self) -> None:
        conn = crowley.connect_db()
        try:
            conn.execute(
                """
                INSERT INTO projects (name, slug, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("Other", "other", "inactive", "now", "now"),
            )
            project_row = conn.execute(
                "SELECT id FROM projects WHERE slug = 'other'"
            ).fetchone()
            assert project_row is not None
            project_id = int(project_row["id"])
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[],
            ) as retrieve_mock:
                context_orchestration.build_cognitive_context(
                    "query",
                    project="other",
                    conn=conn,
                )

            self.assertEqual(retrieve_mock.call_args.kwargs["project_id"], project_id)
        finally:
            conn.close()

    def test_default_active_project_id_passed_to_retrieval(self) -> None:
        conn = crowley.connect_db()
        try:
            active = conn.execute(
                "SELECT id FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            assert active is not None
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[],
            ) as retrieve_mock:
                context_orchestration.build_cognitive_context("query", conn=conn)

            self.assertEqual(
                retrieve_mock.call_args.kwargs["project_id"],
                int(active["id"]),
            )
        finally:
            conn.close()

    def test_api_returns_context_payload(self) -> None:
        client = TestClient(crowley_app.app)
        with mock.patch.object(
            context_orchestration,
            "build_cognitive_context",
            return_value={
                "core_sparks": [],
                "supporting_sparks": [],
                "patterns": [],
                "confidence": 0.0,
                "trace": {
                    "lanes_used": [],
                    "retrieved_count": 0,
                    "core_count": 0,
                    "supporting_count": 0,
                    "pattern_count": 0,
                    "expand_hops": 1,
                    "selection_reason": "test",
                    "score_basis": "test",
                },
            },
        ):
            res = client.get("/api/cognitive/context?q=test&limit=3")

        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertIn("core_sparks", data)
        self.assertIn("supporting_sparks", data)
        self.assertIn("patterns", data)
        self.assertIn("confidence", data)
        self.assertIn("trace", data)

    def test_api_dispatch_invariant_blocks_context(self) -> None:
        client = TestClient(crowley_app.app)
        broken = {"error": "invariant_violation", "ok": False}
        with mock.patch(
            "system_integrity.enforce_dispatch_invariants",
            return_value=(False, broken),
        ):
            res = client.get("/api/cognitive/context?q=test")

        self.assertEqual(res.status_code, 428)
        self.assertEqual(res.json()["error"], "invariant_violation")

    def test_actions_catalog_registers_cognitive_context(self) -> None:
        payload = actions_tool_registry.catalog_payload()
        tools = {tool["name"]: tool for tool in payload["tools"]}
        self.assertIn("cognitive.context", tools)
        self.assertEqual(tools["cognitive.context"]["kind"], "read")

    def test_actions_dispatch_returns_context_payload(self) -> None:
        headers = actions_headers(ACTIONS_KEY, session="cognitive-context-test")
        client = TestClient(crowley_app.app)
        boot_actions_session(client, headers)
        with mock.patch.object(
            context_orchestration,
            "build_cognitive_context",
            return_value={
                "core_sparks": [],
                "supporting_sparks": [],
                "patterns": [],
                "confidence": 0.0,
                "trace": {
                    "lanes_used": [],
                    "retrieved_count": 0,
                    "core_count": 0,
                    "supporting_count": 0,
                    "pattern_count": 0,
                    "expand_hops": 1,
                    "selection_reason": "test",
                    "score_basis": "test",
                },
            },
        ):
            res = client.post(
                "/api/actions/read",
                headers=headers,
                json={"tool": "cognitive.context", "args": {"q": "test", "limit": 3}},
            )

        self.assertEqual(res.status_code, 200, res.text)
        self.assertIn("core_sparks", res.json())

    def test_cold_start_uses_confirmed_candidates_without_active_sparks(self) -> None:
        conn = crowley.connect_db()
        try:
            project_id = crowley._active_project_id(conn)
            for index in range(8):
                sparks.insert_spark(
                    conn,
                    {
                        "content": f"Cold start confirmed candidate spark {index} for fallback exit.",
                        "lane": "work",
                        "why_keep": "Builds cold-start pool.",
                        "worth_reason": "Confirms fallback policy.",
                        "confidence": 0.8,
                        "certainty": "confirmed",
                        "sensitivity": "normal",
                    },
                    source_memory_item_id=1,
                    project_id=project_id,
                    trust_state="candidate",
                )
            conn.commit()
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[],
            ):
                payload = context_orchestration.build_cognitive_context(
                    "cold start query",
                    conn=conn,
                    project_id=project_id,
                )
        finally:
            conn.close()
        trace = payload["trace"]
        self.assertEqual(trace["active_spark_count"], 0)
        self.assertEqual(trace["cold_start_spark_count"], 8)
        self.assertFalse(trace["fallback_used"])
        self.assertNotIn("memory_fallback", payload)


if __name__ == "__main__":
    unittest.main()
