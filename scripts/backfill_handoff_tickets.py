#!/usr/bin/env python3
"""Backfill durable tickets from recent handoffs (#131)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import handoff_ticket_bridge  # noqa: E402


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    report = handoff_ticket_bridge.backfill_handoff_tickets(limit=limit)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
