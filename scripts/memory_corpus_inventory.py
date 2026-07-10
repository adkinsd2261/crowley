#!/usr/bin/env python3
"""V4.3.1 T1 — read-only inventory of memory_items / sparks for corpus migration.

Writes JSON to stdout and optionally docs/artifacts/memory_corpus_inventory.json.
Never mutates the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory_spark_migration as msm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Also write docs/artifacts/memory_corpus_inventory.json",
    )
    args = parser.parse_args()
    report = msm.build_inventory()
    text = json.dumps(report, indent=2)
    print(text)
    if args.write:
        out = ROOT / "docs" / "artifacts" / "memory_corpus_inventory.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"\n# wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
