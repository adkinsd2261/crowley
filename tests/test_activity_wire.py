#!/usr/bin/env python3
"""V3.9.11 #72 — build_activity_wire builder."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS))

import agent_sync_lib as asl  # noqa: E402
import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class ActivityWireTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_wire_merges_pulses_handoffs_and_ticket_events_sorted(self) -> None:
        ticket_id = int(
            crowley.create_ticket(
                "Activity wire merge probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.record_activity_pulse(
            "cursor",
            "claimed",
            project_id=self.project_id,
            ticket_id=ticket_id,
            summary="Claimed for wire merge",
        )
        crowley.save_memory_item(
            "project_update",
            (
                "# Crowley Handoff\n\nSource: codex\n\n"
                "## Summary\n\n- Wire merge architect handoff probe\n\n"
                "## Next Action\n\n- Continue wire QA"
            ),
            source="codex",
            project_id=self.project_id,
            importance=4,
        )

        wire = crowley.build_activity_wire(self.project_id, limit=20)
        items = wire["items"]
        kinds = {item["kind"] for item in items if not item.get("is_ambient")}
        self.assertIn("pulse", kinds)
        self.assertIn("handoff", kinds)
        self.assertIn("ticket", kinds)
        timestamps = [str(item["created_at"]) for item in items if not item.get("is_ambient")]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_narrative_lines_for_key_verbs(self) -> None:
        self.assertIn(
            "claimed ticket #72",
            crowley._activity_wire_line(
                "cursor", "claimed", ticket_id=72, ticket_title="Wire builder"
            ).lower(),
        )
        self.assertIn(
            "handed off",
            crowley._activity_wire_line(
                "cursor", "handoff", summary="Shipped wire builder"
            ).lower(),
        )
        self.assertIn(
            "minted",
            crowley._activity_wire_line(
                "codex", "minted", summary="Minted 3 tickets: Live Wire"
            ).lower(),
        )
        self.assertIn(
            "closed ticket #70",
            crowley._activity_wire_line(
                "cursor", "closed", ticket_id=70, ticket_title="Pulse API"
            ).lower(),
        )

    def test_dedupe_same_agent_verb_ticket_within_two_minutes(self) -> None:
        now = datetime.now(timezone.utc)
        older = (now - timedelta(minutes=1)).isoformat()
        newer = now.isoformat()
        items = [
            {
                "id": "pulse:2",
                "kind": "pulse",
                "agent": "cursor",
                "verb": "claimed",
                "ticket_id": 72,
                "line": "newer",
                "created_at": newer,
                "is_ambient": False,
            },
            {
                "id": "pulse:1",
                "kind": "pulse",
                "agent": "cursor",
                "verb": "claimed",
                "ticket_id": 72,
                "line": "older",
                "created_at": older,
                "is_ambient": False,
            },
        ]
        deduped = crowley._dedupe_activity_wire_items(items)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], "pulse:2")

    def test_wire_needs_ambient_when_empty_or_stale(self) -> None:
        self.assertTrue(crowley._wire_needs_ambient([]))
        stale = [
            {
                "created_at": (
                    datetime.now(timezone.utc) - timedelta(minutes=60)
                ).isoformat()
            }
        ]
        self.assertTrue(crowley._wire_needs_ambient(stale))

    def test_ambient_items_include_in_progress_and_focus(self) -> None:
        crowley.update_project_state_field(
            self.project_id,
            "focus",
            "V3.9.11 Live Wire ambient probe",
            updated_by="test",
        )
        ticket_id = int(
            crowley.create_ticket(
                "Ambient in-progress probe",
                assignee="cursor",
                project_id=self.project_id,
            )["ticket"]["id"]
        )
        crowley.update_ticket(ticket_id, actor="cursor", status="in_progress")

        ambient = crowley._ambient_activity_wire_items(self.project_id)
        self.assertGreaterEqual(len(ambient), 1)
        lines = " ".join(str(item["line"]) for item in ambient).lower()
        self.assertIn("in-progress probe", lines)
        self.assertIn("focus", lines)

    def test_build_activity_wire_adds_ambient_when_no_real_activity(self) -> None:
        crowley.update_project_state_field(
            self.project_id,
            "focus",
            "Quiet wire fallback probe",
            updated_by="test",
        )
        wire = crowley.build_activity_wire(self.project_id, limit=20)
        self.assertTrue(any(item.get("is_ambient") for item in wire["items"]))

    def test_build_activity_wire_empty_without_project(self) -> None:
        wire = crowley.build_activity_wire(None)
        self.assertEqual(wire["items"], [])
        self.assertIsNone(wire["pinned_focus"])


if __name__ == "__main__":
    unittest.main()


class ActivityWireExposureTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_world_dashboard_includes_activity_wire_capped(self) -> None:
        crowley.record_activity_pulse(
            "cursor",
            "claimed",
            project_id=self.project_id,
            ticket_id=72,
            summary="World wire exposure probe",
        )
        dash = crowley.build_world_dashboard()
        wire = dash.get("activity_wire")
        assert isinstance(wire, dict)
        self.assertEqual(wire.get("cap"), crowley.ACTIVITY_WIRE_WORLD_CAP)
        items = wire.get("items")
        assert isinstance(items, list)
        self.assertLessEqual(len(items), crowley.ACTIVITY_WIRE_WORLD_CAP)
        self.assertIn("pinned_focus", wire)
        self.assertIn("active_agents", wire)

    def test_agent_sync_bundle_includes_slim_activity_wire(self) -> None:
        crowley.record_activity_pulse(
            "codex",
            "minted",
            project_id=self.project_id,
            summary="Codex minted wire probe",
        )
        crowley.record_activity_pulse(
            "cursor",
            "handoff",
            project_id=self.project_id,
            summary="Cursor handoff wire probe",
        )
        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        wire = sync.get("activity_wire")
        assert isinstance(wire, dict)
        self.assertEqual(wire.get("cap"), crowley.ACTIVITY_WIRE_SYNC_CAP)
        items = wire.get("items")
        assert isinstance(items, list)
        self.assertLessEqual(len(items), crowley.ACTIVITY_WIRE_SYNC_CAP)
        caps = sync.get("bundle_caps")
        assert isinstance(caps, dict)
        self.assertEqual(caps.get("activity_wire"), crowley.ACTIVITY_WIRE_SYNC_CAP)

    def test_sync_wire_prioritizes_other_agent_items(self) -> None:
        now = crowley._now_iso()
        wire = {
            "pinned_focus": "Wire priority probe",
            "active_agents": ["cursor", "codex"],
            "items": [
                {
                    "id": "pulse:1",
                    "kind": "pulse",
                    "agent": "cursor",
                    "verb": "handoff",
                    "ticket_id": None,
                    "line": "Cursor handed off",
                    "created_at": now,
                    "is_ambient": False,
                },
                {
                    "id": "pulse:2",
                    "kind": "pulse",
                    "agent": "codex",
                    "verb": "minted",
                    "ticket_id": None,
                    "line": "Codex minted tickets",
                    "created_at": now,
                    "is_ambient": False,
                },
            ],
        }
        slim = crowley._slim_activity_wire_for_agent(wire, "cursor", limit=5)
        agents = [str(item["agent"]) for item in slim["items"] if isinstance(item, dict)]
        self.assertGreaterEqual(len(agents), 2)
        self.assertEqual(agents[0], "codex")

    def test_cli_prints_in_the_air_section(self) -> None:
        sync = crowley.build_agent_sync_bundle("cursor", limit=8)
        buffer = StringIO()
        with patch("sys.stdout", buffer):
            asl.print_agent_sync_bundle(sync, agent="cursor")
        output = buffer.getvalue()
        self.assertIn("In the air:", output)
        working_idx = output.find("Working on:")
        in_air_idx = output.find("In the air:")
        if working_idx >= 0:
            self.assertGreater(working_idx, in_air_idx)
