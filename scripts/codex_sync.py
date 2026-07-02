#!/usr/bin/env python3
"""Hardwired Codex sync hooks for the Crowley project."""

from __future__ import annotations

import argparse
import json
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
CODEX_MD = ROOT / "CODEX.md"
INBOX = ROOT / ".crowley" / "inbox"
HEALTH_URL = asl.url("/api/bus/health")
AGENT = "codex"
PLACEHOLDER_SUMMARY = "Codex completed a repository work session"
DEFAULT_DO_NOT_BUILD = "Do not build direct Codex-to-Cursor communication; Crowley is the only hub."
VALID_TICKET_ASSIGNEES = frozenset({"codex", "cursor", "crowley", "mr_go", "unassigned"})


def validate_ticket_packet(payload: object) -> list[str]:
    """Return human-readable validation errors for a ticket mint JSON packet."""
    if not isinstance(payload, dict):
        return ["Ticket file must be a JSON object with a tickets array."]
    tickets = payload.get("tickets")
    if not isinstance(tickets, list):
        return ["Ticket file must contain a tickets array."]
    if not tickets:
        return ["Ticket file tickets array is empty."]

    errors: list[str] = []
    for index, item in enumerate(tickets, start=1):
        prefix = f"Ticket #{index}"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        title = str(item.get("title", "")).strip()
        if not title:
            errors.append(f"{prefix}: missing title")

        description = str(item.get("description", "")).strip()
        if not description:
            errors.append(f"{prefix}: missing description")

        if "assignee" not in item or not str(item.get("assignee", "")).strip():
            errors.append(f"{prefix}: missing assignee")
        else:
            assignee = str(item.get("assignee")).strip().lower()
            if assignee not in VALID_TICKET_ASSIGNEES:
                errors.append(
                    f"{prefix}: invalid assignee '{item.get('assignee')}' "
                    f"(must be one of {', '.join(sorted(VALID_TICKET_ASSIGNEES))})"
                )

        if "priority" not in item:
            errors.append(f"{prefix}: missing priority")
        else:
            try:
                priority = int(item.get("priority"))
            except (TypeError, ValueError):
                errors.append(f"{prefix}: invalid priority '{item.get('priority')}'")
            else:
                if priority < 1 or priority > 4:
                    errors.append(f"{prefix}: invalid priority '{priority}' (must be 1-4)")

        acceptance = item.get("acceptance")
        if not isinstance(acceptance, list) or not any(str(entry).strip() for entry in acceptance):
            errors.append(f"{prefix}: missing acceptance criteria")

        parent_id = item.get("parent_id")
        if parent_id is not None:
            try:
                parent_value = int(parent_id)
            except (TypeError, ValueError):
                errors.append(f"{prefix}: invalid parent_id '{parent_id}'")
            else:
                if parent_value < 1:
                    errors.append(f"{prefix}: invalid parent_id '{parent_id}'")

    return errors


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


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_text(item: Any, keys: tuple[str, ...]) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, dict):
        return ""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and key in {"id", "task_id"}:
            return str(value)
    return ""


def _clip(text: str, limit: int = 180) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _print_list(title: str, items: list[Any], keys: tuple[str, ...], *, limit: int = 5) -> None:
    print(f"{title}:")
    if not items:
        print("  - (none reported)")
        return
    for item in items[:limit]:
        text = _first_text(item, keys)
        if not text and isinstance(item, dict):
            text = json.dumps(item, sort_keys=True)
        print(f"  - {_clip(text or str(item))}")


def _memory_text(item: Any) -> str:
    return asl.event_display_line(item)


def _print_memories(title: str, items: list[Any], *, limit: int = 5) -> None:
    print(f"{title}:")
    if not items:
        print("  - (none reported)")
        return
    for item in items[:limit]:
        print(f"  - {_clip(_memory_text(item))}")


def _print_agent_sync(sync: dict[str, Any]) -> None:
    asl.print_agent_sync_bundle(sync, agent=AGENT)
    print("")
    _print_list(
        "recent decisions",
        _as_list(sync.get("recent_decisions")),
        ("decision", "title", "content", "summary", "text"),
    )
    print("")
    _print_list(
        "open loops",
        _as_list(sync.get("open_loops")),
        ("loop", "title", "content", "summary", "text"),
    )
    print("")
    asl.print_tickets_summary(sync, agent=AGENT)
    print("")
    _print_list(
        "open tasks",
        _as_list(sync.get("open_tasks")),
        ("title", "task", "description", "content", "text"),
    )
    print("")
    _print_memories("top retrieved memories", _as_list(sync.get("relevant_memories")))


