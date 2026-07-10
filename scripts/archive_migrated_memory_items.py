#!/usr/bin/env python3
"""V4.3.2 T4 — demote/archive legacy memory_items (no DELETE).

Dry-run required before apply (or --reviewed). Protects pinned/canon/ticket-linked
receipts unless represented by active/pinned sparks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402
import memory_spark_migration as msm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--scan-limit", type=int, default=None)
    parser.add_argument("--reviewed", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    if args.apply:
        if args.limit is None:
            print("ERROR: --apply requires explicit --limit", file=sys.stderr)
            return 2
        if args.limit <= 0:
            print("ERROR: --limit must be positive", file=sys.stderr)
            return 2

    artifact = ROOT / "docs" / "artifacts" / msm.ARCHIVE_DRY_RUN_ARTIFACT
    conn = crowley.connect_db()
    try:
        if args.apply:
            try:
                report = msm.apply_memory_demotion(
                    conn,
                    limit=int(args.limit),
                    reviewed=args.reviewed,
                    artifact_path=artifact,
                )
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            conn.commit()
        else:
            report = msm.review_memory_demotion(
                conn,
                limit=args.limit,
                scan_limit=args.scan_limit,
            )
    finally:
        conn.close()

    text = json.dumps(report, indent=2)
    print(text)
    if args.write:
        art = ROOT / "docs" / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        out = art / (
            "memory_items_demotion_apply.json"
            if args.apply
            else msm.ARCHIVE_DRY_RUN_ARTIFACT
        )
        out.write_text(text + "\n", encoding="utf-8")
        print(f"\n# wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
