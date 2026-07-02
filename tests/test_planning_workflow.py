#!/usr/bin/env python3
"""V3.9.3 planning workflow doc and packet tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "V3.9.3_PLANNING_WORKFLOW.md"
WHERE_WE_ARE = ROOT / "docs" / "WHERE_WE_ARE.md"
TEMPLATE = ROOT / "tickets" / "planning_packet.template.json"
EXAMPLE = ROOT / "tickets" / "planning_packet.pre_v4_example.json"

PACKET_KEYS = frozenset({
    "objective",
    "context",
    "decisions",
    "non_goals",
    "risks",
    "qa_expectations",
    "next_action",
    "approval",
    "tickets",
})

MINT_TICKET_KEYS = frozenset({"title", "assignee", "priority", "description", "acceptance"})


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _mint_payload_from_packet(packet: dict[str, object]) -> dict[str, object]:
    tickets = packet.get("tickets")
    assert isinstance(tickets, list)
    mint_tickets: list[dict[str, object]] = []
    for item in tickets:
        assert isinstance(item, dict)
        mint_tickets.append(
            {
                "title": item["title"],
                "assignee": item["assignee"],
                "priority": item["priority"],
                "description": item["description"],
                "acceptance": item["acceptance"],
            }
        )
    return {"tickets": mint_tickets}


class PlanningWorkflowDocTests(unittest.TestCase):
    def test_planning_workflow_doc_exists(self) -> None:
        self.assertTrue(DOC.is_file(), msg="missing docs/V3.9.3_PLANNING_WORKFLOW.md")

    def test_where_we_are_links_planning_workflow_in_rituals(self) -> None:
        text = WHERE_WE_ARE.read_text(encoding="utf-8")
        rituals_idx = text.find("## 4. Agent rituals")
        self.assertGreaterEqual(rituals_idx, 0)
        rituals_section = text[rituals_idx : rituals_idx + 600]
        self.assertIn("V3.9.3_PLANNING_WORKFLOW.md", rituals_section)

    def test_doc_covers_roles_and_cursor_ready_tickets(self) -> None:
        content = DOC.read_text(encoding="utf-8")
        lower = content.lower()
        self.assertIn("mr. go", lower)
        self.assertIn("codex", lower)
        self.assertIn("cursor", lower)
        self.assertIn("crowley", lower)
        self.assertIn("cursor-ready", lower)
        self.assertIn("acceptance criteria", lower)
        self.assertIn("non-goals", lower)
        self.assertIn("qa expectation", lower)

    def test_doc_does_not_imply_direct_codex_cursor_messaging(self) -> None:
        content = DOC.read_text(encoding="utf-8").lower()
        self.assertIn("only hub", content)
        self.assertIn("do not message each other directly", content)


class PlanningPacketTemplateTests(unittest.TestCase):
    def test_template_includes_required_fields(self) -> None:
        packet = _load_json(TEMPLATE)
        self.assertTrue(PACKET_KEYS.issubset(packet.keys()))
        tickets = packet["tickets"]
        assert isinstance(tickets, list)
        self.assertGreaterEqual(len(tickets), 1)
        slice0 = tickets[0]
        assert isinstance(slice0, dict)
        self.assertTrue(MINT_TICKET_KEYS.issubset(slice0.keys()))
        self.assertIn("acceptance", slice0)
        approval = packet["approval"]
        assert isinstance(approval, dict)
        self.assertEqual(approval.get("status"), "pending")

    def test_pre_v4_example_is_realistic_and_approved(self) -> None:
        packet = _load_json(EXAMPLE)
        self.assertIn("pre-v4", str(packet["objective"]).lower())
        self.assertIn("V3.9.1", str(packet["context"]))
        approval = packet["approval"]
        assert isinstance(approval, dict)
        self.assertEqual(approval.get("status"), "approved")
        self.assertIn("pre_v4_release_plan.json", str(packet["context"]))

    def test_packet_tickets_copy_to_mint_json_without_losing_core_fields(self) -> None:
        packet = _load_json(EXAMPLE)
        mint_payload = _mint_payload_from_packet(packet)
        self.assertIn("tickets", mint_payload)
        tickets = mint_payload["tickets"]
        assert isinstance(tickets, list)
        self.assertGreaterEqual(len(tickets), 1)
        for item in tickets:
            assert isinstance(item, dict)
            self.assertTrue(MINT_TICKET_KEYS.issubset(item.keys()))
            acceptance = item["acceptance"]
            assert isinstance(acceptance, list)
            self.assertGreaterEqual(len(acceptance), 1)

    def test_workflow_doc_explains_approval_before_implementation(self) -> None:
        content = DOC.read_text(encoding="utf-8").lower()
        self.assertIn("approval gate", content)
        self.assertIn("pending", content)
        self.assertIn("planning_packet.template.json", content)


if __name__ == "__main__":
    unittest.main()
