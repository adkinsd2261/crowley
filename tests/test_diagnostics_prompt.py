#!/usr/bin/env python3
"""V3.9.5 diagnostics prompt separation tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402


_CHAT_FLOURISH_MARKERS = (
    "project co-founder",
    "Honor the inferred Response depth",
    "Conversation mode (inferred):",
    "Response depth (inferred):",
    "Filesystem truth (primary readout",
    "Supporting memory (hybrid retrieval",
)


class DiagnosticsPromptTests(unittest.TestCase):
    def _diagnostics_system(self) -> str:
        context = crowley.gather_diagnostics_context()
        return crowley.format_diagnostics_prompt(context)[0]["content"]

    def test_diagnostics_prompt_is_factual_and_structured(self) -> None:
        system = self._diagnostics_system()
        self.assertIn("read-only operating-system diagnostic report", system)
        self.assertIn("Never invent missing information", system)
        self.assertIn("GROUND TRUTH CONTEXT:", system)
        self.assertIn("Current Project", system)
        self.assertIn("System Health", system)
        self.assertIn("No flourish", system)

    def test_diagnostics_excludes_chat_mode_depth_and_personality(self) -> None:
        system = self._diagnostics_system()
        chat = crowley._personality_prompt()
        for marker in _CHAT_FLOURISH_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, system)
        self.assertNotEqual(chat.strip(), system.strip())

    def test_diagnostics_uses_sql_facts_as_authority(self) -> None:
        context = crowley.gather_diagnostics_context()
        facts = crowley._serialize_diagnostics_facts(context)
        system = crowley.format_diagnostics_prompt(context)[0]["content"]
        self.assertIn(facts, system)
        self.assertIn("authoritative SQL/system output", system)

    def test_iter_diagnostics_tokens_does_not_use_chat_prompt(self) -> None:
        with mock.patch.object(crowley, "build_prompt", side_effect=AssertionError("chat prompt used")):
            with mock.patch.object(crowley, "iter_model_tokens", return_value=iter(())):
                list(crowley.iter_diagnostics_tokens())

    def test_format_diagnostics_prompt_shape(self) -> None:
        context = crowley.gather_diagnostics_context()
        messages = crowley.format_diagnostics_prompt(context)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(messages[1]["content"], "Produce the diagnostic briefing now.")


if __name__ == "__main__":
    unittest.main()
