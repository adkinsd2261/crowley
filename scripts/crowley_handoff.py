#!/usr/bin/env python3
"""Generate structured handoff markdown into .crowley/inbox (V3.7 Phase 5)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / ".crowley" / "inbox"

SOURCES = frozenset({"cursor", "chatgpt", "codex", "manual"})
HANDOFF_TYPES = frozenset({
    "builder_handoff",
    "architect_handoff",
    "session_summary",
    "project_update",
    "qa_result",
    "note",
})

MAX_DIFF_CHARS = 12_000


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _type_filename_token(handoff_type: str) -> str:
    mapping = {
        "builder_handoff": "builder",
        "architect_handoff": "architect",
        "session_summary": "session",
        "project_update": "project",
        "qa_result": "qa",
        "note": "note",
    }
    return mapping.get(handoff_type, "session")


def build_filename(source: str, handoff_type: str) -> str:
    ts = _timestamp()
    if source == "manual" and handoff_type == "session_summary":
        return f"manual_handoff_{ts}.md"
    token = _type_filename_token(handoff_type)
    return f"{source}_{token}_handoff_{ts}.md"


def _run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_section(include_diff: bool) -> str:
    lines: list[str] = []

    status = _run_git(["status", "--short"])
    if status:
        lines.append("### Git status")
        lines.append("")
        lines.append("```")
        lines.append(status)
        lines.append("```")
    else:
        lines.append("_Git status unavailable or clean._")

    changed = _run_git(["diff", "--name-only"])
    if changed:
        lines.append("")
        lines.append("### Changed files")
        lines.append("")
        for path in changed.splitlines():
            if path.strip():
                lines.append(f"- {path.strip()}")
    elif status:
        lines.append("")
        lines.append("_No unstaged diff file list (see status above)._")

    if include_diff:
        diff = _run_git(["diff"])
        if diff:
            if len(diff) > MAX_DIFF_CHARS:
                diff = diff[: MAX_DIFF_CHARS - 3] + "..."
            lines.append("")
            lines.append("### Git diff")
            lines.append("")
            lines.append("```diff")
            lines.append(diff)
            lines.append("```")

    return "\n".join(lines)


def build_template(
    *,
    source: str,
    handoff_type: str,
    project: str,
    from_git: bool,
    include_diff: bool,
) -> str:
    project_label = project.strip().capitalize() if project else "Crowley"
    lines = [
        "# Crowley Handoff",
        "",
        f"Source: {source}",
        f"Type: {handoff_type}",
        f"Project: {project_label}",
        "",
        "## Summary",
        "",
        "",
        "## What Changed",
        "",
        "",
        "## Files Changed",
        "",
    ]

    if from_git:
        lines.append(_git_section(include_diff))
    else:
        lines.append("")

    lines.extend([
        "",
        "## Decisions",
        "",
        "",
        "## Lessons",
        "",
        "",
        "## State Changed",
        "",
        "",
        "## QA Results",
        "",
        "",
        "## Known Issues",
        "",
        "",
        "## Open Loops",
        "",
        "",
        "## Next Action",
        "",
        "",
        "## Do Not Build",
        "",
        "",
    ])
    return "\n".join(lines)


def write_handoff(
    *,
    source: str,
    handoff_type: str,
    project: str,
    from_git: bool,
    include_diff: bool,
) -> Path:
    INBOX.mkdir(parents=True, exist_ok=True)
    filename = build_filename(source, handoff_type)
    path = INBOX / filename
    content = build_template(
        source=source,
        handoff_type=handoff_type,
        project=project,
        from_git=from_git,
        include_diff=include_diff,
    )
    path.write_text(content, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write a Crowley handoff template to .crowley/inbox/."
    )
    parser.add_argument(
        "--source",
        choices=sorted(SOURCES),
        default="manual",
        help="Handoff source label (default: manual)",
    )
    parser.add_argument(
        "--type",
        dest="handoff_type",
        choices=sorted(HANDOFF_TYPES),
        default="session_summary",
        help="Handoff type (default: session_summary)",
    )
    parser.add_argument(
        "--project",
        default="crowley",
        help="Project slug (default: crowley)",
    )
    parser.add_argument(
        "--from-git",
        action="store_true",
        help="Include git status and changed file list under Files Changed",
    )
    parser.add_argument(
        "--include-diff",
        action="store_true",
        help="Include git diff output (requires --from-git; capped)",
    )
    args = parser.parse_args()

    if args.include_diff and not args.from_git:
        print("crowley_handoff: --include-diff requires --from-git", file=sys.stderr)
        raise SystemExit(2)

    path = write_handoff(
        source=args.source,
        handoff_type=args.handoff_type,
        project=args.project,
        from_git=args.from_git,
        include_diff=args.include_diff,
    )
    print(f"Wrote handoff template: {path}")


if __name__ == "__main__":
    main()
