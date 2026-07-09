#!/usr/bin/env python3
"""V4.1 — conversation runtime and CLI shell extraction compatibility tests."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import cli_shell  # noqa: E402
import conversation_runtime  # noqa: E402
import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class ConversationCliExtractionTests(IsolatedDbTestCase):
    def test_conversation_runtime_backs_mode_depth_and_prompt_facades(self) -> None:
        self.assertEqual(
            conversation_runtime.classify_conversation_mode(crowley, "quick status"),
            crowley.classify_conversation_mode("quick status"),
        )
        self.assertEqual(
            conversation_runtime.classify_response_depth(crowley, "quick status"),
            crowley.classify_response_depth("quick status"),
        )

        direct = conversation_runtime.build_prompt(crowley, "quick status")
        facade = crowley.build_prompt("quick status")
        self.assertEqual(direct[0]["content"], facade[0]["content"])
        self.assertIn("Conversation mode (inferred): status", direct[0]["content"])
        self.assertIn("Response depth (inferred): brief", direct[0]["content"])

    def test_chat_turn_module_uses_runtime_facade_dependencies(self) -> None:
        with mock.patch.object(crowley, "call_model", return_value="Hello from T8"):
            with mock.patch.object(crowley, "maybe_create_spark") as spark:
                with mock.patch.object(crowley, "maybe_extract_state") as extract:
                    result = conversation_runtime.chat_turn(crowley, "hello")

        self.assertEqual(result.reply, "Hello from T8")
        self.assertIsNotNone(result.user_message_id)
        self.assertIsNotNone(result.assistant_message_id)
        spark.assert_called_once()
        extract.assert_called_once()

    def test_cli_shell_backs_command_parser_and_noninteractive_hygiene(self) -> None:
        self.assertEqual(
            cli_shell._parse_task_add(crowley, "Build T8 | tomorrow | crowley"),
            ("Build T8", "tomorrow", "crowley"),
        )

        buffer = io.StringIO()
        with mock.patch.object(sys, "argv", ["crowley.py", "--hygiene"]):
            with mock.patch.object(crowley, "setup_db") as setup:
                with mock.patch.object(
                    crowley,
                    "memory_hygiene_report",
                    return_value={"secret_like_findings": 0},
                ):
                    with redirect_stdout(buffer):
                        handled = cli_shell._run_cli_hygiene(crowley)

        self.assertTrue(handled)
        setup.assert_called_once()
        self.assertIn('"secret_like_findings": 0', buffer.getvalue())


if __name__ == "__main__":
    import unittest

    unittest.main()
