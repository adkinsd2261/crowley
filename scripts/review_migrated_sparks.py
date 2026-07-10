#!/usr/bin/env python3
"""V4.3.2 T3 — promotion review for migrated candidate sparks.

Dry-run lists promote/hold with reasons. Apply requires --apply and --limit.
No broad auto-promotion; ticket chatter stays candidate unless --whitelist.
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


def _parse_ids(raw: str | None) -> frozenset[int] | None:
    if not raw:
        return None
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return frozenset(ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--whitelist",
        type=str,
        default=None,
        help="Comma-separated spark ids to force-promote (manual override)",
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    whitelist = _parse_ids(args.whitelist)

    if args.apply:
        if args.limit is None:
            print("ERROR: --apply requires explicit --limit", file=sys.stderr)
            return 2
        if args.limit <= 0:
            print("ERROR: --limit must be positive", file=sys.stderr)
            return 2

    conn = crowley.connect_db()
    try:
        if args.apply:
            try:
                report = msm.apply_promotion_review(
                    conn,
                    limit=int(args.limit),
                    whitelist_ids=whitelist,
                )
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            conn.commit()
        else:
            report = msm.review_migrated_sparks(
                conn,
                limit=args.limit,
                whitelist_ids=whitelist,
            )
    finally:
        conn.close()

    text = json.dumps(report, indent=2)
    print(text)
    if args.write:
        art = ROOT / "docs" / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        name = (
            "spark_promotion_apply.json"
            if args.apply
            else "spark_promotion_review.json"
        )
        out = art / name
        out.write_text(text + "\n", encoding="utf-8")
        print(f"\n# wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