def before() -> int:
    script = ROOT / "scripts" / "ensure_crowley_bus.sh"
    if script.is_file():
        _run(["bash", str(script)], timeout=30)
    sync, error = asl.fetch_json(
        asl.url("/api/agent/sync", {"agent": AGENT, "limit": 20})
    )
    if error:
        print(f"WARNING: Crowley agent sync unavailable: {error}")
        print("Continuing cautiously without authoritative Crowley context.")
        return 0

    if sync is None:
        print("WARNING: Crowley agent sync returned no context.")
        return 0

    _print_agent_sync(sync)
    return 0


def _latest_handoff(before_files: set[Path]) -> Path | None:
    files = {
        path
        for path in INBOX.glob("codex_*_handoff_*.md")
        if path.is_file()
    }
    created = sorted(files - before_files, key=lambda path: path.stat().st_mtime)
    if created:
        return created[-1]
    all_files = sorted(files, key=lambda path: path.stat().st_mtime)
    return all_files[-1] if all_files else None


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
) -> str:
    status_text = status or "Git status unavailable or clean."
    changed_lines = [line.strip() for line in changed.splitlines() if line.strip()]
    changed_text = "\n".join(f"- {line}" for line in changed_lines) or "- No changed files reported."
    decisions_text = _bullets(decisions) or "- No new product decisions recorded."
    do_not_build_text = _bullets(do_not_build) or f"- {DEFAULT_DO_NOT_BUILD}"
    open_loops_text = _bullets(open_loops) or "- None recorded."
    qa_default = "- Not run; planning-only handoff." if handoff_type == "architect_handoff" else "- Not recorded."
    qa_text = _bullets(qa_results) or qa_default
    files_section = (
        "## Files Changed\n\n"
        "### Git status\n\n"
        "```\n"
        f"{status_text}\n"
        "```\n\n"
        "### Changed files\n\n"
        f"{changed_text}\n\n"
    )
    if handoff_type == "architect_handoff":
        files_section = "## Files Changed\n\n- None; planning-only architect handoff.\n\n"
    return (
        "# Crowley Handoff\n\n"
        "Source: codex\n"
        f"Type: {handoff_type}\n"
        "Project: Crowley\n\n"
        "## Summary\n\n"
        f"- {summary.strip()}\n\n"
        "## What Changed\n\n"
        f"- {'Planning handoff for Cursor via Crowley.' if handoff_type == 'architect_handoff' else 'Code/session handoff for Crowley memory.'}\n\n"
        f"{files_section}"
        "## Decisions\n\n"
        f"{decisions_text}\n\n"
        "## QA Results\n\n"
        f"{qa_text}\n\n"
        "## Known Issues\n\n"
        "- None recorded.\n\n"
        "## Open Loops\n\n"
        f"{open_loops_text}\n\n"
        "## Next Action\n\n"
        f"- {next_action.strip()}\n\n"
        "## Do Not Build\n\n"
        f"{do_not_build_text}\n"
    )


def _bullets(items: list[str]) -> str:
    cleaned = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"- {item}" for item in cleaned)


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
        ),
        encoding="utf-8",
    )


def _has_real_handoff_content(path: Path) -> tuple[bool, str]:
    content = path.read_text(encoding="utf-8")
    if PLACEHOLDER_SUMMARY.lower() in content.lower():
        return False, "Summary still contains placeholder Codex text"
    required = ("## Summary", "## Decisions", "## Next Action", "## Do Not Build", "## Open Loops")
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
        line.strip()
        for line in content[start:end].splitlines()
        if line.strip() and line.strip() != "-"
    ]
    return "\n".join(lines).strip()


