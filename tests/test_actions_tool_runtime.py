#!/usr/bin/env python3
"""Tests for Actions tool runtime guards."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import actions_tool_runtime as runtime  # noqa: E402


class ActionsToolRuntimeTests(unittest.TestCase):
    def test_tool_timeout_defaults(self) -> None:
        self.assertEqual(runtime.tool_timeout_seconds("agent.sync"), 45)
        self.assertEqual(runtime.tool_timeout_seconds("unknown.tool"), 30)

    def test_invoke_tool_handler_success(self) -> None:
        def handler(args: dict) -> tuple[dict, int | None]:
            return {"ok": True, "value": args.get("x")}, None

        body, status, error = runtime.invoke_tool_handler(
            "ticket.get",
            handler,
            {"x": 1},
        )
        self.assertIsNone(error)
        self.assertEqual(status, None)
        assert body is not None
        self.assertTrue(body.get("ok"))

    def test_invoke_tool_handler_timeout(self) -> None:
        def slow_handler(args: dict) -> tuple[dict, int | None]:
            time.sleep(0.2)
            return {"ok": True}, None

        prior = runtime.TOOL_TIMEOUT_SECONDS.get("ticket.get")
        runtime.TOOL_TIMEOUT_SECONDS["ticket.get"] = 0
        try:
            _body, status, error = runtime.invoke_tool_handler(
                "ticket.get",
                slow_handler,
                {},
            )
            self.assertEqual(error, "tool_timeout")
            self.assertEqual(status, 504)
        finally:
            if prior is None:
                runtime.TOOL_TIMEOUT_SECONDS.pop("ticket.get", None)
            else:
                runtime.TOOL_TIMEOUT_SECONDS["ticket.get"] = prior


if __name__ == "__main__":
    unittest.main()
