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
        self.assertIn("changesItemsForDashboard", js)
        self.assertIn("agent_fallback:", js)
        self.assertIn("updateTabBadges(data.counts || {}, data)", js)
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
        self.assertIn("agent work board", html.lower())
        self.assertIn("not the Codex/Cursor work board", html)
        self.assertIn("not assigned agent work", html)
        self.assertIn("Agent work board", js)
        self.assertIn("not the agent board", js)

    def test_onboarding_docs_locked_for_v3915_gpt_toolbelt(self) -> None:
        where = (ROOT / "docs" / "WHERE_WE_ARE.md").read_text(encoding="utf-8")
        versions = (ROOT / "VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn('CROWLEY_VERSION = "3.9.15"', where)
        self.assertIn("V3.9.15", versions)
        self.assertIn("GPT Toolbelt", versions)
        self.assertTrue((ROOT / "docs" / "V3.9.15_GPT_TOOLBELT.md").is_file())
        self.assertTrue((ROOT / "docs" / "CHATGPT_ACTIONS_API.md").is_file())
        self.assertTrue((ROOT / "openapi-chatgpt.json").is_file())
        actions_doc = (ROOT / "docs" / "CHATGPT_ACTIONS_API.md").read_text(encoding="utf-8")
        self.assertIn("CROWLEY_ACTION_KEY", actions_doc)
        self.assertIn("/api/actions/", actions_doc)

    def test_onboarding_docs_locked_for_v3912_portable_terminal(self) -> None:
        where = (ROOT / "docs" / "WHERE_WE_ARE.md").read_text(encoding="utf-8")
        versions = (ROOT / "VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn("V3.9.12", where)
        self.assertIn("persistent context layer", where)
        self.assertIn("V3.9.12", versions)
        self.assertIn("Portable Context Terminal", versions)
        self.assertIn("shipped", versions.lower())
        self.assertTrue((ROOT / "docs" / "V3.9.12_PORTABLE_CONTEXT_TERMINAL.md").is_file())
        release_doc = (ROOT / "docs" / "V3.9.12_PORTABLE_CONTEXT_TERMINAL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Shipped", release_doc)
        self.assertIn("V4.0 owns Spark Lanes", release_doc)
        self.assertIn("staged", release_doc.lower())

    def test_onboarding_docs_locked_for_v3911_live_wire(self) -> None:
        versions = (ROOT / "VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn("V3.9.11", versions)
        self.assertIn("Live Wire", versions)
        self.assertTrue((ROOT / "docs" / "V3.9.11_LIVE_WIRE.md").is_file())

    def test_onboarding_docs_locked_for_v3910_task_frame(self) -> None:
        versions = (ROOT / "VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn("V3.9.10", versions)
        self.assertIn("Task-Frame Context", versions)
        self.assertTrue((ROOT / "docs" / "V3.9.10_TASK_FRAME_CONTEXT.md").is_file())

    def test_onboarding_docs_locked_for_v395(self) -> None:
        where = (ROOT / "docs" / "WHERE_WE_ARE.md").read_text(encoding="utf-8")
        versions = (ROOT / "VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn("V3.9.5", where)
        self.assertIn("Shipped", where)
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
        self.assertIn("flex-wrap: nowrap", css)
        self.assertIn(".ticket-detail-meta", css)

    def test_ui_contains_livability_pass_styles(self) -> None:
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("loadMessages();", js)
        self.assertIn("if (streaming) return;", js)
        self.assertIn("if (refreshBtn) refreshBtn.disabled = busy;", js)
        self.assertIn("Refresh context panels and chat history", html)
        self.assertIn("Handoff timeline", html)
        for token in (
            "overflow-wrap: anywhere",
            "-webkit-line-clamp: 2",
            ".panel-list li:has(.agent-feed-row)",
            ".panel-list li:has(.change-row)",
            ".panel-list li:has(.memory-badge)",
            "--drawer-panel-max-h",
        ):
            self.assertIn(token, css)

    def test_ui_contains_project_tab(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('data-tab="project"', html)
        self.assertIn('data-label="Project"', html)
        self.assertIn('id="panel-project"', html)
        project_pos = html.index('data-tab="project"')
        tickets_pos = html.index('data-tab="tickets"')
        self.assertLess(project_pos, tickets_pos)
        for token in (
            "renderProjectPanel",
            "projectPanelFingerprint",
            "project-state-grid",
            "project-counts",
            "project-panel-version",
            'activeContextTab = "project"',
            "Next action",
            "What changed",
            "release_label",
        ):
            self.assertIn(token, js)
        for token in (
            ".project-state-grid",
            ".project-counts",
            ".project-panel-version",
            "@media (max-width: 520px)",
            ".project-state-grid div",
            "display: block",
        ):
            self.assertIn(token, css)

            self.assertIn(token, css)

    def test_ui_intelligence_drawer_polish(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        for token in (
            "--workspace-glass",
            "--drawer-body-max-h",
            "--drawer-panel-max-h",
            ".context-drawer:not(.is-collapsed)",
            "scroll-snap-type: x proximity",
            ".context-tab.is-active",
            "box-shadow: 0 0 0 1px var(--accent-line)",
            ".project-panel-body",
            "backdrop-filter: blur(12px)",
            ".context-panel .panel-list li",
        ):
            self.assertIn(token, css)

    def test_ui_cinematic_workspace_without_inspector(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('class="inspector"', html)
        self.assertNotIn("world-project", html)
        self.assertNotIn("world-state", html)
        self.assertIn('class="workspace"', html)
        self.assertIn('class="workspace-pane"', html)
        self.assertIn('id="run-diagnostics"', html)
        diagnostics_pos = html.index('id="run-diagnostics"')
        project_panel_pos = html.index('data-panel="project"')
        self.assertLess(project_panel_pos, diagnostics_pos)
        for token in (
            "radial-gradient",
            "backdrop-filter",
            "--entry-width: 46rem",
            ".workspace::before",
            "linear-gradient(to top",
        ):
            self.assertIn(token, css)
        self.assertNotIn("worldProjectEl", js)
        self.assertNotIn("renderWorldState", js)

    def test_ui_chat_stream_readability(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        for token in (
            ".message.user",
            ".message-expand",
            "border-radius: 999px",
            ".message.diagnostics .message-body.prose",
            "box-shadow: inset 3px 0 0 var(--accent-soft)",
            "Show full response",
            "attachMessageExpand",
            "renderDiagnosticsBlock",
        ):
            blob = css if token.startswith(".") or token.startswith("border") or token.startswith("box") else js
            self.assertIn(token, blob)

    def test_ui_workspace_cohesion_tokens(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        for token in (
            "--workspace-header-bg",
            "--workspace-label-size",
            "--workspace-label-tracking",
            "var(--workspace-header-bg)",
            "var(--workspace-label-size)",
        ):
            self.assertIn(token, css)

    def test_ui_tasks_tab_demoted_after_loops(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        loops_pos = html.index('data-tab="loops"')
        tasks_pos = html.index('data-tab="tasks"')
        self.assertLess(loops_pos, tasks_pos)
        self.assertIn("context-tab-legacy", html)
        self.assertIn("Tickets = agent work board", html)

    def test_ui_narrow_viewport_overflow_guards(self) -> None:
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('content="width=device-width, initial-scale=1.0"', html)
        for token in (
            "overflow-x: clip",
            "grid-template-columns: minmax(0, 1fr) auto",
            ".workspace-pane",
            "min-width: 0",
            ".workspace-pane",
            ".context-drawer",
            "max-width: 100%",
            ".context-tabs",
            "width: 100%",
            "max-width: var(--entry-width)",
            "@media (max-width: 840px)",
            "--entry-width: 100%",
            "@media (max-width: 520px)",
            ".context-summary",
            "display: none",
            ".message-body.prose .code-block",
            "max-width: 100%",
        ):
            self.assertIn(token, css)


if __name__ == "__main__":
    unittest.main()
