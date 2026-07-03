#!/usr/bin/env python3
"""V3.9.11 #74 — compose live wire UI."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


def resolve_node_binary() -> tuple[str | None, str]:
    """Resolve node for app.js --check; honor NODE_BINARY env override."""
    override = os.environ.get("NODE_BINARY", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return str(path), ""
        found = shutil.which(override)
        if found:
            return found, ""
        return (
            None,
            f"NODE_BINARY={override!r} is not an executable node binary",
        )
    found = shutil.which("node")
    if found:
        return found, ""
    return (
        None,
        "node not found on PATH; install Node.js or set NODE_BINARY to run app.js syntax check",
    )


_NODE_BINARY, _NODE_SKIP_REASON = resolve_node_binary()


class UiLiveWireTests(IsolatedDbTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.conn = crowley.connect_db()
        self.project_id = crowley._active_project_id(self.conn)
        assert self.project_id is not None

    def tearDown(self) -> None:
        self.conn.close()
        super().tearDown()

    def test_static_assets_include_live_wire_compose_ui(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="activity-wire"', html)
        self.assertIn('id="activity-wire-lines"', html)
        self.assertIn('id="compose-live-panel"', html)
        self.assertIn('id="live-wire-beacon"', html)
        self.assertIn('id="current-objective"', html)
        self.assertIn("In the air", html)
        self.assertIn("live-wire-banner", html)
        self.assertIn("live-wire-ticker", html)
        self.assertIn("renderActivityWire", js)
        self.assertIn("buildTickerQueue", js)
        self.assertIn("pulseLiveWirePanel", js)
        self.assertIn("ACTIVITY_WIRE_ROTATE_MS", js)
        self.assertIn("startActivityWireRotation", js)
        self.assertIn("stopActivityWireRotation", js)
        self.assertIn("compose-live-panel", css)
        self.assertIn("live-wire-beacon", css)
        self.assertIn("ticker-enter", css)
        self.assertIn("activity-wire-dot", css)
        self.assertIn("agent-source-cursor", css)

    @unittest.skipUnless(_NODE_BINARY, _NODE_SKIP_REASON)
    def test_app_js_syntax_check(self) -> None:
        assert _NODE_BINARY is not None
        result = subprocess.run(
            [_NODE_BINARY, "--check", str(ROOT / "static" / "app.js")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_world_dashboard_activity_wire_feeds_compose_contract(self) -> None:
        crowley.record_activity_pulse(
            "cursor",
            "claimed",
            project_id=self.project_id,
            ticket_id=74,
            summary="Compose live wire UI probe",
        )
        crowley.update_project_state_field(
            self.project_id,
            "focus",
            "V3.9.11 compose live wire probe",
            updated_by="test",
        )
        dash = crowley.build_world_dashboard()
        wire = dash.get("activity_wire")
        assert isinstance(wire, dict)
        self.assertIn("pinned_focus", wire)
        self.assertIn("items", wire)
        items = wire.get("items")
        assert isinstance(items, list)
        self.assertGreaterEqual(len(items), 1)
        sample = items[0]
        assert isinstance(sample, dict)
        for key in ("id", "kind", "agent", "verb", "line", "created_at", "is_ambient"):
            self.assertIn(key, sample)


if __name__ == "__main__":
    unittest.main()
