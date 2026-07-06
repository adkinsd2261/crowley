#!/usr/bin/env python3
"""Ingest handoff files from .crowley/inbox into Crowley memory (V3.7 Phase 4)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / ".crowley" / "inbox"
PROCESSED = ROOT / ".crowley" / "processed"
INGEST_URL = "http://127.0.0.1:8765/api/ingest"

HANDOFF_SUFFIXES = {".md", ".txt"}


def _ensure_dirs() -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)


def infer_source(filename: str) -> str:
    lower = filename.lower()
    if lower.startswith("cursor_"):
        return "cursor"
    if lower.startswith("chatgpt_"):
        return "chatgpt"
    if lower.startswith("codex_"):
        return "codex"
    return "manual"


def infer_handoff_type(filename: str) -> str:
    lower = filename.lower()
    if "builder" in lower:
        return "builder_handoff"
    if "architect" in lower:
        return "architect_handoff"
    if "qa" in lower:
        return "qa_result"
    if "project" in lower:
        return "project_update"
    if "session" in lower:
        return "session_summary"
    if "note" in lower:
        return "note"
    return "session_summary"


def list_inbox_files() -> list[Path]:
    if not INBOX.is_dir():
        return []
    files = [
        path
        for path in sorted(INBOX.iterdir())
        if path.is_file() and path.suffix.lower() in HANDOFF_SUFFIXES
    ]
    return files


def _unique_processed_path(filename: str) -> Path:
    target = PROCESSED / filename
    if not target.exists():
        return target
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = PROCESSED / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def ingest_via_engine(
    source: str,
    handoff_type: str,
    content: str,
    project: str,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    import crowley
    import handoff_ticket_bridge

    ingest_metadata = dict(metadata or {})
    if handoff_type in {"builder_handoff", "architect_handoff"}:
        refs = handoff_ticket_bridge.extract_referenced_ticket_ids(
            content,
            metadata=ingest_metadata,
        )
        if refs and "closed_work_ticket_id" not in ingest_metadata:
            ingest_metadata["closed_work_ticket_id"] = refs[0]

    crowley.setup_db()
    return crowley.ingest_handoff(
        source=source,
        handoff_type=handoff_type,
        content=content,
        project=project,
        metadata=ingest_metadata,
    )


def ingest_via_http(
    source: str,
    handoff_type: str,
    content: str,
    project: str,
) -> dict[str, object]:
    import handoff_ticket_bridge

    metadata: dict[str, object] = {}
    if handoff_type in {"builder_handoff", "architect_handoff"}:
        refs = handoff_ticket_bridge.extract_referenced_ticket_ids(content)
        if refs:
            metadata["closed_work_ticket_id"] = refs[0]
    payload = {
        "source": source,
        "type": handoff_type,
        "project": project,
        "content": content,
        "metadata": metadata,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        INGEST_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"status": "error", "error": body or str(exc)}
    except urllib.error.URLError as exc:
        return {"status": "error", "error": str(exc.reason)}

    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"status": "error", "error": "invalid JSON response from /api/ingest"}


def process_file(
    path: Path,
    *,
    project: str,
    via_http: bool,
) -> tuple[str, str]:
    """
    Process one inbox file.
    Returns (outcome, detail) where outcome is processed|skipped|failed.
    """
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return "skipped", "empty file"

    source = infer_source(path.name)
    handoff_type = infer_handoff_type(path.name)

    if via_http:
        result = ingest_via_http(source, handoff_type, content, project)
    else:
        sys.path.insert(0, str(ROOT))
        try:
            result = ingest_via_engine(source, handoff_type, content, project)
        except Exception as exc:
            return "failed", str(exc)

    status = str(result.get("status", ""))
    if status != "ok":
        error = result.get("error", result)
        return "failed", str(error)

    target = _unique_processed_path(path.name)
    shutil.move(str(path), str(target))
    memory_id = result.get("memory_item_id")
    return "processed", f"memory_item_id={memory_id} -> {target.name}"


def run_inbox(*, project: str, via_http: bool) -> int:
    _ensure_dirs()
    files = list_inbox_files()
    if not files:
        print("ingest_inbox: no .md or .txt files in .crowley/inbox")
        return 0

    processed = 0
    skipped = 0
    failed = 0

    for path in files:
        outcome, detail = process_file(path, project=project, via_http=via_http)
        if outcome == "processed":
            processed += 1
            print(f"processed: {path.name} ({detail})")
        elif outcome == "skipped":
            skipped += 1
            print(f"skipped: {path.name} ({detail})")
        else:
            failed += 1
            print(f"failed: {path.name} ({detail})")

    mode = "http" if via_http else "engine"
    print(
        f"summary: processed={processed} skipped={skipped} failed={failed} "
        f"(mode={mode})"
    )
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest handoff files from .crowley/inbox into Crowley."
    )
    parser.add_argument(
        "--project",
        default="crowley",
        help="Project slug (default: crowley)",
    )
    parser.add_argument(
        "--via-http",
        action="store_true",
        help="POST to /api/ingest instead of calling ingest_handoff() directly",
    )
    args = parser.parse_args()
    raise SystemExit(run_inbox(project=args.project, via_http=args.via_http))


if __name__ == "__main__":
    main()
