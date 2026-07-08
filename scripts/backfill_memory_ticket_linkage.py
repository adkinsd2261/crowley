#!/usr/bin/env python3
"""Backfill persisted memory ↔ ticket links."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory_ticket_linkage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill memory ticket links")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist links (default is dry-run preview)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only scan first N memory_items (debug)",
    )
    args = parser.parse_args()
    report = memory_ticket_linkage.backfill_memory_ticket_links(
        dry_run=not args.apply,
        limit=args.limit,
    )
    print(json.dumps(report, indent=2))
    if args.apply and report.get("updated", 0) > 0:
        audit = memory_ticket_linkage.audit_memory_ticket_linkage()
        print(json.dumps({"post_backfill_audit": audit}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
