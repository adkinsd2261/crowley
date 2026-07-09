"""V4.1 — read-only secret hygiene audit helpers."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.IGNORECASE)),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    (
        "assigned_secret",
        re.compile(
            r"\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*['\"]?[^\s'\"<>\[\]]{8,}",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True)
class SecretFinding:
    kind: str
    source: str
    field: str
    record_id: str | None
    offset: int
    excerpt: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source": self.source,
            "field": self.field,
            "record_id": self.record_id,
            "offset": self.offset,
            "excerpt": self.excerpt,
        }


def _redact(text: str) -> str:
    result = str(text or "")
    for kind, pattern in SECRET_PATTERNS:
        label = kind.upper().replace("_", "-")
        result = pattern.sub(f"[REDACTED-{label}]", result)
    return result


def _excerpt(text: str, start: int, end: int, *, radius: int = 48) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    clipped = text[left:right].replace("\n", " ")
    return _redact(clipped).strip()


def scan_text_for_secrets(
    text: object,
    *,
    source: str,
    field: str,
    record_id: object | None = None,
) -> list[SecretFinding]:
    """Return redacted findings for likely secrets in text."""
    body = str(text or "")
    findings: list[SecretFinding] = []
    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(body):
            findings.append(
                SecretFinding(
                    kind=kind,
                    source=source,
                    field=field,
                    record_id=None if record_id is None else str(record_id),
                    offset=int(match.start()),
                    excerpt=_excerpt(body, int(match.start()), int(match.end())),
                )
            )
    return findings


def _default_log_paths(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for pattern in (".crowley/*.log", ".crowley/chatgpt_bridge/*.log"):
        candidates.extend(root.glob(pattern))
    return sorted(path for path in candidates if path.is_file())


def secret_hygiene_report(
    *,
    conn: sqlite3.Connection | None = None,
    include_logs: bool = True,
    log_paths: list[Path] | None = None,
    memory_limit: int = 500,
    root: Path | None = None,
) -> dict[str, object]:
    """
    Read-only report of likely secrets in raw memory/log-adjacent text.

    The report intentionally returns redacted excerpts only and performs no
    updates, deletes, access-count bumps, or metadata changes.
    """
    import crowley

    owns_conn = conn is None
    db = conn or crowley.connect_db()
    findings: list[SecretFinding] = []
    scanned_memory_items = 0
    scanned_logs = 0
    try:
        rows = db.execute(
            """
            SELECT id, summary, content, metadata_json
            FROM memory_items
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(memory_limit)),),
        ).fetchall()
        scanned_memory_items = len(rows)
        for row in rows:
            record_id = int(row["id"]) if isinstance(row, sqlite3.Row) else row[0]
            fields = {
                "summary": row["summary"] if isinstance(row, sqlite3.Row) else row[1],
                "content": row["content"] if isinstance(row, sqlite3.Row) else row[2],
                "metadata_json": row["metadata_json"] if isinstance(row, sqlite3.Row) else row[3],
            }
            for field, value in fields.items():
                findings.extend(
                    scan_text_for_secrets(
                        value,
                        source="memory_items",
                        field=field,
                        record_id=record_id,
                    )
                )

        if include_logs:
            repo_root = root or Path(__file__).resolve().parent
            paths = log_paths if log_paths is not None else _default_log_paths(repo_root)
            for path in paths:
                if not path.is_file():
                    continue
                scanned_logs += 1
                text = path.read_text(encoding="utf-8", errors="replace")[:200_000]
                findings.extend(
                    scan_text_for_secrets(
                        text,
                        source="log_file",
                        field=str(path),
                        record_id=path.name,
                    )
                )
    finally:
        if owns_conn:
            db.close()

    by_kind: dict[str, int] = {}
    for finding in findings:
        by_kind[finding.kind] = by_kind.get(finding.kind, 0) + 1

    return {
        "status": "ok",
        "read_only": True,
        "scanned": {
            "memory_items": scanned_memory_items,
            "log_files": scanned_logs,
        },
        "counts": {
            "total": len(findings),
            "by_kind": by_kind,
        },
        "findings": [finding.to_dict() for finding in findings],
    }
