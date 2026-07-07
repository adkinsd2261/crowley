#!/usr/bin/env python3
"""V4 T4 — spark extraction tests."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402
import spark_extraction  # noqa: E402
import sparks  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _spark(
    *,
    content: str = "Cache embeddings locally for deterministic offline retrieval tests.",
    lane: str = "work",
    why_keep: str = "Preserves offline retrieval behavior.",
    worth_reason: str = "Avoids flaky network dependencies in CI.",
    confidence: float = 0.8,
) -> dict[str, object]:
    return {
        "content": content,
        "lane": lane,
        "why_keep": why_keep,
        "worth_reason": worth_reason,
        "confidence": confidence,
    }


class SparkExtractionTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)

    def test_valid_json_array_parsed(self) -> None:
        payload = json.dumps([_spark()])
        parsed, errors = spark_extraction.parse_spark_extraction_response(payload)
        self.assertEqual(errors, [])
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(len(parsed), 1)

    def test_prose_wrapper_rejected(self) -> None:
        payload = 'Here are sparks:\n[{"content":"x","lane":"work"}]'
        parsed, errors = spark_extraction.parse_spark_extraction_response(payload)
        self.assertIsNone(parsed)
        self.assertTrue(errors)

    def test_retry_then_discard_on_second_failure(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch.object(
                crowley,
                "_call_openai",
                side_effect=["not json", "still not json"],
            ):
                result = spark_extraction.extract_sparks_from_text("source text")
        self.assertFalse(result.ok)
        self.assertEqual(result.sparks, [])
        self.assertEqual(result.attempts, 2)
        self.assertTrue(any("parse" in err for err in result.errors))

    def test_retry_succeeds_on_second_attempt(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        good = json.dumps([_spark()])
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch.object(
                crowley,
                "_call_openai",
                side_effect=[f"prefix prose\n{good}", good],
            ) as call_mock:
                result = spark_extraction.extract_sparks_from_text("source text")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(len(result.sparks), 1)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(call_mock.call_count, 2)
        retry_messages = call_mock.call_args_list[1].args[0]
        retry_user = retry_messages[1]["content"]
        self.assertIn("Parse errors:", retry_user)
        self.assertNotIn("source text", retry_user)

    def test_test_mode_uses_fixture_without_api(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        with mock.patch.object(crowley, "_call_openai") as call_mock:
            result = spark_extraction.extract_sparks_from_text("ignored in test mode")
        call_mock.assert_not_called()
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(len(result.sparks), 1)

    def test_no_partial_acceptance(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        payload = json.dumps(
            [
                _spark(),
                {
                    "content": "Missing worth reason field.",
                    "lane": "work",
                    "why_keep": "Should fail validation.",
                    "confidence": 0.7,
                },
            ]
        )
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch.object(crowley, "_call_openai", return_value=payload):
                result = spark_extraction.extract_sparks_from_text("source text")
        self.assertFalse(result.ok)
        self.assertEqual(result.sparks, [])
        self.assertTrue(any("validation" in err for err in result.errors))

    def test_empty_array_returns_ok(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch.object(crowley, "_call_openai", return_value="[]"):
                result = spark_extraction.extract_sparks_from_text("source text")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.sparks, [])

    def test_missing_openai_key_fails_cleanly(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        with mock.patch.object(crowley, "_has_openai_key", return_value=False):
            with mock.patch.object(crowley, "_call_openai") as call_mock:
                result = spark_extraction.extract_sparks_from_text("source text")
        call_mock.assert_not_called()
        self.assertFalse(result.ok)
        self.assertIn("OPENAI_API_KEY not set", result.errors)

    def test_excessive_sparks_rejected(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        too_many = json.dumps([_spark(content=f"Valid spark number {i}.") for i in range(6)])
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch.object(crowley, "_call_openai", return_value=too_many):
                result = spark_extraction.extract_sparks_from_text("source text")
        self.assertFalse(result.ok)
        self.assertEqual(result.sparks, [])
        self.assertEqual(result.attempts, 2)
        self.assertTrue(
            any("too many sparks" in err for err in result.errors),
            result.errors,
        )

    def test_batch_too_short_triggers_retry_then_discard(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        short_batch = json.dumps(
            [
                _spark(content="tiny", why_keep="a", worth_reason="b"),
                _spark(content="bits", lane="health", why_keep="c", worth_reason="d"),
            ]
        )
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch.object(crowley, "_call_openai", return_value=short_batch):
                result = spark_extraction.extract_sparks_from_text("source text")
        self.assertFalse(result.ok)
        self.assertTrue(
            any("batch content too short" in err for err in result.errors),
            result.errors,
        )

    def test_validate_spark_called_for_each_item(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        payload = json.dumps([_spark(), _spark(lane="health")])
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch.object(crowley, "_call_openai", return_value=payload):
                with mock.patch.object(
                    sparks,
                    "validate_spark",
                    wraps=sparks.validate_spark,
                ) as validate_mock:
                    result = spark_extraction.extract_sparks_from_text("source text")
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(validate_mock.call_count, 2)

    def test_module_has_no_patterns_table_access(self) -> None:
        source = (ROOT / "spark_extraction.py").read_text(encoding="utf-8")
        self.assertNotIn("patterns", source.lower())
        self.assertNotIn("connect_db", source)


if __name__ == "__main__":
    unittest.main()
