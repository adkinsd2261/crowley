#!/usr/bin/env python3
"""V4.3 T1 — cognitive query interpreter tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import cognitive_query  # noqa: E402
import context_orchestration  # noqa: E402
import crowley  # noqa: E402
import spark_retrieval  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class CognitiveQueryInterpreterTests(unittest.TestCase):
    def test_recall_mode(self) -> None:
        result = cognitive_query.interpret_query("What did I pay for car insurance?")
        self.assertEqual(result.mode, "recall")
        self.assertGreater(result.confidence, 0.4)

    def test_decision_mode(self) -> None:
        result = cognitive_query.interpret_query(
            "Should I accept the senior engineer offer?"
        )
        self.assertEqual(result.mode, "decision")

    def test_reflection_mode(self) -> None:
        result = cognitive_query.interpret_query(
            "Looking back, what patterns show up in my work stress?"
        )
        self.assertEqual(result.mode, "reflection")

    def test_planning_mode(self) -> None:
        result = cognitive_query.interpret_query(
            "Help me plan next steps for the V4.3 ladder this week"
        )
        self.assertEqual(result.mode, "planning")

    def test_empty_defaults_to_recall(self) -> None:
        result = cognitive_query.interpret_query("   ")
        self.assertEqual(result.mode, "recall")
        self.assertEqual(result.reason, "empty_query")
        self.assertLess(result.confidence, 0.5)

    def test_no_markers_defaults_to_recall(self) -> None:
        result = cognitive_query.interpret_query("Crowley cognitive memory status")
        self.assertEqual(result.mode, "recall")
        self.assertEqual(result.reason, "default_recall")

    def test_tie_break_defaults_to_recall(self) -> None:
        # Equal marker counts across modes → recall tie-break.
        result = cognitive_query.interpret_query(
            "should i decide and also plan next steps while looking back"
        )
        self.assertEqual(result.mode, "recall")
        self.assertEqual(result.reason, "tie_break_recall")
        self.assertIn("tied_modes", result.hints)
        tied = result.hints["tied_modes"]
        assert isinstance(tied, list)
        self.assertGreaterEqual(len(tied), 2)

    def test_inferred_lanes_multi(self) -> None:
        result = cognitive_query.interpret_query(
            "finance and health costs for this month"
        )
        self.assertEqual(result.inferred_lanes, ["health", "money"])

    def test_insurance_keyword_infers_money(self) -> None:
        result = cognitive_query.interpret_query(
            "What am I paying for insurance and subscriptions?"
        )
        self.assertEqual(result.inferred_lanes, ["money"])

    def test_explicit_query_mode_override(self) -> None:
        result = cognitive_query.interpret_query(
            "What did I pay?",
            explicit_mode="planning",
        )
        self.assertEqual(result.mode, "planning")
        self.assertEqual(result.reason, "explicit_query_mode")
        self.assertEqual(result.confidence, 1.0)

    def test_invalid_explicit_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            cognitive_query.interpret_query("q", explicit_mode="precise")

    def test_test_mode_never_calls_model_providers(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        try:
            with mock.patch.object(crowley, "_call_openai") as openai_mock:
                cognitive_query.interpret_query(
                    "Should I choose the money lane plan next steps?"
                )
            openai_mock.assert_not_called()
        finally:
            os.environ.pop("CROWLEY_TEST_MODE", None)

    def test_module_has_no_provider_imports(self) -> None:
        source = (ROOT / "cognitive_query.py").read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertNotIn("openai", lowered)
        self.assertNotIn("ollama", lowered)
        self.assertNotIn("anthropic", lowered)


class CognitiveQueryContextWireTests(IsolatedDbTestCase):
    def test_trace_records_query_mode(self) -> None:
        conn = crowley.connect_db()
        try:
            ranked = [
                spark_retrieval.SparkRetrievalResult(
                    spark_id=1,
                    content="Spark content",
                    lane="work",
                    trust_state="active",
                    confidence=0.7,
                    score=0.9,
                    score_breakdown={
                        "semantic": 0.5,
                        "confidence": 0.7,
                        "recency": 1.0,
                        "graph_reinforcement": 0.0,
                    },
                )
            ]
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=ranked,
            ) as retrieve_mock:
                payload = context_orchestration.build_cognitive_context(
                    "Should I choose option A or option B?",
                    conn=conn,
                    debug=True,
                )
        finally:
            conn.close()

        # Orchestration owns interpretation and passes mode into retrieval scoring.
        retrieve_mock.assert_called_once()
        call_kwargs = retrieve_mock.call_args.kwargs
        self.assertEqual(call_kwargs.get("query_mode"), "decision")
        self.assertIsNone(call_kwargs.get("lanes"))

        trace = payload["trace"]
        self.assertEqual(trace["query_mode"], "decision")
        self.assertEqual(trace["lane_source"], "none")
        self.assertEqual(trace["score_profile"], "decision")
        self.assertIn("query_mode_confidence", trace)
        self.assertIn("query_mode_reason", trace)
        self.assertIn("decision profile:", trace["score_basis"])
        debug = payload["debug"]
        self.assertIn("query_hints", debug)
        self.assertIn("inferred_lanes", debug)
        self.assertEqual(trace["lanes_used"], [])
        self.assertEqual(debug["inferred_lanes"], [])

    def test_inferred_lanes_applied_as_retrieval_filter(self) -> None:
        conn = crowley.connect_db()
        try:
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[],
            ) as retrieve_mock:
                payload = context_orchestration.build_cognitive_context(
                    "What am I paying for insurance and subscriptions?",
                    conn=conn,
                    debug=True,
                )
        finally:
            conn.close()

        call_kwargs = retrieve_mock.call_args.kwargs
        self.assertEqual(call_kwargs.get("lanes"), frozenset({"money"}))
        self.assertEqual(call_kwargs.get("query_mode"), "recall")
        trace = payload["trace"]
        self.assertEqual(trace["lanes_used"], ["money"])
        self.assertEqual(trace["lane_source"], "inferred")
        self.assertEqual(trace["score_profile"], "recall")
        self.assertEqual(payload["debug"]["inferred_lanes"], ["money"])

    def test_explicit_lane_overrides_inference(self) -> None:
        conn = crowley.connect_db()
        try:
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[],
            ) as retrieve_mock:
                payload = context_orchestration.build_cognitive_context(
                    "What am I paying for insurance and subscriptions?",
                    lanes="health",
                    conn=conn,
                    debug=True,
                )
        finally:
            conn.close()

        call_kwargs = retrieve_mock.call_args.kwargs
        self.assertEqual(call_kwargs.get("lanes"), frozenset({"health"}))
        trace = payload["trace"]
        self.assertEqual(trace["lanes_used"], ["health"])
        self.assertEqual(trace["lane_source"], "explicit")
        # Inference still recorded in debug, but not applied.
        self.assertEqual(payload["debug"]["inferred_lanes"], ["money"])

    def test_explicit_query_mode_on_context(self) -> None:
        conn = crowley.connect_db()
        try:
            with mock.patch.object(
                context_orchestration.spark_retrieval,
                "retrieve_sparks",
                return_value=[],
            ):
                payload = context_orchestration.build_cognitive_context(
                    "What did I pay?",
                    conn=conn,
                    query_mode="reflection",
                    debug=True,
                )
        finally:
            conn.close()
        self.assertEqual(payload["trace"]["query_mode"], "reflection")
        self.assertEqual(payload["trace"]["query_mode_reason"], "explicit_query_mode")


if __name__ == "__main__":
    unittest.main()
