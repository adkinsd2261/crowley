#!/usr/bin/env python3
"""V4.2 T3 — cognitive document chunking tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cognitive_chunking  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class CognitiveChunkingTests(unittest.TestCase):
    def test_short_text_single_chunk(self) -> None:
        text = "Short cognitive ingest stays on the single-chunk path."
        result = cognitive_chunking.chunk_cognitive_text(text)
        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.chunks[0].break_reason, "single")
        self.assertFalse(result.truncated)

    def test_long_text_splits_on_headings(self) -> None:
        text = (FIXTURES / "cognitive_chunking_mixed_topic.txt").read_text(encoding="utf-8")
        self.assertGreater(len(text), cognitive_chunking.CHUNK_THRESHOLD_CHARS)
        result = cognitive_chunking.chunk_cognitive_text(text)
        self.assertGreaterEqual(len(result.chunks), 2)
        reasons = {chunk.break_reason for chunk in result.chunks}
        self.assertTrue(reasons & {"heading", "paragraph"})

    def test_long_single_topic_splits_by_size(self) -> None:
        text = (FIXTURES / "cognitive_chunking_long_single_topic.txt").read_text(encoding="utf-8")
        result = cognitive_chunking.chunk_cognitive_text(text)
        self.assertGreater(len(result.chunks), 1)
        self.assertTrue(any(chunk.break_reason == "size_limit" for chunk in result.chunks))

    def test_chunk_cap_truncates(self) -> None:
        sections = "\n\n".join(f"## Section {index}\n\n{'detail ' * 400}" for index in range(12))
        result = cognitive_chunking.chunk_cognitive_text(sections)
        self.assertEqual(len(result.chunks), cognitive_chunking.MAX_CHUNKS)
        self.assertTrue(result.truncated)
        self.assertGreater(result.omitted_chunk_count, 0)


if __name__ == "__main__":
    unittest.main()
