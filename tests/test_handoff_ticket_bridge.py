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

    def test_ingest_replay_does_not_create_duplicate_archival(self) -> None:
        body = HANDOFF_BODY.replace("## Context Basis\n\n- ticket #131\n\n", "")
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
        )
        second = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        self.assertTrue(first.get("created"))
        self.assertFalse(second.get("created"))
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(second.get("mode"), "upsert_linked")
        linked = handoff_ticket_bridge.list_tickets_for_handoff_memory(int(mem_id))
        self.assertEqual(len(linked), 1)

    def test_reconcile_cancels_duplicate_linked_tickets(self) -> None:
        mem_id = crowley.save_memory_item(
            "project_update",
            HANDOFF_BODY,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        first_id = int(
            crowley.create_ticket(
                "Duplicate A",
                assignee="cursor",
                project_id=self.project_id,
                linked_memory_id=int(mem_id),
            )["ticket"]["id"]
        )
        second_id = int(
            crowley.create_ticket(
                "Duplicate B",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        tickets.update_ticket(second_id, actor="cursor", linked_memory_id=int(mem_id))
        report = handoff_ticket_bridge.reconcile_handoff_ticket_parity(
            limit=50,
            dry_run=False,
        )
        self.assertGreaterEqual(int(report.get("cancelled_duplicates", 0)), 1)
        linked = handoff_ticket_bridge.list_tickets_for_handoff_memory(int(mem_id))
        self.assertEqual(len(linked), 1)
        remaining_id = int(linked[0]["id"])
        self.assertIn(remaining_id, {first_id, second_id})
        parity = handoff_ticket_bridge.verify_handoff_ticket_parity(limit=50)
        self.assertTrue(parity.get("parity_ok"))

    def test_create_ticket_rejects_duplicate_linked_memory(self) -> None:
        mem_id = crowley.save_memory_item(
            "project_update",
            "handoff probe",
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        crowley.create_ticket(
            "First link",
            assignee="cursor",
            project_id=self.project_id,
            linked_memory_id=int(mem_id),
        )
        with self.assertRaises(ValueError):
            tickets.create_ticket(
                "Second link",
                assignee="cursor",
                project_id=self.project_id,
                linked_memory_id=int(mem_id),
            )

    def test_follow_up_handoff_does_not_steal_work_ticket_link(self) -> None:
        work_id = int(
            crowley.create_ticket(
                "Primary work ticket",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        first_body = HANDOFF_BODY.replace("ticket #131", f"ticket #{work_id}")
        first_mem = crowley.save_memory_item(
            "project_update",
            first_body,
            source="cursor",
            project_id=self.project_id,
        )
        assert first_mem is not None
        first = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(first_mem),
            first_body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
            closed_work_ticket_id=work_id,
        )
        self.assertEqual(first.get("linkage_decision"), "work_ticket_enriched")

        second_body = (
            first_body.replace("probe", "follow-up probe")
            + "\n\n## Follow-up\n\n- Additional doc-lock handoff for the same work ticket.\n"
        )
        second_mem = crowley.save_memory_item(
            "project_update",
            second_body,
            source="cursor",
            project_id=self.project_id,
        )
        assert second_mem is not None
        second = handoff_ticket_bridge.persist_handoff_as_ticket(
            int(second_mem),
            second_body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
            closed_work_ticket_id=work_id,
        )
        self.assertEqual(second.get("linkage_decision"), "follow_up_archival")
        self.assertTrue(second.get("created"))

        work_row = tickets.get_ticket_by_id(work_id)
        assert work_row is not None
        self.assertEqual(int(work_row["linked_memory_id"]), int(first_mem))
        self.assertEqual(len(handoff_ticket_bridge.list_tickets_for_handoff_memory(int(second_mem))), 1)

    def test_extract_bare_hash_ticket_reference(self) -> None:
        body = "Shipped validation wiring (#166) without Context Basis ticket line."
        self.assertEqual(
            handoff_ticket_bridge.extract_referenced_ticket_ids(body),
            [166],
        )

    def test_ensure_handoff_ticket_link_idempotent(self) -> None:
        body = HANDOFF_BODY.replace("## Context Basis\n\n- ticket #131\n\n", "")
        mem_id = crowley.save_memory_item(
            "project_update",
            body,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        first = handoff_ticket_bridge.ensure_handoff_ticket_link(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        second = handoff_ticket_bridge.ensure_handoff_ticket_link(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        self.assertTrue(first.get("created"))
        self.assertEqual(second.get("linkage_decision"), "already_linked")

    def test_resolve_work_ticket_link_prefers_metadata(self) -> None:
        body = "Shipped (#999) but metadata wins."
        ticket_id, source = handoff_ticket_bridge.resolve_work_ticket_link(
            body,
            {"closed_work_ticket_id": 42},
        )
        self.assertEqual(ticket_id, 42)
        self.assertEqual(source, "metadata.closed_work_ticket_id")

    def test_get_ticket_for_handoff_memory_matches_earliest_linked(self) -> None:
        body = HANDOFF_BODY.replace("## Context Basis\n\n- ticket #131\n\n", "")
        mem_id = crowley.save_memory_item(
            "project_update",
            body,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        bridge = handoff_ticket_bridge.ensure_handoff_ticket_link(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        linked = handoff_ticket_bridge.list_tickets_for_handoff_memory(int(mem_id))
        canonical = handoff_ticket_bridge.get_ticket_for_handoff_memory(int(mem_id))
        assert canonical is not None
        self.assertEqual(int(canonical["id"]), int(linked[0]["id"]))
        self.assertEqual(int(canonical["id"]), int(bridge["ticket"]["id"]))

    def test_archival_replay_upserts_instead_of_duplicate(self) -> None:
        body = HANDOFF_BODY.replace("## Context Basis\n\n- ticket #131\n\n", "")
        mem_id = crowley.save_memory_item(
            "project_update",
            body,
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_id is not None
        first = handoff_ticket_bridge._create_archival_ticket_for_handoff(
            int(mem_id),
            body,
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        second = handoff_ticket_bridge._create_archival_ticket_for_handoff(
            int(mem_id),
            body + "\n\nReplay ingest.",
            source="cursor",
            handoff_type="builder_handoff",
            project_id=self.project_id,
        )
        self.assertTrue(first.get("created"))
        self.assertTrue(second.get("idempotent"))
        self.assertEqual(
            len(handoff_ticket_bridge.list_tickets_for_handoff_memory(int(mem_id))),
            1,
        )

    def test_linked_memory_id_immutable_on_update(self) -> None:
        mem_a = crowley.save_memory_item(
            "project_update",
            "Memory A for immutability probe — unique alpha content.",
            source="cursor",
            project_id=self.project_id,
        )
        mem_b = crowley.save_memory_item(
            "project_update",
            "Memory B for immutability probe — unique beta content.",
            source="cursor",
            project_id=self.project_id,
        )
        assert mem_a is not None and mem_b is not None
        self.assertNotEqual(int(mem_a), int(mem_b))
        created = tickets.create_ticket(
            "immutable link test",
            description="x",
            assignee="cursor",
            priority=3,
            source="system",
            actor="system",
            project_id=self.project_id,
            linked_memory_id=int(mem_a),
            status="done",
        )
        ticket_id = int(created["ticket"]["id"])
        with self.assertRaises(ValueError):
            tickets.update_ticket(
                ticket_id,
                actor="system",
                linked_memory_id=int(mem_b),
            )

    def test_ingest_enforces_handoff_ticket_parity(self) -> None:
        body = HANDOFF_BODY.replace("## Context Basis\n\n- ticket #131\n\n", "")
        result = crowley.ingest_handoff("cursor", "builder_handoff", body)
        self.assertEqual(result.get("status"), "ok")
        bridge = result.get("handoff_ticket")
        assert isinstance(bridge, dict)
        self.assertIn("ticket", bridge)
        mem_id = int(result["memory_item_id"])
        self.assertEqual(
            len(handoff_ticket_bridge.list_tickets_for_handoff_memory(mem_id)),
            1,
        )

    def test_parity_metrics_counters(self) -> None:
        before = handoff_ticket_bridge.parity_metrics()
        body = HANDOFF_BODY.replace("## Context Basis\n\n- ticket #131\n\n", "")
        crowley.ingest_handoff("cursor", "builder_handoff", body)
        after = handoff_ticket_bridge.parity_metrics()
        self.assertGreaterEqual(
            int(after["counters"]["tickets_created"]),
            int(before["counters"]["tickets_created"]),
        )
        self.assertIn("parity_ok", after)


if __name__ == "__main__":
    unittest.main()
