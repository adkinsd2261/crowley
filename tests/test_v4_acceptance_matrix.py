#!/usr/bin/env python3
"""V4 cognitive acceptance — matrix manifest and fixture validation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"
MATRIX_DOC = ROOT / "docs" / "V4_ACCEPTANCE_TEST_MATRIX.md"
GAP_DOC = ROOT / "docs" / "V4_COGNITIVE_SPEC_GAP_ANALYSIS.md"


class V4AcceptanceMatrixTests(unittest.TestCase):
    def test_manifest_lists_six_acceptance_tests(self) -> None:
        manifest = json.loads((FIXTURE_DIR / "matrix_manifest.json").read_text())
        self.assertEqual(manifest["version"], 1)
        tests = manifest["tests"]
        self.assertEqual(len(tests), 6)
        ids = sorted(int(t["id"]) for t in tests)
        self.assertEqual(ids, [1, 2, 3, 4, 5, 6])

    def test_all_manifest_fixtures_exist(self) -> None:
        manifest = json.loads((FIXTURE_DIR / "matrix_manifest.json").read_text())
        for entry in manifest["tests"]:
            path = FIXTURE_DIR / str(entry["fixture"])
            self.assertTrue(path.is_file(), f"missing fixture: {entry['fixture']}")
            payload = json.loads(path.read_text())
            self.assertEqual(int(payload["test_id"]), int(entry["id"]))

    def test_planning_docs_present(self) -> None:
        self.assertTrue(GAP_DOC.is_file())
        self.assertTrue(MATRIX_DOC.is_file())
        self.assertIn("Messy input handling", MATRIX_DOC.read_text())
        self.assertIn("Security validation", MATRIX_DOC.read_text())


if __name__ == "__main__":
    unittest.main()
