#!/usr/bin/env python3
"""Tests for ChatGPT Actions HTTPS verifier."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import verify_chatgpt_actions_https as verifier  # noqa: E402


class VerifyChatGptActionsHttpsTests(unittest.TestCase):
    def test_verify_fails_when_host_unreachable(self) -> None:
        rc = verifier.verify(
            base_url="https://crowley-bridge-test.invalid",
            action_key="test-key",
            wait_seconds=1,
        )
        self.assertEqual(rc, 1)

    def test_resolve_host_ip_returns_localhost(self) -> None:
        ip = verifier.resolve_host_ip("localhost")
        self.assertEqual(ip, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
