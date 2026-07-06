#!/usr/bin/env python3
"""Backfill duplicate constraint memories (#163)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory_quality  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplicate constraint memories")
    parser.add_argument("--apply", action="store_true", help="Apply merges (default dry-run)")
    args = parser.parse_args()
    report = memory_quality.backfill_constraint_deduplication(dry_run=not args.apply)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
