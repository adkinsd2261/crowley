#!/usr/bin/env python3
"""V3.9.18 #131 patch — handoff → ticket persistence bridge tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import handoff_ticket_bridge  # noqa: E402
import tickets  # noqa: E402
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

- Backend: 430/430 OK

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

    def test_extract_work_ticket_id(self) -> None:
        self.assertEqual(
            handoff_ticket_bridge.extract_work_ticket_id(HANDOFF_BODY),
            131,
        )
        self.assertEqual(
            handoff_ticket_bridge.extract_work_ticket_id(
                "summary only",
                metadata={"closed_work_ticket_id": 42},
            ),
            42,
        )

    def test_work_ticket_enriched_not_duplicated(self) -> None:
        work_id = int(
            crowley.create_ticket(
                "Persist handoffs as tickets (handoff → ticket bridge)",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        mem_id = crowley.save_memory_item(
            "project_update",
            HANDOFF_BODY,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        bridge = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(mem_id),
            HANDOFF_BODY,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
            closed_work_ticket_id=work_id,
        )
        self.assertEqual(bridge.get("mode"), "work_ticket_enriched")
        self.assertFalse(bridge.get("created"))
        linked = handoff_ticket_bridge.list_tickets_for_handoff_memory(int(mem_id))
        self.assertEqual(len(linked), 1)
        self.assertEqual(int(linked[0]["id"]), work_id)
        self.assertEqual(int(linked[0]["linked_memory_id"]), int(mem_id))

    def test_ingest_enriches_work_ticket_from_context_basis(self) -> None:
        work_id = int(
            crowley.create_ticket(
                "Work ticket for ingest enrich probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        body = HANDOFF_BODY.replace("ticket #131", f"ticket #{work_id}")
        result = crowley.ingest_handoff("cursor", "builder_handoff", body)
        self.assertEqual(result["status"], "ok")
        mem_id = int(result["memory_item_id"])
        bridge = result.get("handoff_ticket")
        assert isinstance(bridge, dict)
        self.assertEqual(bridge.get("mode"), "work_ticket_enriched")
        linked = handoff_ticket_bridge.list_tickets_for_handoff_memory(mem_id)
        self.assertEqual(len(linked), 1)
        self.assertEqual(int(linked[0]["id"]), work_id)

    def test_archival_created_when_no_work_ticket(self) -> None:
        body = HANDOFF_BODY.replace("## Context Basis\n\n- ticket #131\n\n", "")
        mem_id = crowley.save_memory_item(
            "project_update",
            body,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        bridge = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        self.assertTrue(bridge.get("created"))
        self.assertEqual(bridge.get("mode"), "archival_created")

    def test_idempotent_when_already_linked(self) -> None:
        work_id = int(
            crowley.create_ticket(
                "Idempotent work ticket probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        body = HANDOFF_BODY.replace("ticket #131", f"ticket #{work_id}")
        mem_id = crowley.save_memory_item(
            "project_update",
            body,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        first = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
            closed_work_ticket_id=work_id,
        )
        second = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
            closed_work_ticket_id=work_id,
        )
        self.assertEqual(first.get("mode"), "work_ticket_enriched")
        self.assertTrue(second.get("idempotent"))


if __name__ == "__main__":
    unittest.main()
