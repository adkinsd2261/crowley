#!/usr/bin/env python3
"""codex_sync.py --create-tickets validation tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import codex_sync as cs  # noqa: E402


class CodexSyncTicketValidationTests(unittest.TestCase):
    def test_valid_packet_has_no_errors(self) -> None:
        payload = json.loads((ROOT / "tickets" / "v3.9_builder.json").read_text(encoding="utf-8"))
        self.assertEqual(cs.validate_ticket_packet(payload), [])

    def test_missing_fields_report_all_errors(self) -> None:
        errors = cs.validate_ticket_packet({"tickets": [{}]})
        joined = "\n".join(errors)
        self.assertIn("missing title", joined)
        self.assertIn("missing description", joined)
        self.assertIn("missing assignee", joined)
        self.assertIn("missing priority", joined)
        self.assertIn("missing acceptance criteria", joined)
        self.assertGreaterEqual(len(errors), 5)

    def test_invalid_priority_reported(self) -> None:
        errors = cs.validate_ticket_packet(
            {
                "tickets": [
                    {
                        "title": "Probe",
                        "description": "Scope",
                        "assignee": "cursor",
                        "priority": 9,
                        "acceptance": ["ok"],
                    }
                ]
            }
        )
        self.assertTrue(any("invalid priority" in error for error in errors))

    @mock.patch.object(cs.asl, "create_ticket_api")
    @mock.patch.object(cs, "_run")
    def test_invalid_packet_creates_no_tickets(
        self, mock_run: mock.MagicMock, mock_create: mock.MagicMock
    ) -> None:
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"tickets": [{"title": "", "description": ""}]}, handle)
            path = handle.name
        try:
            code = cs.create_tickets_file(path)
        finally:
            Path(path).unlink()
        self.assertEqual(code, 2)
        mock_create.assert_not_called()

    @mock.patch.object(cs.asl, "create_ticket_api")
    @mock.patch.object(cs, "_run")
    def test_mixed_packet_fails_before_partial_creation(
        self, mock_run: mock.MagicMock, mock_create: mock.MagicMock
    ) -> None:
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(
                {
                    "tickets": [
                        {
                            "title": "Good ticket",
                            "description": "Scope",
                            "assignee": "cursor",
                            "priority": 1,
                            "acceptance": ["ok"],
                        },
                        {
                            "title": "Bad ticket",
                            "description": "Scope",
                            "assignee": "cursor",
                            "priority": 1,
                            "acceptance": [],
                        },
                    ]
                },
                handle,
            )
            path = handle.name
        try:
            code = cs.create_tickets_file(path)
        finally:
            Path(path).unlink()
        self.assertEqual(code, 2)
        mock_create.assert_not_called()

    @mock.patch.object(cs.asl, "create_ticket_api")
    @mock.patch.object(cs, "_run")
    def test_valid_packet_mints_tickets(
        self, mock_run: mock.MagicMock, mock_create: mock.MagicMock
    ) -> None:
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        mock_create.return_value = (42, None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(
                {
                    "tickets": [
                        {
                            "title": "Valid probe",
                            "description": "Do thing",
                            "assignee": "cursor",
                            "priority": 1,
                            "acceptance": ["tests pass"],
                        }
                    ]
                },
                handle,
            )
            path = handle.name
        try:
            code = cs.create_tickets_file(path)
        finally:
            Path(path).unlink()
        self.assertEqual(code, 0)
        mock_create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
