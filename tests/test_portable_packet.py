"""V3.9.12 #76 — portable context packet exporter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import app as crowley_app  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class PortablePacketTests(IsolatedDbTestCase):
    def test_build_packet_shape(self) -> None:
        packet = crowley.build_portable_context_packet("chatgpt")
        for key in (
            "packet_version",
            "crowley_version",
            "surface",
            "identity",
            "world",
            "work",
            "guardrails",
            "memories",
            "writeback_contract",
            "context_pull_guidance",
        ):
            self.assertIn(key, packet)
        self.assertEqual(packet["surface"], "chatgpt")
        identity = packet["identity"]
        assert isinstance(identity, dict)
        self.assertIn("persistent context layer", identity["crowley_role"].lower())

    def test_markdown_is_paste_ready(self) -> None:
        packet = crowley.build_portable_context_packet("claude")
        markdown = crowley.render_portable_context_packet_markdown(packet)
        self.assertIn("# Crowley portable context packet", markdown)
        self.assertIn("## Crowley identity", markdown)
        self.assertIn("## Writeback contract", markdown)
        self.assertIn("```json", markdown)
        self.assertIn("context_pull_candidates", markdown)
        self.assertLessEqual(len(markdown), crowley.PORTABLE_PACKET_MAX_CHARS + 80)

    def test_no_raw_db_dump(self) -> None:
        packet = crowley.build_portable_context_packet("chatgpt")
        blob = json.dumps(packet)
        self.assertNotIn("CREATE TABLE", blob)
        self.assertNotIn('"messages"', blob)
        world = packet.get("world")
        assert isinstance(world, dict)
        self.assertNotIn("memory_items", world)

    def test_writeback_contract_lanes(self) -> None:
        contract = crowley.portable_writeback_contract()
        lanes = contract.get("allowed_lanes")
        assert isinstance(lanes, list)
        for lane in ("work", "learning", "health"):
            self.assertIn(lane, lanes)

    def test_api_portable_packet(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.get("/api/portable/packet?surface=chatgpt")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("markdown", data)
        self.assertIn("packet", data)
        self.assertGreater(data["char_count"], 200)

    def test_export_script_prints_markdown(self) -> None:
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "export_portable_packet.py"),
                "--surface",
                "chatgpt",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env={
                **dict(__import__("os").environ),
                "CROWLEY_TEST_MODE": "1",
                "CROWLEY_EMBED_PROVIDER": "off",
            },
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Crowley portable context packet", proc.stdout)


if __name__ == "__main__":
    import unittest

    unittest.main()
