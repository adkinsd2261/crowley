#!/usr/bin/env python3
"""Synthesize Crowley's layered canon memory from existing local truth."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402


CANON_TITLES = [
    "Canon: Project",
    "Canon: Agents",
    "Canon: Decisions",
    "Canon: Work",
    "Canon: Mr. Go",
    "Canon: Recent",
]

EVIDENCE_RE = re.compile(
    r"\b(?:memory_items|decision|loop|task|message|project_state):\d+\b"
    r"|(?:^|\s)(?:docs/[A-Za-z0-9_./-]+\.md|VERSIONS\.md|CODEX\.md)\b",
    re.MULTILINE,
)
SECRET_RE = re.compile(
    r"\b[A-Z0-9_]*API_KEY\s*="
    r"|\b[A-Z0-9_]*TOKEN\s*="
    r"|\bpassword\s*="
    r"|\bsecret\s*="
    r"|\bsk-[A-Za-z0-9_-]{20,}\b",
    re.IGNORECASE,
)


def _row_dict(row) -> dict[str, object]:
    return crowley.row_to_dict(row)


def _active_memory_items(project_id: int) -> list[dict[str, object]]:
    conn = crowley.connect_db()
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, memory_type, source, importance, content, summary
            FROM memory_items
            WHERE status = 'active'
              AND (project_id = ? OR project_id IS NULL)
              AND NOT (
                source = 'crowley'
                AND pinned = 1
                AND memory_type = 'summary'
                AND content LIKE 'Canon:%'
              )
            ORDER BY id ASC
            """,
            (project_id,),
        ).fetchall()
        return [_row_dict(row) for row in rows]
    finally:
        conn.close()


def _recent_unsummarized_messages() -> list[dict[str, object]]:
    conn = crowley.connect_db()
    try:
        latest = conn.execute(
            """
            SELECT created_at FROM memory_items
            WHERE source = 'session_summary'
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        params: list[object] = []
        where = ""
        if latest is not None:
            where = "WHERE datetime(timestamp) > datetime(?)"
            params.append(str(latest["created_at"]))
        rows = conn.execute(
            f"""
            SELECT id, timestamp, role, content
            FROM messages
            {where}
            ORDER BY id ASC
            LIMIT 40
            """,
            params,
        ).fetchall()
        return [_row_dict(row) for row in rows]
    finally:
        conn.close()


def build_source_packet(project_slug: str = crowley.DEFAULT_PROJECT_SLUG) -> dict[str, object]:
    crowley.setup_db()
    project = crowley.get_project_by_slug(project_slug)
    if project is None:
        raise ValueError(f"project not found: {project_slug}")
    project_id = int(project["id"])
    state = crowley.get_project_state(project_id)
    return {
        "project": _row_dict(project),
        "project_state": _row_dict(state) if state is not None else None,
        "decisions": [
            _row_dict(row) for row in crowley.list_decisions(project_id, limit=50)
        ],
        "open_loops": [
            _row_dict(row)
            for row in crowley.list_open_loops(project_id, status="open", limit=50)
        ],
        "tasks": [_row_dict(row) for row in crowley.list_tasks(status="open")],
        "memory_items": _active_memory_items(project_id),
        "knowledge_docs": crowley.load_knowledge_files_context(
            "current project memory canon agents architecture work decisions",
            max_files=7,
            max_chars_per_file=2200,
        ),
        "recent_unsummarized_messages": _recent_unsummarized_messages(),
    }


def build_model_messages(packet: dict[str, object]) -> list[dict[str, str]]:
    instructions = "\n".join(
        [
            "Synthesize Crowley's canon memory from the provided source packet.",
            "Return exactly six Markdown sections with these headings:",
            *[f"## {title}" for title in CANON_TITLES],
            "Every section must be concise, factual, and include evidence markers.",
            "Use evidence markers like memory_items:85, decision:31, loop:3, task:11, project_state:1, docs/PROJECT_STATE.md, VERSIONS.md, or CODEX.md.",
            "Do not include secrets or raw credentials.",
            "Do not invent continuity not supported by the source packet.",
        ]
    )
    return [
        {"role": "system", "content": instructions},
        {
            "role": "user",
            "content": json.dumps(packet, ensure_ascii=False, default=str),
        },
    ]


def parse_canon_output(text: str) -> dict[str, str]:
    layers: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []

    def flush() -> None:
        nonlocal lines
        if current is not None:
            layers[current] = "\n".join(lines).strip()
        lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        title = None
        if line.startswith("## "):
            candidate = line[3:].strip()
            if candidate in CANON_TITLES:
                title = candidate
        elif line in CANON_TITLES:
            title = line
        if title:
            flush()
            current = title
            continue
        if current is not None:
            lines.append(raw_line.rstrip())
    flush()
    return layers


def validate_canon_layers(layers: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for title in CANON_TITLES:
        body = layers.get(title, "").strip()
        if not body:
            errors.append(f"missing or empty layer: {title}")
            continue
        if not EVIDENCE_RE.search(body):
            errors.append(f"missing evidence marker: {title}")
        if SECRET_RE.search(body):
            errors.append(f"secret-looking content rejected: {title}")
    unknown = sorted(set(layers) - set(CANON_TITLES))
    for title in unknown:
        errors.append(f"unexpected layer: {title}")
    return errors


def _archive_existing_canon(conn, project_id: int) -> int:
    cur = conn.execute(
        """
        UPDATE memory_items
        SET status = 'archived', updated_at = ?
        WHERE status = 'active'
          AND source = 'crowley'
          AND pinned = 1
          AND memory_type = 'summary'
          AND content LIKE 'Canon:%'
          AND (project_id = ? OR project_id IS NULL)
        """,
        (crowley._now_iso(), project_id),
    )
    return int(cur.rowcount)


def _insert_canon_layers(conn, project_id: int, layers: dict[str, str]) -> list[int]:
    now = crowley._now_iso()
    inserted: list[int] = []
    for title in CANON_TITLES:
        content = f"{title}\n\n{layers[title].strip()}"
        cur = conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, pinned, status, confidence
            ) VALUES (?, ?, ?, 'summary', ?, ?, 5, 'crowley', 1, 'active', 0.95)
            """,
            (now, now, project_id, content, title),
        )
        inserted.append(int(cur.lastrowid))
    return inserted


