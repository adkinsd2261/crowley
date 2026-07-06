#!/usr/bin/env python3
"""V3.9.17 #114 — Write audit log and rollback tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import tickets  # noqa: E402
import write_audit  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class WriteAuditTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        write_audit.ensure_write_audit_table(self.conn)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_memory_save_creates_audit_entry(self) -> None:
        item_id = crowley.save_memory_item(
            "lesson",
            "Audit log probe for memory save.",
            source="cursor",
            project_id=self.project_id,
            agent_id="cursor",
            write_action="test.audit",
        )
        assert item_id is not None
        items, total = write_audit.list_write_audit_log(entity_id=int(item_id))
        self.assertGreaterEqual(total, 1)
        entry = items[0]
        self.assertEqual(entry["entity_type"], "memory_item")
        self.assertEqual(entry["agent_id"], "cursor")
        self.assertIsNone(entry["before"])
        self.assertIsNotNone(entry["after"])

    def test_ticket_update_audit_and_rollback(self) -> None:
        created = tickets.create_ticket(
            "Audit rollback probe",
            project_id=self.project_id,
            actor="codex",
            source="codex",
        )
        ticket_id = int(created["ticket"]["id"])
        tickets.update_ticket(
            ticket_id,
            actor="codex",
            status="in_progress",
        )
        items, _ = write_audit.list_write_audit_log(
            entity_type="ticket",
            entity_id=ticket_id,
        )
        update_entry = next(
            (item for item in items if item["action"] == "ticket.update"),
            None,
        )
        self.assertIsNotNone(update_entry)
        assert update_entry is not None
        result = write_audit.rollback_write_audit(
            int(update_entry["id"]),
            agent_id="codex",
        )
        self.assertTrue(result["ok"])
        ticket = tickets.get_ticket_by_id(ticket_id)
        assert ticket is not None
        self.assertEqual(str(ticket["status"]), "open")

    def test_memory_create_rollback_marks_rolled_back(self) -> None:
        item_id = crowley.save_memory_item(
            "lesson",
            "Rollback create probe.",
            source="cursor",
            project_id=self.project_id,
            agent_id="cursor",
        )
        assert item_id is not None
        items, _ = write_audit.list_write_audit_log(entity_id=int(item_id))
        create_entry = items[-1]
        write_audit.rollback_write_audit(int(create_entry["id"]), agent_id="codex")
        row = self.conn.execute(
            "SELECT status FROM memory_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        self.assertEqual(str(row["status"]), "rolled_back")

    def test_writer_cannot_rollback(self) -> None:
        item_id = crowley.save_memory_item(
            "lesson",
            "Permission rollback probe.",
            source="cursor",
            project_id=self.project_id,
            agent_id="cursor",
        )
        assert item_id is not None
        items, _ = write_audit.list_write_audit_log(entity_id=int(item_id))
        with self.assertRaises(ValueError):
            write_audit.rollback_write_audit(int(items[0]["id"]), agent_id="cursor")


if __name__ == "__main__":
    unittest.main()
