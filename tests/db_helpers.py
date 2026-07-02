"""Shared test database isolation helpers.

Convention: any unittest that writes to Crowley tables should inherit
``IsolatedDbTestCase`` so regression runs do not pollute ``crowley.db``.
"""

from __future__ import annotations

import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import crowley


@contextmanager
def isolated_db() -> Iterator[Path]:
    """Temporary Crowley database for one-off checks."""
    tmpdir = tempfile.TemporaryDirectory(prefix="crowley-test-")
    try:
        crowley.set_db_path(Path(tmpdir.name) / "test.db")
        crowley.setup_db()
        yield crowley.get_db_path()
    finally:
        crowley.reset_db_path()
        tmpdir.cleanup()


class IsolatedDbTestCase(unittest.TestCase):
    """Use a temporary SQLite database for each test method."""

    _tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(prefix="crowley-test-")
        crowley.set_db_path(Path(self._tmpdir.name) / "test.db")
        crowley.setup_db()

    def tearDown(self) -> None:
        try:
            crowley.reset_db_path()
        finally:
            if self._tmpdir is not None:
                self._tmpdir.cleanup()
                self._tmpdir = None
        super().tearDown()