def synthesize_canon(
    *,
    project_slug: str = crowley.DEFAULT_PROJECT_SLUG,
    write: bool = False,
    model_func: Callable[[list[dict[str, str]]], str | None] | None = None,
) -> dict[str, object]:
    packet = build_source_packet(project_slug)
    messages = build_model_messages(packet)
    if model_func is None:
        model_func = lambda msgs: crowley.call_model(msgs, stream=False, quiet=True)
    output = model_func(messages)
    if not output:
        return {
            "status": "error",
            "dry_run": not write,
            "errors": ["model returned no output"],
        }

    layers = parse_canon_output(output)
    errors = validate_canon_layers(layers)
    if errors:
        return {
            "status": "error",
            "dry_run": not write,
            "errors": errors,
            "layers_found": sorted(layers),
        }

    if not write:
        return {
            "status": "ok",
            "dry_run": True,
            "layers": CANON_TITLES,
            "would_write": len(CANON_TITLES),
        }

    project = crowley.get_project_by_slug(project_slug)
    if project is None:
        raise ValueError(f"project not found: {project_slug}")
    project_id = int(project["id"])
    conn = crowley.connect_db()
    try:
        archived = _archive_existing_canon(conn, project_id)
        inserted_ids = _insert_canon_layers(conn, project_id, layers)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "status": "ok",
        "dry_run": False,
        "archived": archived,
        "inserted": len(inserted_ids),
        "inserted_ids": inserted_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize Crowley canon memory.")
    parser.add_argument("--project", default=crowley.DEFAULT_PROJECT_SLUG)
    parser.add_argument("--write", action="store_true", help="Archive old canon and insert new canon rows.")
    parser.add_argument(
        "--show-packet",
        action="store_true",
        help="Print the source packet and exit without model or writes.",
    )
    args = parser.parse_args()

    if args.show_packet:
        print(json.dumps(build_source_packet(args.project), indent=2, default=str))
        return

    result = synthesize_canon(project_slug=args.project, write=args.write)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
