#!/usr/bin/env python3
"""V3.7.2 knowledge files context patch tests — no live model calls."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


class KnowledgeFilesLoaderTests(unittest.TestCase):
    def test_baseline_files_always_loaded(self) -> None:
        entries = crowley.load_knowledge_files_context("ping")
        paths = [str(entry["path"]) for entry in entries]
        if (crowley.PROJECT_ROOT / "VERSIONS.md").is_file():
            self.assertIn("VERSIONS.md", paths)
        if (crowley.PROJECT_ROOT / "docs/PROJECT_STATE.md").is_file():
            self.assertIn("docs/PROJECT_STATE.md", paths)

    def test_version_history_includes_versions_md(self) -> None:
        entries = crowley.load_knowledge_files_context("version history")
        paths = [str(entry["path"]) for entry in entries]
        if (crowley.PROJECT_ROOT / "VERSIONS.md").is_file():
            self.assertIn("VERSIONS.md", paths)

    def test_entries_have_required_keys(self) -> None:
        entries = crowley.load_knowledge_files_context("architecture")
        for entry in entries:
            self.assertIn("path", entry)
            self.assertIn("excerpt", entry)
            self.assertIn("score", entry)
            self.assertIn("mtime", entry)
            self.assertLessEqual(len(str(entry["excerpt"])), 1803)

    def test_never_reads_forbidden_paths(self) -> None:
        entries = crowley.load_knowledge_files_context(".env crowley.db secrets")
        paths = [str(entry["path"]).lower() for entry in entries]
        self.assertFalse(any(".env" in path for path in paths))
        self.assertFalse(any("crowley.db" in path for path in paths))


class KnowledgePromptTests(unittest.TestCase):
    def test_build_prompt_includes_source_of_truth_section(self) -> None:
        crowley.setup_db()
        messages = crowley.build_prompt("what version are we on?")
        system = messages[0]["content"]
        self.assertIn("Filesystem truth", system)
        self.assertIn(crowley.CROWLEY_VERSION, system)

    def test_knowledge_before_db_state_before_memory(self) -> None:
        crowley.setup_db()
        messages = crowley.build_prompt("what version are we on?")
        system = messages[0]["content"]
        knowledge_idx = system.find("Filesystem truth")
        state_idx = system.find("Live DB state")
        memory_idx = system.find("Supporting memory")
        self.assertGreater(knowledge_idx, -1)
        self.assertGreater(state_idx, -1)
        self.assertGreater(memory_idx, -1)
        self.assertLess(knowledge_idx, state_idx)
        self.assertLess(state_idx, memory_idx)


class ContextBundleKnowledgeTests(unittest.TestCase):
    def test_api_context_includes_knowledge_files(self) -> None:
        crowley.setup_db()
        bundle = crowley.build_context_bundle(q="version history", limit=1)
        knowledge = bundle["knowledge_files"]
        self.assertIsInstance(knowledge, list)
        if (crowley.PROJECT_ROOT / "VERSIONS.md").is_file():
            paths = [str(item["path"]) for item in knowledge]
            self.assertIn("VERSIONS.md", paths)


class VersionGuardV372Tests(unittest.TestCase):
    def test_version_100_blocks_state_with_new_reason(self) -> None:
        proposals = {
            "decisions": [],
            "open_loops": [],
            "state_update": {
                "phase": {"value": "V100", "confidence": 0.95},
            },
        }
        result = crowley.apply_state_proposals(
            proposals,
            dry_run=True,
            grounding_message="I released version 100.",
        )
        self.assertIn(
            "conflicts with source-of-truth files: phase", result["skipped"]
        )
        self.assertNotIn("phase", result["state_fields_updated"])


if __name__ == "__main__":
    unittest.main()
