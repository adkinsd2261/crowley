#!/usr/bin/env python3
"""V3.9.17 #112 — Agent identity and write attribution tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_identity  # noqa: E402
import crowley  # noqa: E402
import tickets  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class AgentIdentityUnitTests(unittest.TestCase):
    def test_build_write_attribution_signature_is_stable(self) -> None:
        attr = agent_identity.build_write_attribution(
            "cursor",
            "cursor",
            timestamp="2026-07-06T00:00:00+00:00",
            action="memory.save",
            content_hint="hello world",
        )
        self.assertEqual(attr["agent_id"], "cursor")
        self.assertEqual(attr["source"], "cursor")
        self.assertEqual(attr["attribution_version"], "1")
        self.assertEqual(len(str(attr["signature"])), 16)

        again = agent_identity.build_write_attribution(
            "cursor",
            "cursor",
            timestamp="2026-07-06T00:00:00+00:00",
            action="memory.save",
            content_hint="hello world",
        )
        self.assertEqual(attr["signature"], again["signature"])

    def test_normalize_agent_id_falls_back_to_source(self) -> None:
        self.assertEqual(
            agent_identity.normalize_agent_id(None, fallback_source="chatgpt"),
            "chatgpt",
        )

    def test_writer_cannot_mint_tickets(self) -> None:
        ok, msg = agent_identity.check_write_permission("cursor", "ticket.create")
        self.assertFalse(ok)
        self.assertIn("permission_denied", msg or "")

    def test_architect_can_mint_tickets(self) -> None:
        ok, _ = agent_identity.check_write_permission("codex", "ticket.create")
        self.assertTrue(ok)


class AgentPermissionsIntegrationTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_cursor_actor_blocked_from_ticket_create(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            tickets.create_ticket(
                "Permission probe",
                project_id=self.project_id,
                source="manual",
                actor="cursor",
            )
        self.assertIn("permission_denied", str(ctx.exception))

    def test_sync_bundle_includes_permissions(self) -> None:
        bundle = crowley.build_agent_sync_bundle("cursor")
        perms = bundle.get("permissions")
        self.assertIsInstance(perms, dict)
        assert isinstance(perms, dict)
        self.assertEqual(perms.get("role"), "writer")
        self.assertIn("ticket.create", perms.get("restricted_actions", []))


class AgentIdentityIntegrationTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_save_memory_item_records_write_attribution(self) -> None:
        item_id = crowley.save_memory_item(
            "lesson",
            "Attribution probe for cursor builder loop.",
            source="cursor",
            project_id=self.project_id,
            agent_id="cursor",
            write_action="test.save",
        )
        assert item_id is not None
        row = self.conn.execute(
            "SELECT metadata_json FROM memory_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        meta = json.loads(str(row["metadata_json"]))
        attr = meta["write_attribution"]
        self.assertEqual(attr["agent_id"], "cursor")
        self.assertEqual(attr["action"], "test.save")
        self.assertIn("signature", attr)

        api = crowley._memory_item_api_dict(
            self.conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (item_id,)
            ).fetchone()
        )
        self.assertEqual(api["agent_id"], "cursor")
        self.assertEqual(api["attribution"]["source"], "cursor")

    def test_list_memory_items_filters_by_agent_id(self) -> None:
        crowley.save_memory_item(
            "lesson",
            "Cursor-only attribution filter probe.",
            source="cursor",
            project_id=self.project_id,
            agent_id="cursor",
        )
        crowley.save_memory_item(
            "lesson",
            "Codex-only attribution filter probe.",
            source="codex",
            project_id=self.project_id,
            agent_id="codex",
        )
        rows, total = crowley.list_memory_items(
            agent_id="cursor",
            status="active",
            limit=50,
        )
        self.assertGreaterEqual(total, 1)
        for row in rows:
            api = crowley._memory_item_api_dict(row)
            self.assertEqual(api["agent_id"], "cursor")

    def test_retrieval_explanation_includes_attribution(self) -> None:
        item_id = crowley.save_memory_item(
            "constraint",
            "Retrieval attribution explain probe for V3.9.17.",
            source="codex",
            project_id=self.project_id,
            agent_id="codex",
            write_action="test.retrieve",
        )
        assert item_id is not None
        results = crowley.retrieve_memories(
            "V3.9.17 attribution explain probe",
            limit=10,
            project_id=self.project_id,
        )
        match = next((r for r in results if int(r["id"]) == int(item_id)), None)
        self.assertIsNotNone(match)
        assert match is not None
        explanation = match.get("explanation")
        self.assertIsInstance(explanation, dict)
        assert isinstance(explanation, dict)
        self.assertIn("attribution", explanation)
        self.assertEqual(explanation["attribution"]["agent_id"], "codex")

    def test_ticket_events_carry_write_attribution(self) -> None:
        result = tickets.create_ticket(
            "Attribution ticket probe",
            project_id=self.project_id,
            source="codex",
            actor="codex",
        )
        ticket_id = int(result["ticket"]["id"])
        detail = tickets.get_ticket_detail(ticket_id)
        assert detail is not None
        created = detail["events"][0]
        payload = created["payload"]
        self.assertIn("write_attribution", payload)
        self.assertEqual(payload["write_attribution"]["agent_id"], "codex")

    def test_ingest_handoff_records_attribution(self) -> None:
        content = (
            "# Crowley Handoff\n\n"
            "Source: cursor\nType: builder_handoff\n\n"
            "## Summary\n\nAttribution handoff ingest probe.\n"
        )
        result = crowley.ingest_handoff("cursor", "builder_handoff", content)
        memory_id = result.get("memory_item_id")
        self.assertIsNotNone(memory_id)
        row = self.conn.execute(
            "SELECT metadata_json FROM memory_items WHERE id = ?",
            (int(memory_id),),
        ).fetchone()
        meta = json.loads(str(row["metadata_json"]))
        self.assertEqual(meta["write_attribution"]["agent_id"], "cursor")
        self.assertTrue(str(meta["write_attribution"]["action"]).startswith("handoff."))


if __name__ == "__main__":
    unittest.main()
