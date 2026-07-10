#!/usr/bin/env python3
"""V4.3.1/V4.3.2 — memory_items → sparks extraction (dry-run default; multi-batch apply).

Dry-run proposes validated sparks with lineage. Apply requires --apply, a bounded
--limit, and either a recent dry-run artifact (--write) or --reviewed.
Never deletes or archives memory_items.
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


def _parse_tiers(raw: str | None) -> frozenset[str] | None:
    if not raw:
        return None
    parts = {p.strip().upper() for p in raw.split(",") if p.strip()}
    invalid = parts - msm.MIGRATE_TIERS
    if invalid:
        raise SystemExit(f"Invalid tiers {sorted(invalid)}; use A,B,C")
    return frozenset(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write sparks (requires --limit). Default is dry-run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max candidates per batch (required with --apply; default 50 dry-run)",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=1,
        help="Number of capped batches to run on --apply (default 1)",
    )
    parser.add_argument(
        "--tier",
        type=str,
        default=None,
        help="Comma-separated migrate tiers (A,B,C). Default: all migrate tiers.",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Allow spark_extraction for long rows (default: deterministic/clip)",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default=None,
        help="Optional migration batch id / prefix for lineage_json",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write report under docs/artifacts/",
    )
    parser.add_argument(
        "--allow-promote",
        action="store_true",
        help="Allow deterministic promote-on-apply (default: leave candidate)",
    )
    parser.add_argument(
        "--reviewed",
        action="store_true",
        help="Explicit review flag bypassing dry-run artifact freshness gate",
    )
    args = parser.parse_args()
    tiers = _parse_tiers(args.tier)
    promote_policy = bool(args.allow_promote)

    if args.apply:
        if args.limit is None:
            print(
                "ERROR: --apply requires explicit --limit (small batch only)",
                file=sys.stderr,
            )
            return 2
        if args.limit <= 0:
            print("ERROR: --limit must be positive", file=sys.stderr)
            return 2
        if args.max_batches <= 0:
            print("ERROR: --max-batches must be positive", file=sys.stderr)
            return 2

    limit = args.limit if args.limit is not None else 50
    artifact = msm.dry_run_artifact_path(ROOT)
    conn = crowley.connect_db()
    try:
        if args.apply:
            try:
                report = msm.apply_multi_batch(
                    conn,
                    limit=limit,
                    max_batches=args.max_batches,
                    allow_llm=args.with_llm,
                    batch_id_prefix=args.batch_id,
                    promote_policy=promote_policy,
                    tiers=tiers,
                    reviewed=args.reviewed,
                    artifact_path=artifact,
                )
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 2
            conn.commit()
        else:
            report = msm.dry_run_extract(
                conn,
                limit=limit,
                allow_llm=args.with_llm,
                batch_id=args.batch_id,
                tiers=tiers,
            )
    finally:
        conn.close()

    text = json.dumps(report, indent=2)
    print(text)
    if args.write:
        art = ROOT / "docs" / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        if args.apply:
            out = art / "memory_to_spark_apply_batches.json"
        else:
            out = art / msm.DRY_RUN_ARTIFACT_NAME
        out.write_text(text + "\n", encoding="utf-8")
        print(f"\n# wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
