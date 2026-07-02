#!/usr/bin/env python3
"""Chat API UX tests — empty, slash rejection, model/empty errors, streaming."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import app as crowley_app  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def parse_sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "" and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


class ChatApiUxTests(unittest.TestCase):
    def test_empty_message_returns_clear_error(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.post("/api/chat", json={"message": "   "})
        events = parse_sse_events(res.text)
        self.assertEqual(events, [("error", {"message": "Message cannot be empty."})])

    def test_slash_command_is_rejected_clearly(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.post("/api/chat", json={"message": "/state"})
        events = parse_sse_events(res.text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "error")
        self.assertIn("terminal", events[0][1]["message"].lower())
        self.assertIn("python crowley.py", events[0][1]["message"])

    def test_chat_error_message_maps_model_and_empty_errors(self) -> None:
        self.assertIn("API key", crowley_app.chat_error_message("model unavailable"))
        self.assertIn("didn't get a response", crowley_app.chat_error_message("empty response"))
        self.assertEqual(
            crowley_app.chat_error_message("custom failure"),
            "custom failure",
        )


class ChatApiStreamingTests(IsolatedDbTestCase):
    def test_model_unavailable_streams_error_after_thinking(self) -> None:
        with mock.patch.object(
            crowley,
            "chat_turn",
            return_value=crowley.ChatTurnResult(
                user_message_id=1,
                assistant_message_id=None,
                reply=None,
                error="model unavailable",
            ),
        ):
            with TestClient(crowley_app.app) as client:
                res = client.post("/api/chat", json={"message": "hello"})

        events = parse_sse_events(res.text)
        self.assertEqual(events[0][0], "status")
        self.assertEqual(events[-1][0], "error")
        self.assertIn("API key", events[-1][1]["message"])

    def test_empty_response_streams_clear_error(self) -> None:
        with mock.patch.object(
            crowley,
            "chat_turn",
            return_value=crowley.ChatTurnResult(
                user_message_id=1,
                assistant_message_id=None,
                reply=None,
                error="empty response",
            ),
        ):
            with TestClient(crowley_app.app) as client:
                res = client.post("/api/chat", json={"message": "hello"})

        events = parse_sse_events(res.text)
        self.assertEqual(events[-1][0], "error")
        self.assertIn("didn't get a response", events[-1][1]["message"])

    def test_successful_turn_emits_tokens_and_done(self) -> None:
        def fake_turn(message: str, on_token=None, **kwargs):  # noqa: ANN001
            if on_token:
                on_token("Hi")
                on_token(" there")
            return crowley.ChatTurnResult(
                user_message_id=1,
                assistant_message_id=2,
                reply="Hi there",
            )

        with mock.patch.object(crowley, "chat_turn", side_effect=fake_turn):
            with TestClient(crowley_app.app) as client:
                res = client.post("/api/chat", json={"message": "hello"})

        events = parse_sse_events(res.text)
        kinds = [name for name, _ in events]
        self.assertEqual(kinds[0], "status")
        self.assertIn("token", kinds)
        self.assertEqual(kinds[-1], "done")
        self.assertEqual(events[-1][1]["reply"], "Hi there")


if __name__ == "__main__":
    unittest.main()
