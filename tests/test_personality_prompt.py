#!/usr/bin/env python3
"""V3.9.5 personality prompt tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class PersonalityPromptTests(unittest.TestCase):
    def test_keeps_running_system_identity(self) -> None:
        prompt = crowley._personality_prompt()
        self.assertIn("running system", prompt)
        self.assertIn("not an assistant talking about Crowley", prompt)

    def test_co_founder_voice(self) -> None:
        prompt = crowley._personality_prompt()
        self.assertIn("project co-founder", prompt)
        self.assertIn("willing to have a point of view", prompt)

    def test_honors_depth_and_mode_controller(self) -> None:
        prompt = crowley._personality_prompt()
        self.assertIn("Honor the inferred Response depth", prompt)
        self.assertIn("when depth is brief, stay tight", prompt)

    def test_drops_theatrical_flourish(self) -> None:
        prompt = crowley._personality_prompt()
        self.assertNotIn("Jarvis-shaped", prompt)
        self.assertNotIn("Charisma when it fits", prompt)
        self.assertNotIn("Don't rush to the shortest reply", prompt)


class PersonalityPromptAssemblyTests(IsolatedDbTestCase):
    def test_build_prompt_includes_trimmed_personality(self) -> None:
        system = crowley.build_prompt("hey crowley")[0]["content"]
        self.assertIn("project co-founder", system)
        self.assertNotIn("Jarvis-shaped", system)


if __name__ == "__main__":
    unittest.main()
