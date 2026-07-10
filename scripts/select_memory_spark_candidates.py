#!/usr/bin/env python3
"""V4.3.1/V4.3.2 — deterministic candidate selector + coverage report (dry-run).

Selects valuable active memory_items for migration without extracting yet.
Supports --tier A,B,C and --coverage for V4.3.2 coverage targets.
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
        "--limit",
        type=int,
        default=100,
        help="Max candidates to include in the review report",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=None,
        help="Optional cap on memory_items scanned (default: all)",
    )
    parser.add_argument(
        "--tier",
        type=str,
        default=None,
        help="Comma-separated migrate tiers to include (A,B,C). Default: all.",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Emit coverage targets report instead of candidate list",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write JSON + markdown under docs/artifacts/",
    )
    args = parser.parse_args()
    tiers = _parse_tiers(args.tier)

    conn = crowley.connect_db()
    try:
        if args.coverage:
            report = msm.build_coverage_report(conn)
        else:
            report = msm.select_candidates(
                conn,
                limit=args.limit,
                scan_limit=args.scan_limit,
                tiers=tiers,
            )
    finally:
        conn.close()

    text = json.dumps(report, indent=2)
    print(text)
    if args.write:
        art = ROOT / "docs" / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        if args.coverage:
            json_path = art / "spark_corpus_coverage.json"
            md_path = art / "spark_corpus_coverage.md"
            md = msm.format_coverage_markdown(report)
        else:
            json_path = art / "memory_spark_candidates.json"
            md_path = art / "memory_spark_candidates.md"
            md = msm.format_candidate_markdown(report)
        json_path.write_text(text + "\n", encoding="utf-8")
        md_path.write_text(md, encoding="utf-8")
        print(f"\n# wrote {json_path}", file=sys.stderr)
        print(f"# wrote {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
