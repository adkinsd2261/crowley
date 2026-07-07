#!/usr/bin/env python3
"""Tests for ChatGPT bridge operator helpers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import chatgpt_bridge_lib as bridge  # noqa: E402


class ChatGptBridgeLibTests(unittest.TestCase):
    def test_classify_http_failures(self) -> None:
        cases = {
            0: "local_connection",
            401: "key_mismatch",
            403: "cloudflare_or_waf",
            503: "actions_disabled",
            502: "tunnel_upstream",
        }
        for code, category in cases.items():
            hint = bridge.classify_http_failure(code, context="test")
            self.assertEqual(hint.category, category)

    def test_classify_public_root_404_is_boundary_ok(self) -> None:
        hint = bridge.classify_http_failure(404, context="public /")
        self.assertEqual(hint.category, "route_boundary_ok")

    def test_cleanup_stale_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "tunnel.pid"
            pid_file.write_text("999999999", encoding="utf-8")
            cleaned = bridge.cleanup_stale_pid_file(pid_file)
            self.assertTrue(cleaned)
            self.assertFalse(pid_file.exists())

    def test_build_verify_report_structure(self) -> None:
        report = bridge.build_verify_report(
            action_key="test-key",
            public_base=None,
            check_service=False,
        )
        self.assertIn("checks", report)
        self.assertIn("status", report)
        names = {c["name"] for c in report["checks"]}
        self.assertIn("local_bus", names)
        self.assertIn("local_actions", names)

    def test_list_connector_pids_shape(self) -> None:
        groups = bridge.list_connector_pids()
        self.assertIn("named", groups)
        self.assertIn("quick", groups)
        self.assertIsInstance(groups["named"], list)
        self.assertIsInstance(groups["quick"], list)

    def test_bus_responsive_is_bool(self) -> None:
        self.assertIsInstance(bridge.bus_responsive(timeout=1.0), bool)


if __name__ == "__main__":
    unittest.main()
