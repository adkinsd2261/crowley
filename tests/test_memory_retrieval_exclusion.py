#!/usr/bin/env python3
"""Retrieval exclusion for non-retrieval cognitive receipts."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory_retrieval  # noqa: E402


class MemoryRetrievalExclusionTests(unittest.TestCase):
    def test_non_retrieval_flag_excludes(self) -> None:
        meta = json.dumps({"non_retrieval": True, "intent": "store"})
        self.assertTrue(memory_retrieval.memory_item_excluded_from_retrieval(meta))

    def test_temporary_intent_excludes(self) -> None:
        meta = json.dumps({"intent": "temporary"})
        self.assertTrue(memory_retrieval.memory_item_excluded_from_retrieval(meta))

    def test_ignore_intent_excludes(self) -> None:
        meta = json.dumps({"intent": "ignore"})
        self.assertTrue(memory_retrieval.memory_item_excluded_from_retrieval(meta))

    def test_store_intent_included(self) -> None:
        meta = json.dumps({"intent": "store", "cognitive_ingest": True})
        self.assertFalse(memory_retrieval.memory_item_excluded_from_retrieval(meta))


if __name__ == "__main__":
    unittest.main()
