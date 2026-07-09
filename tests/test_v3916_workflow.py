#!/usr/bin/env python3
"""V3.9.16 workflow enforcement tests (#101–#111)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import actions_tool_registry as registry  # noqa: E402
import app as crowley_app  # noqa: E402
import crowley  # noqa: E402
import workflow  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ACTIONS_KEY = "test-v3916-secret"
AUTH = {"Authorization": f"Bearer {ACTIONS_KEY}"}
DOC = ROOT / "docs" / "V3.9.16_WORKFLOW_ENFORCEMENT.md"
CODEX_TEMPLATE = ROOT / "tickets" / "codex_grade_ticket.template.json"
RELEASE_JSON = ROOT / "tickets" / "v3.9.16_workflow_enforcement.json"


class WorkflowModuleTests(unittest.TestCase):
    def test_boot_gate_blocks_then_allows(self) -> None:
        session = "test-boot-gate"
        workflow.record_boot_sync(session)
        allowed, _ = workflow.check_boot_gate(session, "memory.get")
        self.assertTrue(allowed)
        fresh = "fresh-session-xyz"
        blocked, message = workflow.check_boot_gate(fresh, "memory.get")
        self.assertFalse(blocked)
        self.assertIn("boot_required", message or "")
        allowed2, _ = workflow.check_boot_gate(fresh, "agent.sync")
        self.assertTrue(allowed2)
        allowed3, _ = workflow.check_boot_gate(fresh, "ticket.list")
        self.assertTrue(allowed3)

    def test_core_tool_tiers(self) -> None:
        self.assertEqual(workflow.tool_tier("agent.sync"), "core")
        self.assertEqual(workflow.tool_tier("ticket.create"), "core")
        self.assertEqual(workflow.tool_tier("github.file"), "secondary")
        self.assertEqual(workflow.tool_tier("inspect.recent_ingests"), "secondary")

    def test_low_signal_note_rejection(self) -> None:
        self.assertTrue(workflow.is_low_signal_note("test note"))
        self.assertTrue(workflow.is_low_signal_note("ok"))
        self.assertFalse(
            workflow.is_low_signal_note(
                "Decision: enforce agent.sync boot before reasoning in fresh ChatGPT sessions."
            )
        )


class WorkflowActionsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prior = os.environ.get("CROWLEY_ACTION_KEY")
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY
        workflow._session_boot.clear()

    def tearDown(self) -> None:
        workflow._session_boot.clear()
        if self._prior is None:
            os.environ.pop("CROWLEY_ACTION_KEY", None)
        else:
            os.environ["CROWLEY_ACTION_KEY"] = self._prior

    def test_catalog_includes_workflow_and_tiers(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/actions/catalog", headers=AUTH)
        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertIn("workflow", payload)
        tools = payload["tools"]
        agent_sync = next(item for item in tools if item["name"] == "agent.sync")
        self.assertEqual(agent_sync["tier"], "core")
        github = next(item for item in tools if item["name"] == "github.file")
        self.assertEqual(github["tier"], "secondary")

    def test_read_blocked_without_boot(self) -> None:
        headers = {**AUTH, "X-Crowley-Session": "blocked-session"}
        with TestClient(crowley_app.app) as client:
            res = client.post(
                "/api/actions/read",
                headers=headers,
                json={"tool": "ticket.list", "args": {}},
            )
        self.assertEqual(res.status_code, 428)
        self.assertEqual(res.json()["error"], "boot_required")

    def test_agent_sync_satisfies_boot(self) -> None:
        headers = {**AUTH, "X-Crowley-Session": "boot-ok-session"}
        with TestClient(crowley_app.app) as client:
            sync = client.post(
                "/api/actions/read",
                headers=headers,
                json={"tool": "agent.sync", "args": {"agent": "chatgpt"}},
            )
            self.assertEqual(sync.status_code, 200)
            self.assertIn("workflow", sync.json())
            follow = client.post(
                "/api/actions/read",
                headers=headers,
                json={"tool": "ticket.list", "args": {}},
            )
        self.assertEqual(follow.status_code, 200)

    def test_note_ingest_rejects_low_signal(self) -> None:
        headers = {**AUTH, "X-Crowley-Session": "note-gate-session"}
        with TestClient(crowley_app.app) as client:
            client.post(
                "/api/actions/read",
                headers=headers,
                json={"tool": "agent.sync", "args": {}},
            )
            res = client.post(
                "/api/actions/write",
                headers=headers,
                json={"tool": "note.ingest", "args": {"content": "test note"}},
            )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"], "low_signal_note")


class WorkflowCrowleyEngineTests(IsolatedDbTestCase):
    def test_agent_sync_includes_boot_sequence(self) -> None:
        sync = crowley.build_agent_sync_bundle(agent="cursor", limit=5)
        self.assertIn("boot_sequence", sync)
        self.assertEqual(sync["boot_sequence"]["required_first_tool"], "agent.sync")

    def test_version_is_current_release(self) -> None:
        self.assertEqual(crowley.CROWLEY_VERSION, "4.1.0")

    def test_fresh_chat_stability_keys(self) -> None:
        """#105 — structural keys stable across repeated sync calls."""
        keys_runs: list[frozenset[str]] = []
        for _ in range(20):
            sync = crowley.build_agent_sync_bundle(agent="chatgpt", limit=10)
            keys_runs.append(frozenset(sync.keys()))
        baseline = keys_runs[0]
        matches = sum(1 for keys in keys_runs if keys == baseline)
        self.assertGreaterEqual(matches / len(keys_runs), 0.95)

    def test_prompt_orders_activity_before_world_state(self) -> None:
        messages = crowley.build_prompt("what changed since last handoff?")
        system = messages[0]["content"]
        activity_idx = system.find("Agent activity")
        world_idx = system.find("Live DB state")
        if activity_idx >= 0 and world_idx >= 0:
            self.assertLess(activity_idx, world_idx)

    def test_ground_truth_prefers_activity_over_memory(self) -> None:
        messages = crowley.build_prompt("what now?")
        system = messages[0]["content"].lower()
        self.assertIn("agent activity beats project_state", system)


class WorkflowDocAndTemplateTests(unittest.TestCase):
    def test_release_doc_exists(self) -> None:
        self.assertTrue(DOC.is_file())

    def test_codex_grade_ticket_template(self) -> None:
        self.assertTrue(CODEX_TEMPLATE.is_file())
        template = json.loads(CODEX_TEMPLATE.read_text(encoding="utf-8"))
        required = {
            "title",
            "assignee",
            "priority",
            "description",
            "acceptance",
            "implementation_steps",
            "files_touched",
            "dependencies",
            "data_flow",
        }
        self.assertTrue(required.issubset(template.keys()))

    def test_v3916_release_json_has_dependency_chain(self) -> None:
        self.assertTrue(RELEASE_JSON.is_file())
        release = json.loads(RELEASE_JSON.read_text(encoding="utf-8"))
        tickets = release["tickets"]
        self.assertGreaterEqual(len(tickets), 10)
        titles = [str(item["title"]) for item in tickets]
        self.assertTrue(any("agent.sync boot" in t.lower() for t in titles))


class CursorHandoffSchemaTests(unittest.TestCase):
    def test_cursor_sync_has_qa_pipeline_args(self) -> None:
        text = (ROOT / "scripts" / "cursor_sync.py").read_text(encoding="utf-8")
        self.assertIn("--context-basis", text)
        self.assertIn("--confidence", text)
        self.assertIn("## Context Basis", text)
        self.assertIn("## Build Complete", text)
        self.assertIn("## Approval", text)


if __name__ == "__main__":
    unittest.main()
