#!/usr/bin/env python3
"""Import structured portable terminal writeback (V3.9.12 #79)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


def _read_input(path: Path | None) -> str:
    if path is None or str(path) == "-":
        if sys.stdin.isatty():
            print(
                "Reading writeback from stdin (paste JSON or fenced block, then Ctrl-D)...",
                file=sys.stderr,
            )
        return sys.stdin.read()
    if not path.is_file():
        raise FileNotFoundError(f"writeback file not found: {path}")
    return path.read_text(encoding="utf-8")


def _format_report(result: dict[str, object]) -> str:
    if result.get("status") != "ok":
        lines = ["Import failed:"]
        for err in result.get("errors") or []:
            lines.append(f"  - {err}")
        return "\n".join(lines)

    lines = ["Portable terminal writeback imported."]
    session_id = result.get("session_receipt_id")
    lines.append(f"Session receipt: memory_item #{session_id}")

    spark_ids = result.get("spark_ids") or []
    lines.append(f"Saved sparks: {len(spark_ids)}")
    for spark_id in spark_ids:
        lines.append(f"  - memory_item #{spark_id}")

    rejected = result.get("rejected_sparks") or []
    lines.append(f"Rejected sparks: {len(rejected)}")
    for item in rejected:
        lines.append(f"  - {item}")

    skipped = result.get("skipped_do_not_save") or []
    lines.append(f"Skipped do_not_save: {len(skipped)}")
    for item in skipped:
        lines.append(f"  - {item}")

    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        surface = metadata.get("surface")
        model = metadata.get("model")
        provider = metadata.get("provider")
        if surface or model or provider:
            lines.append(
                "Metadata: "
                + ", ".join(
                    part
                    for part in (
                        f"surface={surface}" if surface else None,
                        f"model={model}" if model else None,
                        f"provider={provider}" if provider else None,
                    )
                    if part
                )
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import portable terminal writeback JSON from a file or stdin. "
            "Use scripts/export_portable_packet.py to export a paste-ready packet first."
        )
    )
    parser.add_argument(
        "writeback",
        nargs="?",
        type=Path,
        default=None,
        help="Writeback file path, or omit to read stdin (use '-' explicitly for stdin)",
    )
    parser.add_argument(
        "--project",
        default="crowley",
        help="Project slug (default: crowley)",
    )
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Validate writeback without saving to memory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON result instead of human report",
    )
    args = parser.parse_args()

    try:
        raw = _read_input(args.writeback)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    trimmed = raw.strip()
    if not trimmed:
        print("Writeback input is empty.", file=sys.stderr)
        return 1

    if args.parse_only:
        parsed = crowley.parse_terminal_writeback(raw)
        if args.json:
            payload = {
                "ok": parsed.ok,
                "errors": parsed.errors,
                "writeback": parsed.writeback,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        elif not parsed.ok:
            print("Validation failed:", file=sys.stderr)
            for err in parsed.errors:
                print(f"  - {err}", file=sys.stderr)
        else:
            print("Writeback is valid (parse-only; nothing saved).")
        return 0 if parsed.ok else 1

    try:
        result = crowley.ingest_terminal_writeback(raw, project=args.project)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        sys.stdout.write(json.dumps(result, indent=2) + "\n")
    else:
        report = _format_report(result)
        stream = sys.stdout if result.get("status") == "ok" else sys.stderr
        stream.write(report + "\n")

    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
