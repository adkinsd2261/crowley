#!/usr/bin/env python3
"""Ticket ↔ memory linkage tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import memory_ticket_linkage  # noqa: E402
import tickets  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class MemoryTicketLinkageTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        memory_ticket_linkage.ensure_linkage_column(self.conn)
        self.conn.commit()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None
        self.ticket_ids: list[int] = []
        self.memory_ids: list[int] = []

    def tearDown(self) -> None:
        if self.memory_ids:
            marks = ",".join("?" for _ in self.memory_ids)
            self.conn.execute(
                f"DELETE FROM memory_items WHERE id IN ({marks})",
                self.memory_ids,
            )
        if self.ticket_ids:
            marks = ",".join("?" for _ in self.ticket_ids)
            self.conn.execute(
                f"DELETE FROM ticket_events WHERE ticket_id IN ({marks})",
                self.ticket_ids,
            )
            self.conn.execute(
                f"DELETE FROM tickets WHERE id IN ({marks})",
                self.ticket_ids,
            )
        self.conn.commit()
        self.conn.close()
        super().tearDown()

    def _create_ticket(self, **kwargs: object) -> int:
        result = crowley.create_ticket(
            str(kwargs.pop("title", "Linkage probe")),
            project_id=self.project_id,
            **kwargs,  # type: ignore[arg-type]
        )
        ticket_id = int(result["ticket"]["id"])
        self.ticket_ids.append(ticket_id)
        return ticket_id

    def _create_memory(self, content: str, **kwargs: object) -> int:
        mem_id = crowley.save_memory_item(
            str(kwargs.pop("memory_type", "decision")),
            content,
            source=str(kwargs.pop("source", "cursor")),
            project_id=self.project_id,
            **kwargs,  # type: ignore[arg-type]
        )
        assert mem_id is not None
        self.memory_ids.append(int(mem_id))
        return int(mem_id)

    def test_persist_and_batch_linked_ticket_ids(self) -> None:
        ticket_id = self._create_ticket(title="Persist link probe")
        mem_id = self._create_memory(f"Decision for ticket #{ticket_id} shipped.")
        memory_ticket_linkage.persist_memory_ticket_links(
            self.conn, mem_id, [ticket_id], merge=False
        )
        self.conn.commit()
        linked = memory_ticket_linkage.batch_linked_ticket_ids([mem_id], conn=self.conn)
        self.assertEqual(linked[mem_id], [ticket_id])

    def test_reverse_handoff_link_inferred(self) -> None:
        ticket_id = self._create_ticket(title="Reverse link probe")
        mem_id = self._create_memory("Handoff body without explicit ticket hash.")
        tickets.update_ticket(
            ticket_id,
            actor="cursor",
            linked_memory_id=mem_id,
        )
        row = self.conn.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (mem_id,),
        ).fetchone()
        assert row is not None
        inferred = memory_ticket_linkage.infer_ticket_ids_from_memory(row, conn=self.conn)
        self.assertIn(ticket_id, inferred)

    def test_get_ticket_detail_include_memories(self) -> None:
        ticket_id = self._create_ticket(title="Detail memory bundle probe")
        mem_id = self._create_memory(
            f"Lesson learned on ticket #{ticket_id}: keep links explicit.",
            memory_type="lesson",
        )
        memory_ticket_linkage.persist_memory_ticket_links(
            self.conn, mem_id, [ticket_id], merge=False
        )
        self.conn.commit()
        detail = tickets.get_ticket_detail(ticket_id, include_memories=True)
        assert detail is not None
        self.assertIn("linked_memories", detail)
        grouped = detail["linked_memories"]
        assert isinstance(grouped, dict)
        lessons = grouped.get("lessons")
        assert isinstance(lessons, list)
        self.assertGreaterEqual(len(lessons), 1)
        self.assertEqual(int(lessons[0]["id"]), mem_id)

    def test_backfill_dry_run_and_apply(self) -> None:
        ticket_id = self._create_ticket(title="Backfill probe")
        mem_id = self._create_memory(f"QA result for ticket #{ticket_id} passed.")
        preview = memory_ticket_linkage.backfill_memory_ticket_links(dry_run=True)
        self.assertGreaterEqual(int(preview["scanned"]), 1)
        applied = memory_ticket_linkage.backfill_memory_ticket_links(dry_run=False, limit=5000)
        self.assertGreaterEqual(int(applied["updated"]), 1)
        row = self.conn.execute(
            f"SELECT {memory_ticket_linkage.LINKED_TICKET_IDS_COLUMN} FROM memory_items WHERE id = ?",
            (mem_id,),
        ).fetchone()
        assert row is not None
        stored = json.loads(str(row[0]))
        self.assertIn(ticket_id, stored)

    def test_audit_report_shape(self) -> None:
        ticket_id = self._create_ticket(title="Audit probe")
        mem_id = self._create_memory(f"Update on ticket #{ticket_id}.")
        memory_ticket_linkage.persist_memory_ticket_links(
            self.conn, mem_id, [ticket_id], merge=False
        )
        self.conn.commit()
        report = memory_ticket_linkage.audit_memory_ticket_linkage(
            project_id=self.project_id
        )
        self.assertIn("memory_items_mapped_pct", report)
        self.assertGreaterEqual(int(report["memory_items_mapped"]), 1)
        self.assertIn("tickets_with_memory_context", report)


if __name__ == "__main__":
    unittest.main()
