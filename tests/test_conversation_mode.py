#!/usr/bin/env python3
"""V3.9.5 conversation mode classifier tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class ConversationModeClassifierTests(unittest.TestCase):
    def test_status_phrasings(self) -> None:
        for message in (
            "quick status",
            "what changed?",
            "any update from Cursor?",
            "when did you last hear from cursor",
            "what tickets are open?",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_conversation_mode(message), "status")

    def test_planning_phrasings(self) -> None:
        for message in (
            "help me plan the next ticket slice",
            "what should we prioritize on the roadmap?",
            "how should we break this down for Codex?",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_conversation_mode(message), "planning")

    def test_exploration_phrasings(self) -> None:
        for message in (
            "thoughts on V4?",
            "what if we explored multi-project support first?",
            "walk me through each stage of your development",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_conversation_mode(message), "exploration")

    def test_debug_phrasings(self) -> None:
        for message in (
            "debug why the ticket detail flickers",
            "why is the dashboard behind after deploy?",
            "figure out why agent feed looks stale",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_conversation_mode(message), "debug")

    def test_diagnostics_phrasings(self) -> None:
        for message in (
            "run diagnostics",
            "good morning diagnostics",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_conversation_mode(message), "diagnostics")

    def test_bug_phrasings(self) -> None:
        for message in (
            "there is a bug in streaming completion",
            "the chat is broken after the last deploy",
            "ticket detail fails with a regression",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_conversation_mode(message), "bug")

    def test_casual_phrasings(self) -> None:
        for message in (
            "hey crowley hows it going",
            "tell me about quantum physics",
            "you're doing great",
        ):
            with self.subTest(message=message):
                self.assertEqual(crowley.classify_conversation_mode(message), "casual")

    def test_classifier_is_deterministic(self) -> None:
        message = "any update from Cursor?"
        first = crowley.classify_conversation_mode(message)
        second = crowley.classify_conversation_mode(message)
        self.assertEqual(first, second)
        self.assertEqual(first, "status")

    def test_all_modes_are_valid(self) -> None:
        samples = (
            "quick status",
            "plan the roadmap",
            "thoughts on V4",
            "debug the flicker",
            "run diagnostics",
            "found a bug",
            "hey there",
        )
        for message in samples:
            mode = crowley.classify_conversation_mode(message)
            self.assertIn(mode, crowley.CONVERSATION_MODES)


class ConversationModePromptTests(IsolatedDbTestCase):
    def test_build_prompt_includes_mode_and_answer_shape(self) -> None:
        system = crowley.build_prompt("quick status")[0]["content"]
        self.assertIn("Conversation mode (inferred): status", system)
        self.assertIn("Expected answer shape:", system)
        self.assertIn("Agent activity timestamps", system)

    def test_build_prompt_planning_mode(self) -> None:
        system = crowley.build_prompt("help me plan the next ticket slice")[0]["content"]
        self.assertIn("Conversation mode (inferred): planning", system)
        self.assertIn("tradeoffs", system)

    def test_build_prompt_bug_mode(self) -> None:
        system = crowley.build_prompt("there is a bug in streaming")[0]["content"]
        self.assertIn("Conversation mode (inferred): bug", system)


if __name__ == "__main__":
    unittest.main()