def _ingest_and_verify() -> bool:
    blockers = []
    for path in sorted(INBOX.glob("codex_*_handoff_*.md")):
        if not path.is_file():
            continue
        ready, reason = _has_real_handoff_content(path)
        if not ready:
            blockers.append(f"{path}: {reason}")
    if blockers:
        print("EDIT REQUIRED: unfinished Codex handoff(s) would be ingested:")
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
        print("Any failed handoff remains in .crowley/inbox.")
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
    script = ROOT / "scripts" / "ensure_crowley_bus.sh"
    if script.is_file():
        _run(["bash", str(script)], timeout=30)
    INBOX.mkdir(parents=True, exist_ok=True)
    before_files = {
        path
        for path in INBOX.glob("codex_*_handoff_*.md")
        if path.is_file()
    }

    generator = ROOT / "scripts" / "crowley_handoff.py"
    result = _run(
        [
            _python_cmd(),
            str(generator),
            "--source",
            "codex",
            "--type",
            args.handoff_type,
            *(["--from-git"] if args.handoff_type == "builder_handoff" else []),
        ]
    )
    if result.returncode != 0:
        print("Crowley sync failed while creating handoff.")
        if result.stderr.strip():
            print(result.stderr.strip())
        return 0

    handoff = _latest_handoff(before_files)
    if handoff is None:
        print("Crowley sync failed: handoff generator did not create a file.")
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
        )
    print(f"Handoff ready: {handoff.relative_to(ROOT)}")

    ready, reason = _has_real_handoff_content(handoff)
    if not ready:
        print(f"EDIT REQUIRED: {handoff}")
        print(f"Reason: {reason}. Fill Summary, Decisions, Next Action, Do Not Build, and Open Loops, then run scripts/ingest_inbox.py.")
        return 0

    _ingest_and_verify()
    return 0


def note(text: str) -> int:
    script = ROOT / "scripts" / "ensure_crowley_bus.sh"
    if script.is_file():
        _run(["bash", str(script)], timeout=30)
    INBOX.mkdir(parents=True, exist_ok=True)
    before_files = {
        path
        for path in INBOX.glob("codex_*_handoff_*.md")
        if path.is_file()
    }
    result = _run(
        [
            _python_cmd(),
            str(ROOT / "scripts" / "crowley_handoff.py"),
            "--source",
            "codex",
            "--type",
            "note",
        ]
    )
    if result.returncode != 0:
        print("Crowley sync failed while creating note.")
        if result.stderr.strip():
            print(result.stderr.strip())
        return 0
    handoff = _latest_handoff(before_files)
    if handoff is None:
        print("Crowley sync failed: note generator did not create a file.")
        return 0
    handoff.write_text(
        "# Crowley Handoff\n\n"
        "Source: codex\n"
        "Type: note\n"
        "Project: Crowley\n\n"
        "## Summary\n\n"
        f"- {text.strip()}\n\n"
        "## Decisions\n\n"
        "- None; short planning update only.\n\n"
        "## Open Loops\n\n"
        "- None recorded.\n\n"
        "## Next Action\n\n"
        "- Continue from the latest Crowley state.\n\n"
        "## Do Not Build\n\n"
        f"- {DEFAULT_DO_NOT_BUILD}\n",
        encoding="utf-8",
    )
    print(f"Note ready: {handoff.relative_to(ROOT)}")
    _ingest_and_verify()
    return 0


def create_ticket_cli(args: argparse.Namespace) -> int:
    script = ROOT / "scripts" / "ensure_crowley_bus.sh"
    if script.is_file():
        _run(["bash", str(script)], timeout=30)
    description = args.description or ""
    if args.acceptance:
        description = (description + "\n\nAcceptance:\n" + "\n".join(f"- {a}" for a in args.acceptance)).strip()
    ticket_id, error = asl.create_ticket_api(
        title=args.title or "",
        description=description,
        assignee=args.assignee,
        priority=args.priority,
        parent_id=args.parent_id,
        source="codex",
        actor="codex",
    )
    if error or ticket_id is None:
        print(f"Ticket create failed: {error}")
        return 0
    print(f"Created ticket #{ticket_id}: {args.title}")
    return 0


def cancel_ticket_cli(args: argparse.Namespace) -> int:
    script = ROOT / "scripts" / "ensure_crowley_bus.sh"
    if script.is_file():
        _run(["bash", str(script)], timeout=30)
    if not args.comment or not args.comment.strip():
        print("Ticket cancel failed: --comment is required with --cancel-ticket")
        return 1
    ok, error = asl.cancel_ticket_api(
        int(args.cancel_ticket),
        actor="codex",
        comment=args.comment.strip(),
    )
    if not ok:
        print(f"Ticket cancel failed: {error}")
        return 1
    print(f"Cancelled ticket #{args.cancel_ticket}: {args.comment.strip()}")
    return 0


