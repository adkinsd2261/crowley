"""Tests for shared agent sync helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agent_sync_lib as asl  # noqa: E402


class AgentSyncLibTests(unittest.TestCase):
    def test_event_display_line_no_none_prefix(self) -> None:
        line = asl.event_display_line(
            {
                "source": "cursor",
                "content": "# Crowley Handoff\n\n## Summary\n\n- hello world",
                "created_at": "2026-07-01T20:00:00Z",
            }
        )
        self.assertNotIn("None", line)
        self.assertIn("hello world", line)
        self.assertIn("cursor", line)

    def test_handoff_summary_line_prefers_summary_section(self) -> None:
        content = (
            "# Crowley Handoff\n\n"
            "## Summary\n\n"
            "- picked summary line\n\n"
            "## Next Action\n\n"
            "- later"
        )
        self.assertEqual(asl.handoff_summary_line(content), "picked summary line")


if __name__ == "__main__":
    unittest.main()
