#!/usr/bin/env python3
"""Hardwired Cursor sync hooks for the Crowley project."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_sync_lib as asl  # noqa: E402

ROOT = asl.ROOT
PYTHON = ROOT / "venv" / "bin" / "python3"
INBOX = ROOT / ".crowley" / "inbox"
HEALTH_URL = asl.url("/api/bus/health")
AGENT = "cursor"
DEFAULT_DO_NOT_BUILD = (
    "Do not build direct Cursor-to-Codex communication; Crowley is the only hub."
)


def _python_cmd() -> str:
    return str(PYTHON if PYTHON.exists() else Path(sys.executable))


def _run(args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _git(args: list[str]) -> str:
    try:
        result = _run(["git", *args], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _ensure_bus() -> None:
    script = ROOT / "scripts" / "ensure_crowley_bus.sh"
    if script.is_file():
        _run(["bash", str(script)], timeout=30)


def _print_agent_sync(sync: dict[str, Any]) -> None:
    asl.print_agent_sync_bundle(sync, agent=AGENT)
    asl.print_sync_extras(sync, agent=AGENT)


def session_start() -> int:
    asl.touch_session_marker()
    return 0


def session_end() -> int:
    if asl.session_marker_age_seconds() is None:
        return 0
    if asl.handoff_since_session(AGENT):
        asl.clear_session_marker()
        print("Crowley: handoff logged this session.", file=sys.stderr)
        return 0
    asl.clear_session_marker()
    print(
        "WARNING: Cursor session ended without a builder handoff this session. "
        "Run scripts/cursor_sync.py --after or --note if you shipped work.",
        file=sys.stderr,
    )
    return 0


def before() -> int:
    _ensure_bus()
    sync, error = asl.fetch_json(asl.url("/api/agent/sync", {"agent": AGENT, "limit": 20}))
    if error:
        print(f"WARNING: Crowley agent sync unavailable: {error}", file=sys.stderr)
        return 0
    if sync is None:
        print("WARNING: Crowley agent sync returned no context.", file=sys.stderr)
        return 0
    _print_agent_sync(sync)
    return 0


def _latest_handoff(before_files: set[Path]) -> Path | None:
    files = {path for path in INBOX.glob("cursor_*_handoff_*.md") if path.is_file()}
    created = sorted(files - before_files, key=lambda path: path.stat().st_mtime)
    if created:
        return created[-1]
    all_files = sorted(files, key=lambda path: path.stat().st_mtime)
    return all_files[-1] if all_files else None


def _bullets(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"- {item}" for item in cleaned)


def _section_content(
    *,
    handoff_type: str,
    status: str,
    changed: str,
    summary: str,
    decisions: list[str],
    next_action: str,
    do_not_build: list[str],
    open_loops: list[str],
    qa_results: list[str],
    known_issues: list[str],
) -> str:
    status_text = status or "Git status unavailable or clean."
    changed_lines = [line.strip() for line in changed.splitlines() if line.strip()]
    changed_text = "\n".join(f"- {line}" for line in changed_lines) or "- No changed files reported."
    decisions_text = _bullets(decisions) or "- No new product decisions recorded."
    do_not_build_text = _bullets(do_not_build) or f"- {DEFAULT_DO_NOT_BUILD}"
    open_loops_text = _bullets(open_loops) or "- None recorded."
    known_issues_text = _bullets(known_issues) or "- None recorded."
    qa_default = (
        "- Not run; planning-only handoff."
        if handoff_type == "architect_handoff"
        else "- Not recorded."
    )
    qa_text = _bullets(qa_results) or qa_default

    if handoff_type == "architect_handoff":
        files_section = "## Files Changed\n\n- None; planning-only architect handoff.\n\n"
    else:
        files_section = (
            "## Files Changed\n\n"
            "### Git status\n\n"
            "```\n"
            f"{status_text}\n"
            "```\n\n"
            "### Changed files\n\n"
            f"{changed_text}\n\n"
        )

    what_changed = (
        "Planning handoff for Crowley memory."
        if handoff_type == "architect_handoff"
        else "Builder handoff for Crowley memory."
    )

    return (
        "# Crowley Handoff\n\n"
        f"Source: {AGENT}\n"
        f"Type: {handoff_type}\n"
        "Project: Crowley\n\n"
        "## Summary\n\n"
        f"- {summary.strip()}\n\n"
        "## What Changed\n\n"
        f"- {what_changed}\n\n"
        f"{files_section}"
        "## Decisions\n\n"
        f"{decisions_text}\n\n"
        "## QA Results\n\n"
        f"{qa_text}\n\n"
        "## Known Issues\n\n"
        f"{known_issues_text}\n\n"
        "## Open Loops\n\n"
        f"{open_loops_text}\n\n"
        "## Next Action\n\n"
        f"- {next_action.strip()}\n\n"
        "## Do Not Build\n\n"
        f"{do_not_build_text}\n"
    )


def _autofill_handoff(
    path: Path,
    *,
    handoff_type: str,
    summary: str,
    decisions: list[str],
    next_action: str,
    do_not_build: list[str],
    open_loops: list[str],
    qa_results: list[str],
    known_issues: list[str],
) -> None:
    status = _git(["status", "--short"])
    changed = _git(["diff", "--name-only"])
    if not changed:
        changed = _git(["ls-files", "--modified", "--others", "--exclude-standard"])
    path.write_text(
        _section_content(
            handoff_type=handoff_type,
            status=status,
            changed=changed,
            summary=summary,
            decisions=decisions,
            next_action=next_action,
            do_not_build=do_not_build,
            open_loops=open_loops,
            qa_results=qa_results,
            known_issues=known_issues,
        ),
        encoding="utf-8",
    )


def _extract_section(content: str, title: str) -> str:
    marker = f"## {title}"
    start = content.find(marker)
    if start < 0:
        return ""
    start = content.find("\n", start)
    if start < 0:
        return ""
    end = content.find("\n## ", start + 1)
    if end < 0:
        end = len(content)
    lines = [
        line.strip().lstrip("-").strip()
        for line in content[start:end].splitlines()
        if line.strip() and line.strip() != "-"
    ]
    return "\n".join(lines).strip()


def _has_real_handoff_content(path: Path) -> tuple[bool, str]:
    content = path.read_text(encoding="utf-8")
    required = (
        "## Summary",
        "## Decisions",
        "## Next Action",
        "## Do Not Build",
        "## Open Loops",
    )
    missing = [section for section in required if section not in content]
    if missing:
        return False, f"missing required section(s): {', '.join(missing)}"

    summary = _extract_section(content, "Summary")
    next_action = _extract_section(content, "Next Action")
    if not summary:
        return False, "Summary is empty"
    if not next_action:
        return False, "Next Action is empty"
    return True, ""


def _is_note_path(path: Path) -> bool:
    return "_note_handoff_" in path.name.lower()


def _handoff_ready(path: Path) -> tuple[bool, str]:
    if _is_note_path(path):
        content = path.read_text(encoding="utf-8")
        if _extract_section(content, "Summary"):
            return True, ""
        return False, "Note Summary is empty"
    return _has_real_handoff_content(path)


def _ingest_and_verify() -> bool:
    blockers = []
    for path in sorted(INBOX.glob("cursor_*_handoff_*.md")):
        if not path.is_file():
            continue
        ready, reason = _handoff_ready(path)
        if not ready:
            blockers.append(f"{path}: {reason}")
    if blockers:
        print("EDIT REQUIRED: unfinished Cursor handoff(s) would be ingested:")
        for blocker in blockers:
            print(f"- {blocker}")
        print("No files were ingested.")
        return False

    health, health_error = asl.fetch_json(HEALTH_URL)
    if health_error:
        print(f"WARNING: Crowley unavailable at {HEALTH_URL}: {health_error}")
        print("Handoff left in .crowley/inbox for later ingest.")
        return False

    ingest = _run([_python_cmd(), str(ROOT / "scripts" / "ingest_inbox.py")], timeout=180)
    if ingest.stdout.strip():
        print(ingest.stdout.strip())
    if ingest.returncode != 0:
        print("WARNING: Crowley ingest reported a failure.")
        if ingest.stderr.strip():
            print(ingest.stderr.strip())
        return False

    ok, message = asl.verify_agent_handoff(AGENT)
    if ok:
        print(f"Crowley sync succeeded: {message}")
        return True
    status = health.get("status", "ok") if isinstance(health, dict) else "ok"
    print(
        f"WARNING: Crowley ingest completed, but agent_activity verify failed "
        f"(bus {status}): {message}"
    )
    return False


def after(args: argparse.Namespace) -> int:
    _ensure_bus()
    INBOX.mkdir(parents=True, exist_ok=True)
    before_files = {p for p in INBOX.glob("cursor_*_handoff_*.md") if p.is_file()}

    cmd = [
        _python_cmd(),
        str(ROOT / "scripts" / "crowley_handoff.py"),
        "--source",
        AGENT,
        "--type",
        args.handoff_type,
    ]
    if args.handoff_type == "builder_handoff":
        cmd.append("--from-git")

    result = _run(cmd)
    if result.returncode != 0:
        print("Crowley sync failed while creating handoff.", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return 0

    handoff = _latest_handoff(before_files)
    if handoff is None:
        print("Crowley sync failed: handoff generator did not create a file.", file=sys.stderr)
        return 0

    if args.summary and args.next_action:
        _autofill_handoff(
            handoff,
            handoff_type=args.handoff_type,
            summary=args.summary,
            decisions=args.decision,
            next_action=args.next_action,
            do_not_build=args.do_not_build,
            open_loops=args.open_loop,
            qa_results=args.qa_result,
            known_issues=args.known_issue,
        )

    print(f"Handoff ready: {handoff.relative_to(ROOT)}")

    ready, reason = _has_real_handoff_content(handoff)
    if not ready:
        print(f"EDIT REQUIRED: {handoff}")
        print(
            f"Reason: {reason}. Fill Summary, Decisions, Next Action, Do Not Build, "
            "and Open Loops, then run scripts/ingest_inbox.py."
        )
        return 0

    if _ingest_and_verify():
        asl.clear_session_marker()
        if getattr(args, "ticket", None):
            mem_id = asl.last_handoff_memory_id(AGENT)
            ok, err = asl.complete_ticket_api(
                int(args.ticket),
                actor=AGENT,
                linked_memory_id=mem_id,
            )
            if ok:
                print(f"Ticket #{args.ticket} marked done.")
            else:
                print(f"WARNING: handoff ok but ticket close failed: {err}")
    return 0


def claim_ticket_cmd(ticket_id: int) -> int:
    _ensure_bus()
    ok, error = asl.update_ticket_api(
        ticket_id,
        actor=AGENT,
        status="in_progress",
        assignee=AGENT,
        comment="claimed via cursor_sync",
    )
    if ok:
        print(f"Claimed ticket #{ticket_id} (in_progress).")
    else:
        print(f"WARNING: claim failed: {error}")
    return 0


def note(text: str) -> int:
    _ensure_bus()
    INBOX.mkdir(parents=True, exist_ok=True)
    before_files = {p for p in INBOX.glob("cursor_*_handoff_*.md") if p.is_file()}

    result = _run(
        [
            _python_cmd(),
            str(ROOT / "scripts" / "crowley_handoff.py"),
            "--source",
            AGENT,
            "--type",
            "note",
        ]
    )
    if result.returncode != 0:
        print("Crowley sync failed while creating note.", file=sys.stderr)
        return 0

    handoff = _latest_handoff(before_files)
    if handoff is None:
        print("Crowley sync failed: note generator did not create a file.", file=sys.stderr)
        return 0

    handoff.write_text(
        "# Crowley Handoff\n\n"
        f"Source: {AGENT}\n"
        "Type: note\n"
        "Project: Crowley\n\n"
        "## Summary\n\n"
        f"- {text.strip()}\n\n"
        "## Decisions\n\n"
        "- None; short builder update only.\n\n"
        "## Open Loops\n\n"
        "- None recorded.\n\n"
        "## Next Action\n\n"
        "- Continue from the latest Crowley state.\n\n"
        "## Do Not Build\n\n"
        f"- {DEFAULT_DO_NOT_BUILD}\n",
        encoding="utf-8",
    )
    print(f"Note ready: {handoff.relative_to(ROOT)}")
    if _ingest_and_verify():
        asl.clear_session_marker()
    return 0


def status() -> int:
    health, error = asl.fetch_json(HEALTH_URL)
    print("Cursor hardwiring status")
    print("========================")
    if error:
        print(f"bus health: unavailable ({error})")
    else:
        print(f"bus health: ok ({health.get('status', 'unknown')})")
        if "version" in health:
            print(f"version: {health['version']}")
    print(f"scripts/cursor_sync.py: {'present' if Path(__file__).exists() else 'missing'}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Cursor work with Crowley.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--before", action="store_true", help="Read Crowley context before work.")
    group.add_argument("--after", action="store_true", help="Write and ingest a Cursor handoff.")
    group.add_argument("--status", action="store_true", help="Show Crowley bus status.")
    group.add_argument("--session-start", action="store_true", help="Mark session start (hook).")
    group.add_argument("--session-end", action="store_true", help="Check handoff on session end (hook).")
    group.add_argument("--claim-ticket", type=int, metavar="ID", help="Claim ticket for builder work.")
    group.add_argument("--note", help="Ingest a short cursor/note memory item.")
    parser.add_argument(
        "--handoff-type",
        choices=("builder_handoff", "architect_handoff"),
        default="builder_handoff",
        help="Handoff type for --after (default: builder_handoff).",
    )
    parser.add_argument("--summary", help="Real Summary content for --after.")
    parser.add_argument("--ticket", type=int, help="Ticket ID to close on successful --after.")
    parser.add_argument("--next-action", help="Real Next Action content for --after.")
    parser.add_argument("--decision", action="append", default=[], help="Decision bullet; repeatable.")
    parser.add_argument(
        "--do-not-build", action="append", default=[], help="Do Not Build bullet; repeatable."
    )
    parser.add_argument("--open-loop", action="append", default=[], help="Open Loop bullet; repeatable.")
    parser.add_argument("--qa-result", action="append", default=[], help="QA Result bullet; repeatable.")
    parser.add_argument(
        "--known-issue", action="append", default=[], help="Known Issue bullet; repeatable."
    )
    args = parser.parse_args()

    if args.before:
        raise SystemExit(before())
    if args.after:
        raise SystemExit(after(args))
    if args.session_start:
        raise SystemExit(session_start())
    if args.session_end:
        raise SystemExit(session_end())
    if args.claim_ticket is not None:
        raise SystemExit(claim_ticket_cmd(args.claim_ticket))
    if args.note is not None:
        raise SystemExit(note(args.note))
    raise SystemExit(status())


if __name__ == "__main__":
    main()
