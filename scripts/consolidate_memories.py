#!/usr/bin/env python3
"""Run Crowley memory consolidation jobs (V3.6 Phase 4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run memory consolidation jobs")
    parser.add_argument(
        "run_type",
        nargs="?",
        default="all",
        choices=["session", "duplicates", "stale", "daily", "all"],
        help="Consolidation job type (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without writing changes",
    )
    args = parser.parse_args()
    crowley.setup_db()
    try:
        result = crowley.consolidate_memories(args.run_type, dry_run=args.dry_run)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
