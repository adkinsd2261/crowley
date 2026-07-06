#!/usr/bin/env python3
"""V3.9.17+ #131 — handoff → ticket persistence bridge tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import handoff_ticket_bridge  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402

HANDOFF_BODY = """\
# Crowley Handoff

Source: cursor
Type: builder_handoff

## Summary

- Shipped handoff ticket bridge probe

## Context Basis

- ticket #131

## Build Complete

- files_changed: handoff_ticket_bridge.py

## QA Results

- Backend: 424/424 OK

## Files Changed

- handoff_ticket_bridge.py
"""


class HandoffTicketBridgeTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_persist_handoff_creates_done_ticket(self) -> None:
        result = crowley.ingest_handoff("cursor", "builder_handoff", HANDOFF_BODY)
        self.assertEqual(result["status"], "ok")
        mem_id = int(result["memory_item_id"])
        bridge = result.get("handoff_ticket")
        assert isinstance(bridge, dict)
        self.assertTrue(bridge.get("created"))
        ticket = bridge["ticket"]
        assert isinstance(ticket, dict)
        self.assertEqual(ticket["status"], "done")
        self.assertEqual(int(ticket["linked_memory_id"]), mem_id)
        self.assertIn("bridge probe", str(ticket["title"]).lower())

    def test_idempotent_no_duplicate_ticket(self) -> None:
        mem_id = crowley.save_memory_item(
            "project_update",
            HANDOFF_BODY,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        first = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(mem_id),
            HANDOFF_BODY,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        second = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(mem_id),
            HANDOFF_BODY,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        self.assertTrue(first.get("created"))
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(int(first["ticket"]["id"]), int(second["ticket"]["id"]))

    def test_parse_handoff_fields(self) -> None:
        fields = handoff_ticket_bridge.parse_handoff_ticket_fields(HANDOFF_BODY)
        self.assertIn("bridge probe", fields["title"].lower())
        self.assertIn("handoff_ticket_bridge.py", fields["files_section"])
        self.assertIn("424/424", fields["qa_summary"])


if __name__ == "__main__":
    unittest.main()
