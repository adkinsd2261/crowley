#!/usr/bin/env python3
"""V3.9.5 response depth controller tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class ResponseDepthClassifierTests(unittest.TestCase):
    def test_status_and_update_asks_are_brief(self) -> None:
        for message in (
            "what changed?",
            "quick status",
            "any update from Cursor?",
            "catch me up",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_response_depth(message), "brief")

    def test_planning_and_exploration_are_deep(self) -> None:
        for message in (
            "help me plan the next ticket slice",
            "thoughts on V4?",
            "what if we explored multi-project support first?",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_response_depth(message), "deep")

    def test_default_depth_is_standard(self) -> None:
        for message in (
            "there is a bug in streaming completion",
            "debug why the ticket detail flickers",
            "hey crowley hows it going",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_response_depth(message), "standard")

    def test_check_ask_is_brief_even_when_mode_is_casual(self) -> None:
        self.assertEqual(
            crowley.classify_response_depth("can you check the bus port for me"),
            "brief",
        )

    def test_diagnostics_is_brief(self) -> None:
        self.assertEqual(crowley.classify_response_depth("run diagnostics"), "brief")

    def test_depth_values_are_limited(self) -> None:
        samples = (
            "what changed?",
            "thoughts on V4?",
            "hey there",
            "run diagnostics",
        )
        for message in samples:
            depth = crowley.classify_response_depth(message)
            self.assertIn(depth, crowley.RESPONSE_DEPTHS)

    def test_classifier_is_deterministic(self) -> None:
        message = "what changed?"
        self.assertEqual(
            crowley.classify_response_depth(message),
            crowley.classify_response_depth(message),
        )
        self.assertEqual(crowley.classify_response_depth(message), "brief")


class ResponseDepthPromptTests(IsolatedDbTestCase):
    def test_build_prompt_includes_depth_and_length_expectation(self) -> None:
        system = crowley.build_prompt("what changed?")[0]["content"]
        self.assertIn("Response depth (inferred): brief", system)
        self.assertIn("Answer length:", system)
        self.assertIn("No preamble", system)

    def test_build_prompt_planning_is_deep(self) -> None:
        system = crowley.build_prompt("thoughts on V4?")[0]["content"]
        self.assertIn("Response depth (inferred): deep", system)
        self.assertIn("Thorough when warranted", system)

    def test_build_prompt_casual_defaults_to_standard(self) -> None:
        system = crowley.build_prompt("hey crowley hows it going")[0]["content"]
        self.assertIn("Response depth (inferred): standard", system)


if __name__ == "__main__":
    unittest.main()
