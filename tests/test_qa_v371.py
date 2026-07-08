#!/usr/bin/env python3
"""V3.7.1 QA patch tests — no live model calls."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class VersionTruthTests(unittest.TestCase):
    def test_version_100_claim_conflicts(self) -> None:
        self.assertTrue(
            crowley.grounding_has_version_truth_conflict(
                "I just released version 100"
            )
        )

    def test_matching_version_claim_ok(self) -> None:
        self.assertFalse(
            crowley.grounding_has_version_truth_conflict(
                f"Shipped V{crowley.CROWLEY_VERSION} context bridge"
            )
        )

    def test_casual_message_no_false_conflict(self) -> None:
        self.assertFalse(
            crowley.grounding_has_version_truth_conflict(
                "What should we build next?"
            )
        )


class ApplyStateVersionGuardTests(unittest.TestCase):
    def test_version_claim_blocks_phase_update(self) -> None:
        proposals = {
            "decisions": [],
            "open_loops": [],
            "state_update": {
                "phase": {"value": "V100", "confidence": 0.95},
                "what_changed": {"value": "Released version 100", "confidence": 0.95},
            },
        }
        result = crowley.apply_state_proposals(
            proposals,
            dry_run=True,
            grounding_message="I just released version 100",
        )
        self.assertIn("conflicts with source-of-truth files: phase", result["skipped"])
        self.assertNotIn("phase", result["state_fields_updated"])


class ProjectFilesContextTests(unittest.TestCase):
    def test_context_includes_authoritative_version(self) -> None:
        ctx = crowley.get_project_files_context()
        self.assertEqual(ctx["crowley_version"], crowley.CROWLEY_VERSION)
        self.assertEqual(ctx["release_label"], crowley.CROWLEY_RELEASE_LABEL)

    def test_versions_excerpt_when_file_exists(self) -> None:
        ctx = crowley.get_project_files_context()
        if crowley.VERSIONS_MD_PATH.is_file():
            self.assertIsNotNone(ctx["versions_md_excerpt"])
            self.assertIn(crowley.CROWLEY_VERSION, str(ctx["versions_md_excerpt"]))

    def test_prompt_section_mentions_known_release(self) -> None:
        section = crowley._format_project_files_prompt_section(
            crowley.get_project_files_context()
        )
        self.assertIn(crowley.CROWLEY_VERSION, section)
        self.assertIn("authoritative", section.lower())


class ContextBundleTests(IsolatedDbTestCase):
    def test_api_context_reports_actual_version(self) -> None:
        bundle = crowley.build_context_bundle(q="health", limit=1)
        health = bundle["system_health"]
        self.assertEqual(health["version"], crowley.CROWLEY_VERSION)
        project_files = bundle["project_files"]
        self.assertIsInstance(project_files, dict)
        self.assertEqual(
            project_files["crowley_version"], crowley.CROWLEY_VERSION
        )


class GreetingPromptTests(IsolatedDbTestCase):
    def test_mid_session_prompt_discourages_morning(self) -> None:
        original = crowley.list_chat_context_messages

        def fake_recent(*, limit: int = 8, exclude_message_id: int | None = None):
            _ = limit, exclude_message_id
            return [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "Hello."},
            ]

        crowley.list_chat_context_messages = fake_recent  # type: ignore[method-assign]
        try:
            note = crowley._greeting_behavior_prompt()
            self.assertIn("ongoing thread", note)
        finally:
            crowley.list_chat_context_messages = original  # type: ignore[method-assign]

    def test_build_prompt_includes_greeting_and_project_files(self) -> None:
        messages = crowley.build_prompt("hello", exclude_message_id=None)
        system = messages[0]["content"]
        self.assertIn("When a fact about the project matters", system)
        self.assertIn("Filesystem truth", system)
        self.assertIn(crowley.CROWLEY_VERSION, system)


if __name__ == "__main__":
    unittest.main()
