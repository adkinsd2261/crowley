#!/usr/bin/env python3
"""Audit ticket ↔ memory linkage coverage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402
import memory_ticket_linkage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit memory ↔ ticket linkage")
    parser.add_argument(
        "--project-id",
        type=int,
        default=None,
        help="Limit memory_items to one project (default: all)",
    )
    args = parser.parse_args()
    project_id = args.project_id
    if project_id is None:
        project = crowley.get_active_project()
        if project is not None:
            project_id = int(project["id"])
    report = memory_ticket_linkage.audit_memory_ticket_linkage(project_id=project_id)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
