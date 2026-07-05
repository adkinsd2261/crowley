#!/usr/bin/env python3
"""Review staged portable writeback sparks and optionally promote accepted rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze ChatGPT/portable writeback sessions, sort them, and optionally "
            "promote accepted staged sparks to active memory."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Promote accepted sparks and write the acceptance report",
    )
    parser.add_argument(
        "--reviewer",
        default="operator",
        help="Reviewer label stored in promotion metadata",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full acceptance report as JSON",
    )
    args = parser.parse_args()

    report = crowley.build_portable_writeback_acceptance_report(
        apply=args.apply,
        reviewer=args.reviewer,
    )
    report_path = crowley.write_portable_writeback_acceptance_report(report)

    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    else:
        counts = report.get("counts") or {}
        mode = "applied" if args.apply else "dry-run"
        print(f"Portable writeback acceptance report ({mode})")
        print(f"Report: {report_path}")
        print(f"Sessions: {counts.get('sessions', 0)}")
        print(f"Accepted: {counts.get('accepted', 0)}")
        print(f"Rejected: {counts.get('rejected', 0)}")
        print(f"Deduped: {counts.get('deduped', 0)}")
        print(
            "Promoted session metadata: "
            f"{counts.get('promoted_session_metadata', 0)}"
        )
        for session in report.get("sessions") or []:
            if not isinstance(session, dict):
                continue
            print(
                f"  #{session.get('session_receipt_id')} "
                f"[{session.get('classification')}] "
                f"{session.get('created_at')} — "
                f"{session.get('summary')}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
