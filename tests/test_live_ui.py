#!/usr/bin/env python3
"""Live UI sync tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


class PhaseProgressTests(unittest.TestCase):
    def test_parse_phase_fraction(self) -> None:
        p = crowley.parse_phase_progress("Phase 1/3 — Live UI sync")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p["current"], 1)
        self.assertEqual(p["total"], 3)

    def test_parse_phase_of(self) -> None:
        p = crowley.parse_phase_progress("V3.7 Phase 2 of 6")
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p["current"], 2)
        self.assertEqual(p["total"], 6)

    def test_no_progress_for_plain_phase(self) -> None:
        self.assertIsNone(crowley.parse_phase_progress("V3.7.2 Knowledge Files"))


class WorldDashboardTests(IsolatedDbTestCase):
    def test_dashboard_includes_filesystem_truth(self) -> None:
        dash = crowley.build_world_dashboard()
        self.assertIn("filesystem", dash)
        self.assertIn("agent_activity", dash)
        fs = dash["filesystem"]
        self.assertEqual(fs["authority"], "filesystem")
        self.assertEqual(fs["version"], crowley.CROWLEY_VERSION)
        self.assertIn("project_files", dash)

    def test_dashboard_includes_panels(self) -> None:
        dash = crowley.build_world_dashboard()
        self.assertIsNotNone(dash.get("project"))
        self.assertIn("tasks", dash)
        self.assertIn("loops", dash)
        self.assertIn("memory_items", dash)
        self.assertIn("counts", dash)
        self.assertIn("agent_feed", dash["counts"])
        self.assertIn("synced_at", dash)
        self.assertEqual(dash["version"], crowley.CROWLEY_VERSION)

    def test_dashboard_agent_feed_uses_recent_activity(self) -> None:
        dash = crowley.build_world_dashboard()
        activity = dash.get("agent_activity")
        self.assertIsInstance(activity, dict)
        recent = activity.get("recent") if isinstance(activity, dict) else []
        assert isinstance(recent, list)
        self.assertEqual(dash["counts"]["agent_feed"], len(recent))

    def test_dashboard_includes_recent_changes_feed(self) -> None:
        dash = crowley.build_world_dashboard()
        self.assertIn("recent_changes", dash)
        self.assertIsInstance(dash["recent_changes"], list)
        self.assertIn("recent_changes", dash["counts"])

    def test_ui_contains_what_changed_feed(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('data-tab="changes"', html)
        self.assertIn('id="panel-changes"', html)
        self.assertIn("renderChangesPanel", js)
        self.assertIn("recent_changes", js)
        self.assertIn("changes:", js)
        for token in (".change-row", ".change-kind-handoff", ".change-kind-ticket"):
            self.assertIn(token, css)

    def test_ui_contains_agent_feed_tab(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-tab="agent_feed"', html)
        self.assertIn('id="panel-agent-feed"', html)
        self.assertIn("renderAgentFeedPanel", js)
        self.assertIn("agent_feed:", js)

    def test_ui_contains_ticket_detail_view(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="ticket-detail"', html)
        self.assertIn("renderTicketDetail", js)
        self.assertIn("loadTicketDetail", js)
        self.assertIn("ticketStatusClass", js)
        self.assertIn("linked_handoff", js)
        self.assertIn("linked_ticket_ids", js)
        self.assertIn("has-detail", js)

    def test_ui_contains_work_board_panel_notes(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("panel-role-note", html)
        self.assertIn("Agent work board", html)
        self.assertIn("not the Codex/Cursor work board", html)
        self.assertIn("not assigned agent work", html)
        self.assertIn("Agent work board", js)
        self.assertIn("not the agent board", js)

    def test_onboarding_docs_locked_for_v395(self) -> None:
        where = (ROOT / "docs" / "WHERE_WE_ARE.md").read_text(encoding="utf-8")
        versions = (ROOT / "VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn('CROWLEY_VERSION = "3.9.5"', where)
        self.assertIn("V3.9.5 Conversation + Model Behavior", versions)
        self.assertIn("shipped", versions.lower())
        self.assertTrue((ROOT / "docs" / "V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md").is_file())
        self.assertIn("Shipped", (ROOT / "docs" / "V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md").read_text(encoding="utf-8"))

    def test_ui_contains_panel_state_helpers(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        for token in (
            "renderPanelState",
            "panel-state-loading",
            "panel-state-error",
            'renderPanelState(el, "empty"',
            "Loading chat…",
            "Could not reach Crowley",
            "No agent handoffs yet.",
            "Memory unavailable",
        ):
            self.assertIn(token, js)
        for token in (".panel-state-loading", ".panel-state-error", ".panel-state-empty"):
            self.assertIn(token, css)

    def test_ui_contains_streaming_polish_helpers(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        for token in (
            "scheduleStreamingUpdate",
            "flushStreamingUpdate",
            "finalizeStreamingMessage",
            "abortStreamingMessage",
            'setAttribute("aria-busy"',
            "is-streaming",
            "chatAutoscroll",
            "isChatNearBottom",
        ):
            self.assertIn(token, js)
        for token in (
            ".message.streaming .message-label::after",
            ".message.streaming .message-body.prose.is-streaming::after",
            "stream-caret",
        ):
            self.assertIn(token, css)

    def test_ui_contains_navigation_flow_helpers(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        for token in (
            "saveWorkspaceNav",
            "restoreWorkspaceNav",
            "syncSelectedTicketDetail",
            "fingerprintTickets",
            "renderPanelListIfChanged",
            "panelListNeedsRefresh",
            "delete el.dataset.panelFingerprint",
            "crowley.workspace.nav",
            "ticketDetailRequestId",
        ):
            self.assertIn(token, js)
        self.assertIn("flex-wrap: wrap", css)
        self.assertIn(".ticket-detail-meta", css)

    def test_ui_contains_livability_pass_styles(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("loadMessages();", js)
        self.assertIn("if (streaming) return;", js)
        self.assertIn("if (refreshBtn) refreshBtn.disabled = busy;", js)
        self.assertIn("Refresh context panels and chat history", html)
        self.assertIn("Raw agent handoff timeline", html)
        for token in (
            "overflow-wrap: anywhere",
            "-webkit-line-clamp: 2",
            ".panel-list li:has(.agent-feed-row)",
            ".panel-list li:has(.change-row)",
            ".panel-list li:has(.memory-badge)",
            "max-height: 8.5rem",
        ):
            self.assertIn(token, css)


if __name__ == "__main__":
    unittest.main()
