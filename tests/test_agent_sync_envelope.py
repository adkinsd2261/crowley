#!/usr/bin/env python3
"""Agent sync limit enforcement, ASE, and deep sync tests (#229–#231)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import agent_sync_envelope as ase  # noqa: E402
import app as crowley_app  # noqa: E402
import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class AgentSyncEnvelopeTests(IsolatedDbTestCase):
    def test_limit_caps_tickets_handoffs_and_memories(self) -> None:
        sync = crowley.build_agent_sync_bundle("cursor", limit=3)
        caps = sync["bundle_caps"]
        assert isinstance(caps, dict)
        self.assertEqual(caps["sync_limit"], 3)
        self.assertEqual(caps["handoffs"], 3)
        self.assertEqual(caps["tickets_open"], 3)
        self.assertLessEqual(len(sync["tickets"]["open"]), 3)
        self.assertLessEqual(sync["recent_handoffs"]["total"], 3)
        self.assertLessEqual(len(sync["relevant_memories"]), 3)

    def test_finalize_applies_ase_meta_and_compression(self) -> None:
        bundle = crowley.build_agent_sync_bundle("cursor", limit=8)
        bundle["recent_handoffs"] = {
            "items": [
                {
                    "id": 1,
                    "content": "x" * 500,
                    "display": "full display",
                    "created_at": "2026-07-07T00:00:00Z",
                }
            ],
            "total": 1,
        }
        finalized = crowley.finalize_agent_sync_bundle(bundle)
        meta = finalized["sync_meta"]
        assert isinstance(meta, dict)
        self.assertEqual(meta["envelope"], ase.ASE_ENVELOPE_VERSION)
        self.assertLessEqual(meta["payload_bytes"], ase.MAX_PAYLOAD_BYTES)
        item = finalized["recent_handoffs"]["items"][0]
        self.assertIn("summary", item)
        self.assertNotIn("content", item)

    def test_ase_trims_memory_before_tickets_under_budget(self) -> None:
        bundle = {
            "agent": "cursor",
            "recent_handoffs": {"items": [{"id": 1, "summary": "keep", "timestamp": "now"}], "total": 1},
            "tickets": {
                "open": [{"id": idx, "title": f"t{idx}", "description": "d", "status": "open"} for idx in range(6)],
                "assigned_to_agent": [],
                "blocked": [],
                "recently_closed": [],
                "grouped_open": [],
                "counts": {},
            },
            "relevant_memories": [
                {"id": idx, "content": "m" * 500, "created_at": "now"}
                for idx in range(20)
            ],
        }
        finalized = ase.apply_adaptive_sync_envelope(bundle, max_bytes=1200)
        truncated = finalized["sync_meta"]["truncated"]
        assert isinstance(truncated, dict)
        self.assertTrue(truncated["memory"])
        self.assertFalse(truncated["handoffs"])
        self.assertLessEqual(finalized["sync_meta"]["payload_bytes"], 1200)

    def test_deep_sync_cursor_roundtrip_and_pagination(self) -> None:
        cursor = ase.encode_deep_sync_cursor("tickets", 5)
        section, offset = ase.decode_deep_sync_cursor(cursor)
        self.assertEqual(section, "tickets")
        self.assertEqual(offset, 5)

        page = ase.build_deep_sync_page("cursor", "tickets", limit=2)
        self.assertEqual(page["section"], "tickets")
        self.assertLessEqual(len(page["items"]), 2)
        if page["next_cursor"]:
            page2 = ase.build_deep_sync_page(
                "cursor",
                "tickets",
                cursor=page["next_cursor"],
                limit=2,
            )
            self.assertGreaterEqual(page2["offset"], page["offset"])

    def test_api_agent_sync_returns_finalized_envelope(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.get("/api/agent/sync", params={"agent": "cursor", "limit": 5})
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertIn("sync_meta", data)
        self.assertEqual(data["sync_meta"]["envelope"], ase.ASE_ENVELOPE_VERSION)
        self.assertLessEqual(data["sync_meta"]["payload_bytes"], ase.MAX_PAYLOAD_BYTES)

    def test_api_deep_sync_rejects_invalid_section(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.get(
            "/api/agent/deep_sync",
            params={"agent": "cursor", "section": "invalid"},
        )
        self.assertEqual(res.status_code, 400)

    def test_memory_limit_respects_low_limit(self) -> None:
        self.assertEqual(crowley._agent_sync_memory_limit(2), 2)
        self.assertEqual(crowley._agent_sync_memory_limit(99), 4)


if __name__ == "__main__":
    unittest.main()