def create_tickets_file(path: str) -> int:
    script = ROOT / "scripts" / "ensure_crowley_bus.sh"
    if script.is_file():
        _run(["bash", str(script)], timeout=30)
    file_path = Path(path)
    if not file_path.is_file():
        print(f"Ticket file not found: {file_path}")
        return 0
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Invalid ticket JSON: {exc}")
        return 0
    tickets = payload.get("tickets") if isinstance(payload, dict) else None
    if not isinstance(tickets, list):
        print("Ticket file must contain a tickets array.")
        return 2
    errors = validate_ticket_packet(payload)
    if errors:
        print("Ticket packet validation failed:")
        for error in errors:
            print(f"- {error}")
        return 2
    created: list[int] = []
    for item in tickets:
        assert isinstance(item, dict)
        title = str(item.get("title", "")).strip()
        description = str(item.get("description", "")).strip()
        acceptance = item.get("acceptance")
        if isinstance(acceptance, list):
            description = (
                description
                + "\n\nAcceptance:\n"
                + "\n".join(f"- {str(a).strip()}" for a in acceptance if str(a).strip())
            ).strip()
        parent_id = item.get("parent_id")
        parent_value = int(parent_id) if parent_id is not None else None
        ticket_id, error = asl.create_ticket_api(
            title=title,
            description=description,
            assignee=str(item.get("assignee", "cursor")),
            priority=int(item.get("priority", 2)),
            parent_id=parent_value,
            source="codex",
            actor="codex",
        )
        if error or ticket_id is None:
            print(f"WARNING: failed to create '{title}': {error}")
            continue
        created.append(ticket_id)
        print(f"Created ticket #{ticket_id}: {title}")
    print(f"Minted {len(created)} ticket(s).")
    return 0


def status() -> int:
    health, error = asl.fetch_json(HEALTH_URL)
    print("Codex hardwiring status")
    print("=======================")
    if error:
        print(f"bus health: unavailable ({error})")
    else:
        print(f"bus health: ok ({health.get('status', 'unknown')})")
        if "version" in health:
            print(f"version: {health['version']}")
    print(f"CODEX.md: {'present' if CODEX_MD.exists() else 'missing'}")
    print(f"scripts/codex_sync.py: {'present' if Path(__file__).exists() else 'missing'}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Codex work with Crowley.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--before", action="store_true", help="Read Crowley context before work.")
    group.add_argument("--after", action="store_true", help="Write and ingest a Codex handoff after work.")
    group.add_argument("--status", action="store_true", help="Show Crowley bus and hardwiring status.")
    group.add_argument("--note", help="Ingest a short codex/note memory item.")
    group.add_argument("--create-ticket", action="store_true", help="Create one ticket via API.")
    group.add_argument("--create-tickets", metavar="FILE", help="Create tickets from JSON file.")
    group.add_argument(
        "--cancel-ticket",
        type=int,
        metavar="ID",
        help="Cancel a draft/superseded ticket via API (requires --comment).",
    )
    parser.add_argument("--title", help="Ticket title for --create-ticket.")
    parser.add_argument("--description", default="", help="Ticket description.")
    parser.add_argument(
        "--comment",
        help="Cancellation reason for --cancel-ticket.",
    )
    parser.add_argument("--acceptance", action="append", default=[], help="Acceptance bullet; repeatable.")
    parser.add_argument(
        "--assignee",
        default="cursor",
        choices=("codex", "cursor", "crowley", "mr_go", "unassigned"),
    )
    parser.add_argument("--priority", type=int, default=2, help="Ticket priority 1-4.")
    parser.add_argument("--parent-id", type=int, default=None, help="Parent initiative ticket id.")
    parser.add_argument(
        "--handoff-type",
        choices=("architect_handoff", "builder_handoff"),
        default="architect_handoff",
        help="Handoff type for --after (default: architect_handoff).",
    )
    parser.add_argument("--summary", help="Real Summary content for --after.")
    parser.add_argument("--next-action", help="Real Next Action content for --after.")
    parser.add_argument("--decision", action="append", default=[], help="Decision bullet for --after; repeatable.")
    parser.add_argument("--do-not-build", action="append", default=[], help="Do Not Build bullet for --after; repeatable.")
    parser.add_argument("--open-loop", action="append", default=[], help="Open Loop bullet for --after; repeatable.")
    parser.add_argument("--qa-result", action="append", default=[], help="QA Result bullet for --after; repeatable.")
    args = parser.parse_args()

    if args.before:
        raise SystemExit(before())
    if args.after:
        raise SystemExit(after(args))
    if args.note is not None:
        raise SystemExit(note(args.note))
    if args.create_ticket:
        if not args.title:
            parser.error("--create-ticket requires --title")
        raise SystemExit(create_ticket_cli(args))
    if args.create_tickets:
        raise SystemExit(create_tickets_file(args.create_tickets))
    if args.cancel_ticket is not None:
        raise SystemExit(cancel_ticket_cli(args))
    raise SystemExit(status())


if __name__ == "__main__":
    main()
