#!/usr/bin/env python3
"""V3.9.5 model behavior regression fixtures — no live model calls."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "v3_9_5_model_behavior.json"


def load_model_behavior_fixtures() -> dict:
    return json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))


class ModelBehaviorFixtureTests(unittest.TestCase):
    fixtures = load_model_behavior_fixtures()

    def test_chat_fixture_mode_selection(self) -> None:
        for case in self.fixtures["chat_prompts"]:
            with self.subTest(message=case["message"]):
                self.assertEqual(
                    crowley.classify_conversation_mode(case["message"]),
                    case["mode"],
                )

    def test_chat_fixture_depth_selection(self) -> None:
        for case in self.fixtures["chat_prompts"]:
            with self.subTest(message=case["message"]):
                mode = crowley.classify_conversation_mode(case["message"])
                self.assertEqual(
                    crowley.classify_response_depth(case["message"], mode=mode),
                    case["depth"],
                )

    def test_diagnostics_fixture_mode_and_depth(self) -> None:
        for case in self.fixtures["diagnostics"]:
            with self.subTest(message=case["message"]):
                self.assertEqual(
                    crowley.classify_conversation_mode(case["message"]),
                    case["mode"],
                )
                self.assertEqual(
                    crowley.classify_response_depth(case["message"]),
                    case["depth"],
                )


class ModelBehaviorPromptFixtureTests(IsolatedDbTestCase):
    fixtures = load_model_behavior_fixtures()

    def test_chat_fixture_prompt_assembly(self) -> None:
        for case in self.fixtures["chat_prompts"]:
            with self.subTest(message=case["message"]):
                system = crowley.build_prompt(case["message"])[0]["content"]
                for fragment in case["prompt_contains"]:
                    self.assertIn(fragment, system)

    def test_diagnostics_fixture_separation(self) -> None:
        for case in self.fixtures["diagnostics"]:
            with self.subTest(message=case["message"]):
                context = crowley.gather_diagnostics_context()
                diagnostics = crowley.format_diagnostics_prompt(context)[0]["content"]
                for fragment in case["diagnostics_contains"]:
                    self.assertIn(fragment, diagnostics)
                for fragment in case["diagnostics_excludes"]:
                    self.assertNotIn(fragment, diagnostics)

    def test_diagnostics_path_never_calls_live_model_or_chat_prompt(self) -> None:
        with mock.patch.object(crowley, "build_prompt", side_effect=AssertionError("chat prompt used")):
            with mock.patch.object(crowley, "iter_model_tokens", return_value=iter(())):
                list(crowley.iter_diagnostics_tokens())


if __name__ == "__main__":
    unittest.main()
