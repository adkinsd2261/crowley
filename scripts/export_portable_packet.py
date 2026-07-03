#!/usr/bin/env python3
"""Export a paste-ready Crowley portable context packet (V3.9.12 #76)."""

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
        description="Export a medium Crowley packet for manual paste into ChatGPT or another surface."
    )
    parser.add_argument(
        "--surface",
        default="chatgpt",
        help="Target reasoning surface label (default: chatgpt)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug override (default: active project)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured packet JSON instead of markdown",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Write output to file instead of stdout",
    )
    args = parser.parse_args()

    packet = crowley.build_portable_context_packet(
        args.surface, project_slug=args.project
    )
    if args.json:
        payload = json.dumps(packet, indent=2) + "\n"
    else:
        payload = crowley.render_portable_context_packet_markdown(packet)

    if args.out is not None:
        args.out.write_text(payload, encoding="utf-8")
        print(f"Wrote {args.out} ({len(payload)} chars)", file=sys.stderr)
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
