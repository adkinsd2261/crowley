#!/usr/bin/env python3
"""Reconcile handoff ↔ ticket parity (#151): dry-run audit or apply fixes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import handoff_ticket_bridge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile handoff/ticket parity")
    parser.add_argument("--limit", type=int, default=200, help="Handoffs to check")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fixes (default is dry-run preview)",
    )
    args = parser.parse_args()
    report = handoff_ticket_bridge.reconcile_handoff_ticket_parity(
        limit=args.limit,
        dry_run=not args.apply,
    )
    print(json.dumps(report, indent=2))
    if args.apply and not report.get("parity_ok_after"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
