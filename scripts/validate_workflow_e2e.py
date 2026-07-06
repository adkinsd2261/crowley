#!/usr/bin/env python3
"""V3.9.16 — end-to-end workflow validation (#108)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8765"


def _get(path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    errors: list[str] = []

    try:
        health = _get("/api/health")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"FAIL: bus unreachable — {exc}")
        return 1

    version = str(health.get("version", ""))
    if not version.startswith("3.9.19"):
        errors.append(f"expected version 3.9.19, got {version}")

    sync = _get("/api/agent/sync?agent=cursor&limit=10")
    if sync.get("boot_sequence", {}).get("required_first_tool") != "agent.sync":
        errors.append("agent.sync boot_sequence missing from sync bundle")

    tickets = _get("/api/tickets?status=open&limit=5")
    if "tickets" not in tickets:
        errors.append("tickets API missing tickets key")

    cursor_sync = ROOT / "scripts" / "cursor_sync.py"
    text = cursor_sync.read_text(encoding="utf-8")
    for marker in ("## Context Basis", "## Build Complete", "--confidence"):
        if marker not in text:
            errors.append(f"cursor_sync missing {marker}")

    if errors:
        print("Workflow E2E validation FAILED:")
        for item in errors:
            print(f"  - {item}")
        return 1

    print("Workflow E2E validation OK")
    print(f"  version: {version}")
    print(f"  sync agent: {sync.get('agent')}")
    print(f"  open tickets sample: {len(tickets.get('tickets', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
