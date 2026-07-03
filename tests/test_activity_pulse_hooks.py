#!/usr/bin/env python3
"""V3.9.11 #71 — sync script activity pulse hooks."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(SCRIPTS))

import agent_sync_lib as asl  # noqa: E402
import codex_sync as cs  # noqa: E402
import cursor_sync as curs  # noqa: E402


class PostActivityPulseTests(unittest.TestCase):
    def test_never_raises_on_send_failure(self) -> None:
        with mock.patch.object(asl, "send_json", return_value=(None, "HTTP 500")):
            asl.post_activity_pulse("cursor", "session_start")

    def test_never_raises_on_exception(self) -> None:
        with mock.patch.object(asl, "send_json", side_effect=RuntimeError("bus down")):
            asl.post_activity_pulse("cursor", "session_start")

    def test_posts_expected_payload(self) -> None:
        with mock.patch.object(asl, "send_json", return_value=({"ok": True}, None)) as mock_send:
            asl.post_activity_pulse(
                "cursor",
                "claimed",
                ticket_id=71,
                summary="Claimed ticket #71",
            )
        mock_send.assert_called_once()
        path, payload = mock_send.call_args[0]
        self.assertEqual(path, "/api/activity/pulse")
        self.assertEqual(payload["agent"], "cursor")
        self.assertEqual(payload["verb"], "claimed")
        self.assertEqual(payload["ticket_id"], 71)
        self.assertIn("Claimed ticket #71", payload["summary"])


class CursorSyncPulseHookTests(unittest.TestCase):
    def test_before_posts_session_start(self) -> None:
        sync = {"agent": "cursor", "state": {}, "bus_health": {"version": "3.9.10"}}
        with (
            mock.patch.object(curs, "_ensure_bus"),
            mock.patch.object(asl, "fetch_json", return_value=(sync, None)),
            mock.patch.object(asl, "print_agent_sync_bundle"),
            mock.patch.object(asl, "post_activity_pulse") as pulse,
        ):
            self.assertEqual(curs.before(), 0)
        pulse.assert_called_once_with("cursor", "session_start")

    def test_claim_ticket_posts_claimed_pulse(self) -> None:
        with (
            mock.patch.object(curs, "_ensure_bus"),
            mock.patch.object(asl, "update_ticket_api", return_value=(True, None)),
            mock.patch.object(asl, "post_activity_pulse") as pulse,
        ):
            self.assertEqual(curs.claim_ticket_cmd(71), 0)
        pulse.assert_called_once_with(
            "cursor",
            "claimed",
            ticket_id=71,
            summary="Claimed ticket #71",
        )

    def test_note_posts_note_pulse_on_successful_ingest(self) -> None:
        handoff = mock.Mock()
        handoff.write_text = mock.Mock()
        handoff.relative_to.return_value = Path(".crowley/inbox/cursor_note_probe.md")
        with (
            mock.patch.object(curs, "_ensure_bus"),
            mock.patch.object(curs, "INBOX", Path("/tmp/crowley-test-inbox")),
            mock.patch.object(curs, "_run", return_value=mock.Mock(returncode=0)),
            mock.patch.object(curs, "_latest_handoff", return_value=handoff),
            mock.patch.object(curs, "_ingest_and_verify", return_value=True),
            mock.patch.object(asl, "clear_session_marker"),
            mock.patch.object(asl, "post_activity_pulse") as pulse,
        ):
            self.assertEqual(curs.note("Mid-session builder update"), 0)
        handoff.write_text.assert_called_once()
        pulse.assert_called_once_with("cursor", "note", summary="Mid-session builder update")

    def test_after_posts_handoff_pulse_on_successful_ingest(self) -> None:
        args = mock.Mock(
            handoff_type="builder_handoff",
            summary=None,
            ticket=71,
            decision=[],
            lesson=[],
            state_changed=[],
            next_action=None,
            do_not_build=[],
            open_loop=[],
            qa_result=[],
            known_issue=[],
        )
        handoff = mock.Mock()
        handoff.relative_to.return_value = Path(".crowley/inbox/cursor_after_probe.md")
        with (
            mock.patch.object(curs, "_ensure_bus"),
            mock.patch.object(curs, "INBOX", Path("/tmp/crowley-test-inbox")),
            mock.patch.object(curs, "_run", return_value=mock.Mock(returncode=0)),
            mock.patch.object(curs, "_latest_handoff", return_value=handoff),
            mock.patch.object(curs, "_has_real_handoff_content", return_value=(True, "")),
            mock.patch.object(curs, "_ingest_and_verify", return_value=True),
            mock.patch.object(asl, "clear_session_marker"),
            mock.patch.object(asl, "complete_ticket_api", return_value=(True, None)),
            mock.patch.object(asl, "last_handoff_memory_id", return_value=99),
            mock.patch.object(asl, "format_handoff_closed_ticket", return_value="linked"),
            mock.patch.object(asl, "post_activity_pulse") as pulse,
        ):
            self.assertEqual(curs.after(args), 0)
        handoff.write_text.assert_not_called()
        pulse.assert_called_once_with(
            "cursor",
            "handoff",
            ticket_id=71,
            summary="Builder handoff",
        )

    def test_hook_tests_do_not_write_real_inbox_files(self) -> None:
        inbox = ROOT / ".crowley" / "inbox"
        before = {path.name for path in inbox.glob("*probe*")} if inbox.is_dir() else set()
        handoff = mock.Mock()
        handoff.write_text = mock.Mock()
        handoff.relative_to.return_value = Path(".crowley/inbox/cursor_note_probe.md")
        with (
            mock.patch.object(curs, "_ensure_bus"),
            mock.patch.object(curs, "INBOX", Path("/tmp/crowley-test-inbox")),
            mock.patch.object(curs, "_run", return_value=mock.Mock(returncode=0)),
            mock.patch.object(curs, "_latest_handoff", return_value=handoff),
            mock.patch.object(curs, "_ingest_and_verify", return_value=True),
            mock.patch.object(asl, "clear_session_marker"),
            mock.patch.object(asl, "post_activity_pulse"),
        ):
            curs.note("Isolation probe")
        after = {path.name for path in inbox.glob("*probe*")} if inbox.is_dir() else set()
        self.assertEqual(before, after)


class CodexSyncPulseHookTests(unittest.TestCase):
    def test_before_posts_session_start(self) -> None:
        sync = {"agent": "codex", "state": {}, "bus_health": {"version": "3.9.10"}}
        with (
            mock.patch.object(cs, "_run"),
            mock.patch.object(asl, "fetch_json", return_value=(sync, None)),
            mock.patch.object(cs, "_print_agent_sync"),
            mock.patch.object(asl, "post_activity_pulse") as pulse,
        ):
            self.assertEqual(cs.before(), 0)
        pulse.assert_called_once_with("codex", "session_start")

    def test_create_tickets_posts_minted_pulse(self) -> None:
        packet = {
            "objective": "V3.9.11 Live Wire probe",
            "tickets": [
                {
                    "title": "Probe ticket one",
                    "description": "desc",
                    "assignee": "cursor",
                    "priority": 1,
                    "acceptance": ["ok"],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            with (
                mock.patch.object(cs, "_run"),
                mock.patch.object(cs, "validate_ticket_packet", return_value=[]),
                mock.patch.object(asl, "create_ticket_api", return_value=(88, None)),
                mock.patch.object(asl, "post_activity_pulse") as pulse,
            ):
                self.assertEqual(cs.create_tickets_file(str(path)), 0)
        pulse.assert_called_once()
        self.assertEqual(pulse.call_args.args[0], "codex")
        self.assertEqual(pulse.call_args.args[1], "minted")
        self.assertIn("Minted 1 ticket(s)", pulse.call_args.kwargs["summary"])
        self.assertIn("Live Wire probe", pulse.call_args.kwargs["summary"])


if __name__ == "__main__":
    unittest.main()
