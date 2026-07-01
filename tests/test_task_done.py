#!/usr/bin/env python3
"""Tests for /task done CLI and API."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


class TaskDoneTests(unittest.TestCase):
    def test_complete_task(self) -> None:
        crowley.setup_db()
        task_id = crowley.save_task("QA task done probe", project="crowley")
        self.assertTrue(crowley.complete_task(task_id))
        task = crowley.get_task_by_id(task_id)
        assert task is not None
        self.assertEqual(str(task["status"]), "done")

    def test_complete_task_idempotent(self) -> None:
        crowley.setup_db()
        task_id = crowley.save_task("QA idempotent probe", project="crowley")
        crowley.complete_task(task_id)
        self.assertFalse(crowley.complete_task(task_id))

    def test_get_task_by_id_missing(self) -> None:
        crowley.setup_db()
        self.assertIsNone(crowley.get_task_by_id(999999))


if __name__ == "__main__":
    unittest.main()
