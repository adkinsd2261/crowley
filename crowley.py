#!/usr/bin/env python3
"""Crowley V3.9 — local AI OS with memory backend, context bridge, and web workspace UI."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ollama

# --- local env (optional .env file, never committed) --------------------------


def _load_local_env() -> None:
    """Load KEY=VALUE lines from .env into os.environ if not already set."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()

# --- constants ----------------------------------------------------------------

CROWLEY_VERSION = "3.9.1"
CROWLEY_RELEASE_LABEL = "Crowley V3.9.1 Repository & CI"

DB_PATH = Path(__file__).parent / "crowley.db"
PROJECT_ROOT = Path(__file__).parent
VERSIONS_MD_PATH = PROJECT_ROOT / "VERSIONS.md"
PROJECT_STATE_MD_PATH = PROJECT_ROOT / "docs" / "PROJECT_STATE.md"
PROJECT_FILES_EXCERPT_MAX = 480

KNOWLEDGE_FILES = [
    "VERSIONS.md",
    "docs/WHERE_WE_ARE.md",
    "docs/PROJECT_STATE.md",
    "docs/ARCHITECTURE.md",
    "docs/V3.9.1_REPOSITORY_AND_CI.md",
    "docs/V3.9_CONCURRENT_TICKETING.md",
    "docs/V3.8.1_AGENT_PARITY.md",
    "docs/V3.8_MEMORY_TRAIL.md",
    "docs/V3.7_CONTEXT_BRIDGE.md",
    "docs/V3.6_MEMORY_BACKEND.md",
    "docs/V3.5_CHAT_UI.md",
    "docs/TICKETS.md",
]
BASELINE_KNOWLEDGE_FILES = [
    "VERSIONS.md",
    "docs/WHERE_WE_ARE.md",
    "docs/PROJECT_STATE.md",
]
KNOWLEDGE_DEFAULT_MAX_FILES = 6
KNOWLEDGE_DEFAULT_MAX_CHARS = 1800

_VERSION_QUERY_KEYWORDS = frozenset({
    "version", "versions", "release", "released", "shipped", "shipping",
    "phase", "history", "changelog", "roadmap",
})
_PROJECT_STATE_QUERY_KEYWORDS = frozenset({
    "current", "project", "state", "focus", "risk", "action", "changed",
    "status", "now", "today", "priority", "next",
})

MODEL_PROVIDER = "auto"
OPENAI_MODEL = "gpt-4.1-mini"
OLLAMA_MODEL = "llama3.1:8b"

SPARK_IMPORTANCE_TRIM = 1
SPARK_IMPORTANCE_SUMMARY = 2
SPARK_MESSAGES_PER_SUMMARY = 4
SPARK_SUMMARY_INTERVAL_SEC = 0
MAX_TRIM_LEN = 200
IMPLICIT_SPARK_MIN_LEN = 25
IMPLICIT_SPARK_LONG_LEN = 100

MEMORY_LIMIT = 8
TASK_LIMIT = 5
MEMORY_LINE_MAX = 300
CHAT_CONTEXT_LIMIT = 8
CHAT_CONTEXT_MESSAGE_MAX_LEN = 600

MEMORY_EMBED_PROVIDER = "auto"
EMBED_MODEL_LOCAL = "all-MiniLM-L6-v2"
EMBED_DIM = 384

MEMORY_RETRIEVE_VECTOR_CANDIDATES = 20
MEMORY_RETRIEVE_KEYWORD_CANDIDATES = 20
MEMORY_RETRIEVE_SUMMARY_CANDIDATES = 5
MEMORY_RECENCY_HIGH_DAYS = 7
MEMORY_RECENCY_LOW_DAYS = 90

W_SCORE_SEMANTIC = 0.45
W_SCORE_KEYWORD = 0.20
W_SCORE_RECENCY = 0.15
W_SCORE_IMPORTANCE = 0.10
W_SCORE_TYPE = 0.05
W_SCORE_PROJECT = 0.05
W_SCORE_PINNED_BONUS = 0.10

MEMORY_ITEM_DEDUPE_HOURS = 24
MEMORY_CONSOLIDATE_DUPLICATE_SIM = 0.92
MEMORY_CONSOLIDATE_PAIR_LIMIT = 500
MEMORY_STALE_AGE_DAYS = 90
MEMORY_STALE_MAX_IMPORTANCE = 2
MEMORY_DAILY_SUMMARY = os.environ.get("MEMORY_DAILY_SUMMARY", "0") == "1"
ALLOWED_MEMORY_ITEM_TYPES = frozenset({
    "event",
    "decision",
    "preference",
    "constraint",
    "bug",
    "qa_result",
    "lesson",
    "project_update",
    "summary",
})

STATE_FIELDS = frozenset({"phase", "focus", "current_risk", "next_action", "what_changed"})
STATE_FIELD_ALIASES = {"risk": "current_risk"}
DECISIONS_LIMIT = 10
LOOPS_LIMIT = 10
WORLD_DECISIONS_IN_PROMPT = 3
WORLD_LOOPS_IN_PROMPT = 5

DIAGNOSTICS_DECISIONS_LIMIT = 5
DIAGNOSTICS_SPARKS_LIMIT = 5
DIAGNOSTICS_TASKS_LIMIT = 10

DEFAULT_PROJECT_NAME = "Crowley"
DEFAULT_PROJECT_SLUG = "crowley"

_spark_lock = threading.Lock()
_spark_spawn_lock = threading.Lock()
_spark_running = False
_extract_lock = threading.Lock()
_extract_spawn_lock = threading.Lock()
_extract_running = False

_sqlite_vec_ready: bool | None = None
_embed_model = None
_embed_model_lock = threading.Lock()
_last_retrieval_mode = "keyword-only fallback"

EXTRACT_CONFIDENCE_MIN = 0.85
EXTRACT_DECISION_MAX_LEN = 160
EXTRACT_LOOP_MAX_LEN = 160
EXTRACT_STATE_MAX_LEN = 120
EXTRACT_DEDUPE_HOURS = 24
EXTRACT_CONTEXT_LIMIT = 8

EXTRACT_KEYWORDS = (
    "approved", "approve", "passed", "ship", "shipped", "decided", "decision",
    "we decided", "next action", "next", "focus", "phase", "risk", "bottleneck",
    "blocked", "blocker", "open loop", "need to", "need", "build", "implement",
    "qa", "diagnostics", "world model", "extraction", "fallback", "primary",
    "main brain", "roadmap", "scope", "v3", "v2.6", "crowley",
)

_GENERIC_EXTRACT_VALUES = frozenset({
    "continue working",
    "make progress",
    "improve system",
    "keep going",
    "work on project",
    "continue",
    "keep working",
})

_SKIP_EXACT = frozenset({
    "hey", "hi", "hello", "morning", "mornin", "ok", "okay", "thanks",
    "thank you", "lol", "yes", "no", "yep", "nope", "sure", "cool", "nice",
    "got it", "bye", "goodbye",
})

_SKIP_PHRASES = (
    "what are we building",
    "what do you remember",
    "what's my favorite color",
    "what is my favorite color",
    "what were we working on",
    "what's on my plate",
    "what is on my plate",
)

_SHELL_PREFIXES = (
    "cd ", "ls", "pwd", "python ", "python3 ", "pip ", "brew ", "git ",
    "ollama ", "sqlite3 ", "code ", "nano ", "cat ", "grep ", "sed ", "rm ",
    "mkdir ", "touch ", "source ", "./venv",
)

_SIGNAL_KEYWORDS = (
    "goal", "plan", "decide", "decision", "architecture", "architect", "prefer",
    "preference", "constraint", "idea", "problem", "lesson", "project", "system",
    "build", "implement", "refactor", "design", "deploy", "database", "schema",
    "api", "stack", "memory", "spark", "crowley", "strategy", "roadmap", "bug",
    "fix", "feature", "version", "release", "tradeoff", "approach", "pattern",
    "module", "component", "service", "integration", "migration", "workflow",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _truncate(text: str, max_len: int = MAX_TRIM_LEN) -> str:
    text = _normalize_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _tokenize(text: str) -> list[str]:
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return [t for t in tokens if len(t) >= 3]


def should_create_implicit_spark(content: str) -> bool:
    """
    Decide if a user message is worth a trim-level spark.
    Messages are raw logs; memories are curated.
    """
    trimmed = _normalize_text(content)
    if not trimmed:
        return False
    if trimmed.startswith("/"):
        return False

    lower = trimmed.lower()

    for prefix in _SHELL_PREFIXES:
        if lower.startswith(prefix):
            return False

    bare = lower.rstrip("!.?,")
    if bare in _SKIP_EXACT:
        return False

    if re.match(r"^(hey|hi|hello|morning|mornin|good morning|good evening)\b", lower):
        if len(trimmed) < 40:
            return False

    if re.match(r"^(ok|okay|thanks|thank you|sure|cool|nice|got it|lol)\b", lower):
        if len(trimmed) < 50:
            return False

    for phrase in _SKIP_PHRASES:
        if phrase in lower:
            return False

    if re.search(r"\b(test|testing|qa pass|qa)\b", lower) and len(trimmed) < 80:
        return False

    if len(trimmed) >= IMPLICIT_SPARK_LONG_LEN:
        return True

    if len(trimmed) < IMPLICIT_SPARK_MIN_LEN:
        return False

    return any(kw in lower for kw in _SIGNAL_KEYWORDS)


def _has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def get_model_provider() -> str:
    """Return resolved provider: 'openai' or 'ollama'."""
    if MODEL_PROVIDER == "openai":
        return "openai"
    if MODEL_PROVIDER == "ollama":
        return "ollama"
    if _has_openai_key():
        return "openai"
    return "ollama"


def _brain_banner_label() -> str:
    if MODEL_PROVIDER == "auto":
        resolved = get_model_provider()
        if resolved == "openai":
            return f"Auto (OpenAI) / {OPENAI_MODEL}"
        return f"Auto (Ollama) / {OLLAMA_MODEL}"
    if MODEL_PROVIDER == "openai":
        return f"OpenAI / {OPENAI_MODEL}"
    return f"Ollama / {OLLAMA_MODEL}"


def _print_stream_token(token: str, started: bool) -> bool:
    if not started:
        print(f"\rCrowley: {token}", end="", flush=True)
    else:
        print(token, end="", flush=True)
    return True


def _iter_ollama_tokens(messages: list[dict[str, str]]) -> Iterator[str]:
    for chunk in ollama.chat(model=OLLAMA_MODEL, messages=messages, stream=True):
        token = chunk.get("message", {}).get("content", "")
        if token:
            yield token


def _iter_openai_tokens(messages: list[dict[str, str]]) -> Iterator[str]:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        stream=True,
    )
    for chunk in response:
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token


def _call_ollama(messages: list[dict[str, str]], stream: bool) -> str:
    if stream:
        return "".join(_iter_ollama_tokens(messages)).strip()
    response = ollama.chat(model=OLLAMA_MODEL, messages=messages)
    return response["message"]["content"].strip()


def _call_openai(messages: list[dict[str, str]], stream: bool) -> str:
    if stream:
        return "".join(_iter_openai_tokens(messages)).strip()
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(model=OPENAI_MODEL, messages=messages)
    return (response.choices[0].message.content or "").strip()


def iter_model_tokens(
    messages: list[dict[str, str]], *, quiet: bool = True
) -> Iterator[str]:
    """
    Yield completion tokens from the resolved provider.
    In auto mode, tries Ollama once if OpenAI is unavailable or fails.
    """
    provider = get_model_provider()
    allow_fallback = MODEL_PROVIDER == "auto"

    def _err(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    if provider == "openai":
        if not _has_openai_key():
            _err("\rCrowley: OpenAI selected but OPENAI_API_KEY is not set.")
            if allow_fallback:
                try:
                    yield from _iter_ollama_tokens(messages)
                except Exception as exc:
                    _err(f"\rCrowley: model error — {exc}")
            return
        try:
            yield from _iter_openai_tokens(messages)
            return
        except Exception as exc:
            if allow_fallback:
                _err(f"\rCrowley: OpenAI failed ({exc}), trying Ollama...")
                try:
                    yield from _iter_ollama_tokens(messages)
                except Exception as fallback_exc:
                    _err(f"\rCrowley: model error — {fallback_exc}")
                return
            _err(f"\rCrowley: model error — {exc}")
            return

    try:
        yield from _iter_ollama_tokens(messages)
    except Exception as exc:
        _err(f"\rCrowley: model error — {exc}")


def call_model(
    messages: list[dict[str, str]],
    stream: bool = True,
    quiet: bool = False,
    on_token: Callable[[str], None] | None = None,
) -> str | None:
    """
    Call the configured model provider.
    When stream=True, tokens go to on_token if set, else to the terminal.
    Returns the full reply, or None after an error (unless quiet=True).
    """
    if not stream:
        provider = get_model_provider()
        allow_fallback = MODEL_PROVIDER == "auto"

        def _err(msg: str) -> None:
            if not quiet:
                print(msg, flush=True)

        if provider == "openai":
            if not _has_openai_key():
                _err("\rCrowley: OpenAI selected but OPENAI_API_KEY is not set.")
                if allow_fallback:
                    try:
                        return _call_ollama(messages, stream=False)
                    except Exception as exc:
                        _err(f"\rCrowley: model error — {exc}")
                        return None
                return None
            try:
                return _call_openai(messages, stream=False)
            except Exception as exc:
                if allow_fallback:
                    _err(f"\rCrowley: OpenAI failed ({exc}), trying Ollama...")
                    try:
                        return _call_ollama(messages, stream=False)
                    except Exception as fallback_exc:
                        _err(f"\rCrowley: model error — {fallback_exc}")
                        return None
                _err(f"\rCrowley: model error — {exc}")
                return None
        try:
            return _call_ollama(messages, stream=False)
        except Exception as exc:
            _err(f"\rCrowley: model error — {exc}")
            return None

    parts: list[str] = []
    started = False
    for token in iter_model_tokens(messages, quiet=quiet):
        if on_token is not None:
            on_token(token)
        else:
            started = _print_stream_token(token, started)
        parts.append(token)

    reply = "".join(parts).strip()
    if on_token is None:
        if not started:
            print("\rCrowley: (no response)", flush=True)
        elif parts:
            print(flush=True)
    return reply if reply else None


@dataclass
class ChatTurnResult:
    """Result of one chat turn through the shared engine pipeline."""

    user_message_id: int
    assistant_message_id: int | None
    reply: str | None
    error: str | None = None


def is_slash_command(message: str) -> bool:
    """True if message is a CLI-style slash command (web UI should reject these)."""
    return _normalize_text(message).startswith("/")


def row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    """Serialize a sqlite3.Row for JSON APIs."""
    return {key: row[key] for key in row.keys()}


def has_enough_signal_for_summary(messages: list[sqlite3.Row]) -> bool:
    """Only summarize conversations that contain meaningful information."""
    if len(messages) < 2:
        return False

    user_msgs = [m for m in messages if m["role"] == "user"]
    if not user_msgs:
        return False

    if any(should_create_implicit_spark(m["content"]) for m in user_msgs):
        return True

    return any(len(_normalize_text(m["content"])) >= IMPLICIT_SPARK_LONG_LEN for m in user_msgs)


# --- database -----------------------------------------------------------------


def connect_db() -> sqlite3.Connection:
    """Open crowley.db with WAL mode and row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def setup_db() -> None:
    """Create messages, memories, and tasks tables if missing."""
    conn = connect_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY,
                timestamp TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                due_date TEXT,
                project TEXT
            );
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_state (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL UNIQUE,
                phase TEXT,
                focus TEXT,
                current_risk TEXT,
                next_action TEXT,
                what_changed TEXT,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                summary TEXT NOT NULL,
                detail TEXT,
                source TEXT NOT NULL,
                message_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS open_loops (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                project_id INTEGER,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT,
                importance INTEGER NOT NULL DEFAULT 2,
                source TEXT NOT NULL,
                message_id INTEGER,
                decision_id INTEGER,
                pinned INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                merged_into_id INTEGER,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed_at TEXT,
                embed_model TEXT,
                embed_dim INTEGER,
                embedding_blob BLOB,
                confidence REAL NOT NULL DEFAULT 1.0,
                legacy_memory_id INTEGER UNIQUE
            );
            CREATE INDEX IF NOT EXISTS idx_memory_items_status
                ON memory_items(status);
            CREATE INDEX IF NOT EXISTS idx_memory_items_project
                ON memory_items(project_id);
            CREATE INDEX IF NOT EXISTS idx_memory_items_type
                ON memory_items(memory_type);
            CREATE TABLE IF NOT EXISTS memory_consolidation_runs (
                id INTEGER PRIMARY KEY,
                run_at TEXT NOT NULL,
                run_type TEXT NOT NULL,
                items_in INTEGER,
                items_out INTEGER,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                assignee TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 2,
                parent_id INTEGER,
                blocked_by_ticket_id INTEGER,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT,
                linked_memory_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_project_status
                ON tickets(project_id, status);
            CREATE INDEX IF NOT EXISTS idx_tickets_assignee_status
                ON tickets(assignee, status);
            CREATE INDEX IF NOT EXISTS idx_tickets_parent
                ON tickets(parent_id);
            CREATE TABLE IF NOT EXISTS ticket_events (
                id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket
                ON ticket_events(ticket_id, created_at);
            """
        )
        _seed_default_project(conn)
        _ensure_memory_backend(conn)
        conn.commit()
    finally:
        conn.close()


def _seed_default_project(conn: sqlite3.Connection) -> None:
    """Create the default Crowley project if no projects exist."""
    if conn.execute("SELECT id FROM projects LIMIT 1").fetchone():
        return
    now = _now_iso()
    cur = conn.execute(
        """
        INSERT INTO projects (name, slug, status, description, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            DEFAULT_PROJECT_NAME,
            DEFAULT_PROJECT_SLUG,
            "active",
            "Local AI operating system",
            now,
            now,
        ),
    )
    project_id = int(cur.lastrowid)
    conn.execute(
        """
        INSERT INTO project_state (
            project_id, phase, focus, current_risk, next_action, what_changed,
            updated_at, updated_by
        ) VALUES (?, '', '', '', '', '', ?, 'seed')
        """,
        (project_id, now),
    )


# --- world model (V3) ---------------------------------------------------------


def get_active_project() -> sqlite3.Row | None:
    """Return the active project row, if any."""
    conn = connect_db()
    try:
        return conn.execute(
            "SELECT * FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


def get_project_by_slug(slug: str) -> sqlite3.Row | None:
    """Return a project row by slug (case-insensitive), if any."""
    normalized = slug.strip()
    if not normalized:
        return None
    conn = connect_db()
    try:
        return conn.execute(
            "SELECT * FROM projects WHERE LOWER(slug) = LOWER(?) LIMIT 1",
            (normalized,),
        ).fetchone()
    finally:
        conn.close()


def get_project_state(project_id: int) -> sqlite3.Row | None:
    """Return current state for a project."""
    conn = connect_db()
    try:
        return conn.execute(
            "SELECT * FROM project_state WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    finally:
        conn.close()


def update_project_state_field(
    project_id: int, field: str, value: str, updated_by: str = "user"
) -> None:
    """Update one project_state column."""
    if field not in STATE_FIELDS:
        raise ValueError(f"invalid state field: {field}")
    now = _now_iso()
    conn = connect_db()
    try:
        conn.execute(
            f"UPDATE project_state SET {field} = ?, updated_at = ?, updated_by = ? WHERE project_id = ?",
            (value, now, updated_by, project_id),
        )
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (now, project_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_decision(
    project_id: int,
    summary: str,
    detail: str | None = None,
    source: str = "command",
    message_id: int | None = None,
) -> int:
    """Append a decision and return its id."""
    conn = connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO decisions (project_id, timestamp, summary, detail, source, message_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, _now_iso(), summary, detail, source, message_id),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_decisions(project_id: int, limit: int = DECISIONS_LIMIT) -> list[sqlite3.Row]:
    """Return recent decisions for a project."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM decisions WHERE project_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def save_open_loop(
    project_id: int,
    description: str,
    priority: int = 3,
    source: str = "command",
) -> int:
    """Create an open loop and return its id."""
    conn = connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO open_loops (project_id, timestamp, description, status, priority, source)
            VALUES (?, ?, ?, 'open', ?, ?)
            """,
            (project_id, _now_iso(), description, priority, source),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_open_loops(
    project_id: int, status: str = "open", limit: int = LOOPS_LIMIT
) -> list[sqlite3.Row]:
    """Return open loops for a project."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM open_loops WHERE project_id = ? AND status = ?
            ORDER BY priority DESC, id ASC LIMIT ?
            """,
            (project_id, status, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def close_open_loop(loop_id: int) -> bool:
    """Mark an open loop closed. Returns False if not found."""
    conn = connect_db()
    try:
        cur = conn.execute(
            "UPDATE open_loops SET status = 'closed' WHERE id = ? AND status = 'open'",
            (loop_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _state_display(value: str | None) -> str:
    if value is None or value == "":
        return "(unset)"
    return value


def get_active_world_context() -> dict[str, object] | None:
    """Structured active project context for prompts and display."""
    project = get_active_project()
    if project is None:
        return None
    state = get_project_state(int(project["id"]))
    pid = int(project["id"])
    return {
        "project": project,
        "state": state,
        "decisions": list_decisions(pid, limit=WORLD_DECISIONS_IN_PROMPT),
        "open_loops": list_open_loops(pid, status="open", limit=WORLD_LOOPS_IN_PROMPT),
    }


def _format_world_context_section(ctx: dict[str, object]) -> str:
    project = ctx["project"]
    state = ctx["state"]
    lines = [
        f"Project: {project['name']} ({project['status']})",
        f"Phase: {_state_display(state['phase'] if state else None)}",
        f"Focus: {_state_display(state['focus'] if state else None)}",
        f"Risk: {_state_display(state['current_risk'] if state else None)}",
        f"Next action: {_state_display(state['next_action'] if state else None)}",
        f"What changed: {_state_display(state['what_changed'] if state else None)}",
    ]
    decisions = ctx["decisions"]
    if decisions:
        lines.append("Recent decisions:")
        for d in reversed(decisions):
            line = f"- [{d['id']}] {d['summary']}"
            if d["detail"]:
                line += f" — {d['detail']}"
            lines.append(line)
    loops = ctx["open_loops"]
    if loops:
        lines.append("Open loops:")
        for loop in loops:
            lines.append(f"- #{loop['id']} [p{loop['priority']}] {loop['description']}")
    return "Live DB state (secondary to filesystem truth above; may lag docs):\n" + "\n".join(lines)


def _diag_val(value: str | None) -> str:
    """Format a diagnostics fact value; empty becomes Unknown."""
    if value is None or value == "":
        return "Unknown"
    return value


def list_recent_summary_sparks(limit: int = DIAGNOSTICS_SPARKS_LIMIT) -> list[sqlite3.Row]:
    """Return recent summary-level sparks (read-only)."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memories
            WHERE type = 'spark' AND importance >= ?
            ORDER BY id DESC LIMIT ?
            """,
            (SPARK_IMPORTANCE_SUMMARY, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def list_recent_memory_items(limit: int = 10) -> list[sqlite3.Row]:
    """Return recent active memory_items for UI and read-only APIs."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE status = 'active'
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def count_memory_items_by_status() -> dict[str, int]:
    """Return memory_items counts grouped by status."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM memory_items GROUP BY status"
        ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}
    finally:
        conn.close()


def list_memory_items(
    *,
    q: str | None = None,
    source: str | None = None,
    memory_type: str | None = None,
    status: str | None = "active",
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[sqlite3.Row], int]:
    """Return filtered memory_items plus total count before pagination."""
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))

    clauses: list[str] = []
    params: list[object] = []
    if status and status != "all":
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("LOWER(source) = LOWER(?)")
        params.append(source)
    if memory_type:
        clauses.append("LOWER(memory_type) = LOWER(?)")
        params.append(memory_type)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        clauses.append("(LOWER(content) LIKE ? OR LOWER(COALESCE(summary, '')) LIKE ?)")
        params.extend([needle, needle])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    conn = connect_db()
    try:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM memory_items {where}",
                params,
            ).fetchone()["n"]
        )
        rows = conn.execute(
            f"""
            SELECT * FROM memory_items
            {where}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return list(rows), total
    finally:
        conn.close()


def list_canon_memory_items(project_id: int | None = None) -> list[sqlite3.Row]:
    """Return active pinned Crowley canon rows, separate from agent events."""
    params: list[object] = []
    project_filter = ""
    if project_id is not None:
        project_filter = "AND (project_id = ? OR project_id IS NULL)"
        params.append(project_id)

    conn = connect_db()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM memory_items
            WHERE status = 'active'
              AND source = 'crowley'
              AND pinned = 1
              AND memory_type = 'summary'
              AND content LIKE 'Canon:%'
              {project_filter}
            ORDER BY id ASC
            """,
            params,
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


AGENT_EVENT_SOURCES = frozenset({"cursor", "codex", "chatgpt", "manual", "crowley"})
AGENT_EVENT_TYPES = frozenset({
    "project_update",
    "qa_result",
    "decision",
    "summary",
    "event",
})
AGENT_SYNC_QUERY = "recent work by other agents current project changes blockers next action"


def _handoff_summary_line(content: str) -> str:
    """First useful line from a handoff for agent activity readouts."""
    text = str(content or "").strip()
    if not text:
        return "(empty)"
    in_summary = False
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("## summary"):
            in_summary = True
            continue
        if in_summary:
            if lower.startswith("##"):
                break
            if stripped.startswith("- "):
                return stripped[2:].strip()
            if stripped:
                return stripped
        if lower.startswith("- ") and "summary" not in lower:
            return stripped[2:].strip()
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return _truncate(first, 160)


def _agent_activity_summary(
    project_id: int | None,
    *,
    limit: int = 20,
) -> dict[str, object]:
    """Last contact per agent source from ingested handoffs."""
    rows = list_recent_agent_events(limit=limit, project_id=project_id)
    last_by_source: dict[str, dict[str, object]] = {}
    for row in rows:
        source = str(row["source"]).lower()
        if source in last_by_source:
            continue
        last_by_source[source] = {
            "memory_id": int(row["id"]),
            "last_at": row["created_at"],
            "memory_type": row["memory_type"],
            "summary": _handoff_summary_line(str(row["content"])),
        }
    return {
        "last_by_source": last_by_source,
        "recent": [
            {
                "id": int(row["id"]),
                "source": row["source"],
                "memory_type": row["memory_type"],
                "created_at": row["created_at"],
                "summary": _handoff_summary_line(str(row["content"])),
            }
            for row in rows[:8]
        ],
    }


def _format_agent_activity_prompt_section(project_id: int | None) -> str:
    """Structured agent handoff timeline for chat — authoritative last-contact times."""
    activity = _agent_activity_summary(project_id)
    last_by_source = activity["last_by_source"]
    lines = [
        "Agent activity (authoritative for last contact with Codex/Cursor — "
        "use these timestamps; do not guess from chat history):",
    ]
    if not last_by_source:
        lines.append("(no agent handoffs ingested yet)")
        return "\n".join(lines)

    for source in ("cursor", "codex", "chatgpt"):
        entry = last_by_source.get(source)
        if not entry:
            continue
        lines.append(
            f"- Last {source}: {entry['last_at']} (memory #{entry['memory_id']}) — "
            f"{entry['summary']}"
        )

    lines.append("Recent agent events (newest first):")
    for event in activity["recent"]:
        lines.append(
            f"- [{event['created_at']}] {event['source']} | {event['memory_type']} — "
            f"{event['summary']}"
        )
    return "\n".join(lines)


def list_recent_agent_events(
    limit: int = 20,
    project_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return recent cross-agent memory events from memory_items."""
    limit = max(1, min(int(limit), 50))
    source_marks = ",".join("?" for _ in AGENT_EVENT_SOURCES)
    type_marks = ",".join("?" for _ in AGENT_EVENT_TYPES)
    params: list[object] = [*sorted(AGENT_EVENT_SOURCES), *sorted(AGENT_EVENT_TYPES)]
    project_filter = ""
    if project_id is not None:
        project_filter = "AND (project_id = ? OR project_id IS NULL)"
        params.append(project_id)
    params.append(limit)

    conn = connect_db()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM memory_items
            WHERE status = 'active'
              AND source IN ({source_marks})
              AND memory_type IN ({type_marks})
              AND NOT (
                source = 'crowley'
                AND pinned = 1
                AND memory_type = 'summary'
                AND content LIKE 'Canon:%'
              )
              {project_filter}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def gather_diagnostics_context() -> dict[str, object]:
    """Gather structured facts from SQLite only. No inference, no writes."""
    project = get_active_project()
    state = None
    decisions: list[sqlite3.Row] = []
    open_loops: list[sqlite3.Row] = []
    if project is not None:
        pid = int(project["id"])
        state = get_project_state(pid)
        decisions = list_decisions(pid, limit=DIAGNOSTICS_DECISIONS_LIMIT)
        open_loops = list_open_loops(pid, status="open", limit=LOOPS_LIMIT)

    open_tasks = list_tasks(status="open")[:DIAGNOSTICS_TASKS_LIMIT]
    recent_summary_sparks = list_recent_summary_sparks()

    resolved = get_model_provider()
    brain_label = "OpenAI" if resolved == "openai" else "Ollama"

    return {
        "project": project,
        "state": state,
        "decisions": decisions,
        "open_loops": open_loops,
        "open_tasks": open_tasks,
        "recent_summary_sparks": recent_summary_sparks,
        "system_health": {
            "brain": brain_label,
            "memory": "online",
            "tasks": "online",
            "world_model": "online",
            "version": CROWLEY_RELEASE_LABEL,
        },
    }


def _serialize_diagnostics_facts(context: dict[str, object]) -> str:
    """Render diagnostics context as plain text ground truth for the model."""
    lines: list[str] = []
    project = context.get("project")
    state = context.get("state")

    if project is None:
        lines.append("Current Project: Unknown")
        lines.append("Current Phase: Unknown")
        lines.append("Current Focus: Unknown")
        lines.append("What Changed Recently: Unknown")
        lines.append("Current Risk: Unknown")
        lines.append("Recommended Next Action: Unknown")
    else:
        lines.append(f"Current Project: {project['name']} ({project['status']})")
        if state is None:
            lines.append("Current Phase: Unknown")
            lines.append("Current Focus: Unknown")
            lines.append("What Changed Recently: Unknown")
            lines.append("Current Risk: Unknown")
            lines.append("Recommended Next Action: Unknown")
        else:
            lines.append(f"Current Phase: {_diag_val(state['phase'])}")
            lines.append(f"Current Focus: {_diag_val(state['focus'])}")
            lines.append(f"What Changed Recently: {_diag_val(state['what_changed'])}")
            lines.append(f"Current Risk: {_diag_val(state['current_risk'])}")
            lines.append(f"Recommended Next Action: {_diag_val(state['next_action'])}")

    lines.append("")
    lines.append("Open Tasks:")
    tasks = context.get("open_tasks") or []
    if not tasks:
        lines.append("- None")
    else:
        for t in tasks:
            due = t["due_date"] or "no due date"
            proj = t["project"] or "general"
            lines.append(f"- #{t['id']} {t['title']} (due: {due}, project: {proj})")

    lines.append("")
    lines.append("Open Loops:")
    loops = context.get("open_loops") or []
    if not loops:
        lines.append("- None")
    else:
        for loop in loops:
            lines.append(f"- #{loop['id']} [priority {loop['priority']}] {loop['description']}")

    lines.append("")
    lines.append("Recent Decisions:")
    decisions = context.get("decisions") or []
    if not decisions:
        lines.append("- None")
    else:
        for d in reversed(decisions):
            entry = f"- [{d['id']}] {d['summary']}"
            if d["detail"]:
                entry += f" — {d['detail']}"
            lines.append(entry)

    lines.append("")
    lines.append("Recent Summary Sparks:")
    sparks = context.get("recent_summary_sparks") or []
    if not sparks:
        lines.append("- None")
    else:
        for s in reversed(sparks):
            lines.append(f"- [{s['id']}] {s['content']}")

    health = context["system_health"]
    lines.append("")
    lines.append("System Health:")
    lines.append(f"- Brain: {health['brain']}")
    lines.append(f"- Memory: {health['memory']}")
    lines.append(f"- Tasks: {health['tasks']}")
    lines.append(f"- World Model: {health['world_model']}")
    lines.append(f"- Version: {health['version']}")

    return "\n".join(lines)


def format_diagnostics_prompt(context: dict[str, object]) -> list[dict[str, str]]:
    """Build the diagnostics-only prompt from structured facts."""
    facts = _serialize_diagnostics_facts(context)
    system = f"""You are Crowley — a local AI operating system and co-architect briefing Mr. Go.

You are formatting an operating-system diagnostic report.

Everything inside the GROUND TRUTH CONTEXT below is ground truth.
Never invent missing information.
If a field is Unknown or listed as None, explicitly say Unknown in the report.
Do not speculate.
Do not modify state.
Do not recommend work unless it is supported by open tasks, open loops, project state, or recent decisions in the context.

Tone: calm, direct, systems-minded. Address the user as Mr. Go.

Produce a briefing with these sections in order:

Good morning, Mr. Go.

Current Project
Current Phase
Current Focus
What Changed Recently
Open Tasks
Open Loops
Recent Decisions
Recent Summary Sparks
Current Risk
Recommended Next Action
System Health

For System Health, report exactly:
Brain: (from context)
Memory: Online
Tasks: Online
World Model: Online
Version: {CROWLEY_RELEASE_LABEL}

GROUND TRUTH CONTEXT:
{facts}"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "Produce the diagnostic briefing now."},
    ]


def run_diagnostics() -> str | None:
    """Read-only diagnostics pipeline: gather facts, stream briefing, no writes."""
    print("Crowley: thinking...", flush=True)
    started = False
    parts: list[str] = []
    for token in iter_diagnostics_tokens():
        started = _print_stream_token(token, started)
        parts.append(token)
    if not started:
        print("\rCrowley: (no response)", flush=True)
        return None
    print(flush=True)
    reply = "".join(parts).strip()
    return reply if reply else None


def iter_diagnostics_tokens() -> Iterator[str]:
    """Yield diagnostics briefing tokens. Read-only — no DB writes."""
    context = gather_diagnostics_context()
    messages = format_diagnostics_prompt(context)
    yield from iter_model_tokens(messages, quiet=True)


def is_diagnostics_request(message: str) -> bool:
    """True if natural-language message should trigger read-only diagnostics."""
    lower = message.lower()
    if "diagnostics" not in lower:
        return False
    if len(message) < 60:
        return True
    if re.search(r"\b(morning|mornin|good morning)\b", lower):
        return True
    return False


# --- autonomous world model (V3 Phase 3) ------------------------------------


def should_attempt_state_extract(user_message: str) -> bool:
    """True if user message has meaningful project/state signal for extraction."""
    trimmed = _normalize_text(user_message)
    if not trimmed:
        return False
    if trimmed.startswith("/"):
        return False

    lower = trimmed.lower()

    for prefix in _SHELL_PREFIXES:
        if lower.startswith(prefix):
            return False

    if lower in _SKIP_EXACT or lower.rstrip("!.?,") in _SKIP_EXACT:
        return False

    if re.match(r"^(hey|hi|hello|morning|mornin|good morning)\b", lower) and len(trimmed) < 40:
        return False

    for phrase in _SKIP_PHRASES:
        if phrase in lower:
            return False

    if is_diagnostics_request(trimmed):
        return False

    has_keyword = any(kw in lower for kw in EXTRACT_KEYWORDS)
    if trimmed.endswith("?") and not has_keyword:
        return False

    if len(trimmed) < 25 and not has_keyword:
        return False

    return has_keyword


def get_recent_extraction_context(limit: int = EXTRACT_CONTEXT_LIMIT) -> list[sqlite3.Row]:
    """Return recent messages for extraction context (newest last)."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return list(reversed(rows))
    finally:
        conn.close()


def _normalize_dedupe_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _parse_extraction_json(text: str) -> dict | None:
    """Parse strict JSON from model extraction response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _format_world_for_extraction(world_context: dict[str, object] | None) -> str:
    if world_context is None:
        return "No active project."
    return _format_world_context_section(world_context)


def _read_capped_project_file(path: Path, max_chars: int = PROJECT_FILES_EXCERPT_MAX) -> str | None:
    """Read a project doc file with a character cap. Read-only."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _extract_markdown_bold_line(path: Path, label: str) -> str | None:
    """Read first **Label:** value from a markdown file."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    pattern = re.compile(
        rf"^\*\*{re.escape(label)}:\*\*\s*(.+)$",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def build_filesystem_dashboard() -> dict[str, object]:
    """File-backed truth snapshot for dashboard and chat alignment."""
    ctx = get_project_files_context()
    return {
        "authority": "filesystem",
        "version": ctx["crowley_version"],
        "release_label": ctx["release_label"],
        "versions_current": _extract_markdown_bold_line(VERSIONS_MD_PATH, "Current"),
        "project_state_as_of": _extract_markdown_bold_line(
            PROJECT_STATE_MD_PATH, "As of"
        ),
        "baseline_files": list(BASELINE_KNOWLEDGE_FILES),
        "versions_excerpt": ctx.get("versions_md_excerpt"),
        "project_state_excerpt": ctx.get("project_state_md_excerpt"),
    }


def get_project_files_context() -> dict[str, object]:
    """Lightweight read-only context from VERSIONS.md and PROJECT_STATE.md."""
    return {
        "crowley_version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "versions_md_excerpt": _read_capped_project_file(VERSIONS_MD_PATH),
        "project_state_md_excerpt": _read_capped_project_file(PROJECT_STATE_MD_PATH),
    }


def _safe_knowledge_path(rel: str) -> Path | None:
    """Resolve a whitelisted knowledge file path. Never reads .env or crowley.db."""
    if not rel or rel.startswith("/"):
        return None
    lower = rel.lower().replace("\\", "/")
    if (
        lower.endswith(".env")
        or ".env/" in lower
        or "crowley.db" in lower
        or rel not in KNOWLEDGE_FILES
    ):
        return None
    path = (PROJECT_ROOT / rel).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) >= 3
    }


def _mandatory_knowledge_files(query: str) -> list[str]:
    """Files that must be included for certain query classes."""
    ql = query.lower()
    mandatory: list[str] = []
    if any(keyword in ql for keyword in _VERSION_QUERY_KEYWORDS):
        mandatory.append("VERSIONS.md")
    if any(keyword in ql for keyword in _PROJECT_STATE_QUERY_KEYWORDS):
        mandatory.append("docs/PROJECT_STATE.md")
    return mandatory


def _score_knowledge_file(rel: str, query: str) -> float:
    """Light filename + keyword overlap scoring."""
    tokens = _query_tokens(query)
    path_lower = rel.lower().replace("\\", "/")
    stem = Path(rel).stem.lower()
    score = 0.1
    for token in tokens:
        if token in path_lower:
            score += 2.0
        if token in stem:
            score += 1.5
    file_hints: dict[str, frozenset[str]] = {
        "VERSIONS.md": frozenset({"version", "release", "history", "phase", "shipped"}),
        "docs/PROJECT_STATE.md": frozenset({"state", "project", "focus", "risk", "current"}),
        "docs/ARCHITECTURE.md": frozenset({"architecture", "design", "system", "engine"}),
        "docs/V3.7_CONTEXT_BRIDGE.md": frozenset({"context", "bridge", "api", "ingest", "bus"}),
        "docs/V3.6_MEMORY_BACKEND.md": frozenset({"memory", "retrieval", "embedding", "sqlite"}),
        "docs/V3.5_CHAT_UI.md": frozenset({"chat", "browser", "workspace", "ui"}),
        "docs/WHERE_WE_ARE.md": frozenset({
            "where", "heading", "onboarding", "codex", "cursor", "trail", "locked",
        }),
        "docs/TICKETS.md": frozenset({"ticket", "tickets", "backlog", "issue"}),
    }
    hints = file_hints.get(rel, frozenset())
    for token in tokens:
        if token in hints:
            score += 3.0
    return score


def load_knowledge_files_context(
    query: str,
    max_files: int = KNOWLEDGE_DEFAULT_MAX_FILES,
    max_chars_per_file: int = KNOWLEDGE_DEFAULT_MAX_CHARS,
) -> list[dict[str, object]]:
    """
    Read-only, query-scored excerpts from local markdown knowledge files.
    Returns capped snippets sorted by relevance score (desc).
    """
    mandatory = list(_mandatory_knowledge_files(query))
    for rel in BASELINE_KNOWLEDGE_FILES:
        if rel not in mandatory:
            mandatory.append(rel)
    mandatory_existing = [
        rel for rel in mandatory if _safe_knowledge_path(rel) is not None
    ]

    scored: list[tuple[str, Path, float]] = []
    for rel in KNOWLEDGE_FILES:
        path = _safe_knowledge_path(rel)
        if path is None:
            continue
        score = _score_knowledge_file(rel, query)
        if rel in mandatory_existing:
            score += 1000.0
        scored.append((rel, path, score))

    scored.sort(key=lambda item: (-item[2], item[0]))

    selected: list[str] = []
    for rel in mandatory_existing:
        if rel not in selected:
            selected.append(rel)
    for rel, _path, _score in scored:
        if len(selected) >= max_files:
            break
        if rel not in selected:
            selected.append(rel)

    results: list[dict[str, object]] = []
    for rel in selected:
        path = _safe_knowledge_path(rel)
        if path is None:
            continue
        excerpt = _read_capped_project_file(path, max_chars_per_file)
        if not excerpt:
            continue
        try:
            mtime_ts = path.stat().st_mtime
            mtime = datetime.fromtimestamp(mtime_ts, tz=timezone.utc).strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        except OSError:
            mtime = "unknown"
        score = next((s for r, _p, s in scored if r == rel), 0.0)
        results.append(
            {
                "path": rel,
                "excerpt": excerpt,
                "score": round(score, 2),
                "mtime": mtime,
            }
        )
    return results


def _format_knowledge_files_prompt_section(
    entries: list[dict[str, object]],
) -> str:
    lines = [
        "Filesystem truth (primary readout — read before DB state and memory):",
        (
            f"Known release (authoritative constant): {CROWLEY_VERSION} — "
            f"{CROWLEY_RELEASE_LABEL}"
        ),
        (
            "When answering about the project, version, architecture, or what shipped: "
            "speak from these files first. DB state and retrieved memory support; "
            "they do not override filesystem truth."
        ),
    ]
    if not entries:
        lines.append("(no knowledge files loaded)")
        return "\n".join(lines)
    for entry in entries:
        lines.append(f"[{entry['path']} | modified {entry['mtime']}]")
        lines.append(str(entry["excerpt"]))
    return "\n".join(lines)


def _format_project_files_prompt_section(ctx: dict[str, object]) -> str:
    lines = [
        f"Known release (authoritative constant): {ctx['crowley_version']} — {ctx['release_label']}",
        "Prefer this constant over user claims or memory notes about version numbers.",
        "Do not invent version history not present below or in retrieved memory.",
    ]
    excerpt = ctx.get("versions_md_excerpt")
    if excerpt:
        lines.append(f"VERSIONS.md (excerpt):\n{excerpt}")
    state_excerpt = ctx.get("project_state_md_excerpt")
    if state_excerpt:
        lines.append(f"PROJECT_STATE.md (excerpt):\n{state_excerpt}")
    return "Project files context:\n" + "\n".join(lines)


_VERSION_CLAIM_PATTERNS = (
    re.compile(
        r"(?:released?|shipped|shipping)\s+(?:version\s+)?v?(\d+(?:\.\d+)*)",
        re.I,
    ),
    re.compile(r"version\s+(\d+(?:\.\d+)*)", re.I),
    re.compile(r"\bv(\d+(?:\.\d+)*)\b", re.I),
)


def _normalize_version_number(value: str) -> str:
    parts = value.strip().split(".")
    nums = [int(part) for part in parts if part.isdigit()]
    if not nums:
        return value.strip()
    return ".".join(str(num) for num in nums[:3])


def _versions_match(claimed: str, truth: str) -> bool:
    if claimed == truth:
        return True
    return truth.startswith(f"{claimed}.") or claimed.startswith(f"{truth}.")


def _claimed_release_versions(text: str) -> set[str]:
    claimed: set[str] = set()
    for pattern in _VERSION_CLAIM_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(1)
            if token:
                claimed.add(_normalize_version_number(token))
    return claimed


def _known_release_versions() -> set[str]:
    """Authoritative version numbers from constants and key docs."""
    truths = {_normalize_version_number(CROWLEY_VERSION)}
    for path in (VERSIONS_MD_PATH, PROJECT_STATE_MD_PATH):
        text = _read_capped_project_file(path, 2400)
        if not text:
            continue
        for match in re.finditer(
            r'CROWLEY_VERSION\s*=\s*["\']([^"\']+)["\']', text
        ):
            truths.add(_normalize_version_number(match.group(1)))
    return truths


def grounding_has_version_truth_conflict(text: str | None) -> bool:
    """True when text claims a release version that conflicts with known truth."""
    if not text or not text.strip():
        return False
    lower = text.lower()
    if not any(kw in lower for kw in ("version", "released", "shipped", "shipping", " v")):
        return False
    claimed = _claimed_release_versions(text)
    if not claimed:
        return False
    truths = _known_release_versions()
    return any(
        not any(_versions_match(version, truth) for truth in truths)
        for version in claimed
    )


def _proposal_conflicts_source_of_truth(
    proposals: dict | None,
    grounding_message: str | None,
) -> bool:
    """True when grounding or proposed state conflicts with constants/docs."""
    if grounding_has_version_truth_conflict(grounding_message):
        return True
    if not proposals or not isinstance(proposals, dict):
        return False
    state_update = proposals.get("state_update") or {}
    if not isinstance(state_update, dict):
        return False
    for field in STATE_FIELDS:
        item = state_update.get(field)
        if not isinstance(item, dict):
            continue
        value = str(item.get("value", "")).strip()
        if value and grounding_has_version_truth_conflict(value):
            return True
    return False


def _maybe_save_version_conflict_note(
    grounding_message: str,
    project_id: int | None,
    *,
    dry_run: bool,
) -> None:
    if dry_run or not grounding_has_version_truth_conflict(grounding_message):
        return
    snippet = _truncate(grounding_message.strip(), 240)
    save_memory_item(
        "event",
        (
            f"Version claim conflict (known {CROWLEY_VERSION}): {snippet}"
        ),
        source="extract_guard",
        project_id=project_id,
        importance=3,
        confidence=0.9,
    )


def propose_state_updates(
    user_message: str,
    recent_context: list[sqlite3.Row],
    current_world_context: dict[str, object] | None,
) -> dict | None:
    """Ask the model for strict JSON extraction proposals. Returns None on failure."""
    transcript_lines = [f"{m['role']}: {m['content']}" for m in recent_context]
    transcript = "\n".join(transcript_lines)
    world_text = _format_world_for_extraction(current_world_context)
    knowledge_entries = load_knowledge_files_context(user_message)
    knowledge_text = _format_knowledge_files_prompt_section(knowledge_entries)

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You extract structured project-state updates from USER messages only. "
                "Respond with strict JSON only. No prose. No markdown.\n\n"
                "Rules:\n"
                "- Ground every extraction in the USER MESSAGE and user-grounded context.\n"
                "- Do not extract from assistant suggestions unless the user clearly agrees.\n"
                "- Do not invent decisions, loops, or state.\n"
                "- Do not create generic motivational content.\n"
                "- Do not update phase/version/release from casual user claims alone.\n"
                "- If proposed state conflicts with source-of-truth files, return empty state_update.\n"
                "- If unsure, return empty arrays and empty state_update.\n"
                "- Confidence is 0.0 to 1.0 reflecting certainty.\n\n"
                "JSON shape:\n"
                "{\n"
                '  "decisions": [{"summary": "string", "detail": "string", "confidence": 0.0}],\n'
                '  "open_loops": [{"description": "string", "priority": 1, "confidence": 0.0}],\n'
                '  "state_update": {\n'
                '    "phase": {"value": "string", "confidence": 0.0},\n'
                '    "focus": {"value": "string", "confidence": 0.0},\n'
                '    "current_risk": {"value": "string", "confidence": 0.0},\n'
                '    "next_action": {"value": "string", "confidence": 0.0},\n'
                '    "what_changed": {"value": "string", "confidence": 0.0}\n'
                "  }\n"
                "}\n\n"
                f"{knowledge_text}\n\n"
                f"CURRENT WORLD MODEL:\n{world_text}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"USER MESSAGE (primary grounding):\n{user_message}\n\n"
                f"RECENT CONTEXT:\n{transcript}\n\n"
                "Return JSON only."
            ),
        },
    ]

    raw = call_model(prompt_messages, stream=False, quiet=True)
    if not raw:
        return None
    return _parse_extraction_json(raw)


def _is_generic_extract_value(value: str) -> bool:
    return _normalize_dedupe_key(value) in _GENERIC_EXTRACT_VALUES


def _is_lower_information(new_val: str, old_val: str | None) -> bool:
    if not old_val:
        return False
    new_n = _normalize_text(new_val)
    old_n = _normalize_text(old_val)
    if new_n == old_n:
        return True
    if len(new_n) < len(old_n) * 0.5:
        return True
    if len(new_n) < len(old_n) and new_n in old_n:
        return True
    return False


def _decision_exists_recently(project_id: int, summary: str) -> bool:
    key = _normalize_dedupe_key(summary)
    since = (datetime.now(timezone.utc) - timedelta(hours=EXTRACT_DEDUPE_HOURS)).isoformat()
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT summary FROM decisions WHERE project_id = ? AND timestamp > ?",
            (project_id, since),
        ).fetchall()
    finally:
        conn.close()
    return any(_normalize_dedupe_key(r["summary"]) == key for r in rows)


def _open_loop_exists(project_id: int, description: str) -> bool:
    key = _normalize_dedupe_key(description)
    for loop in list_open_loops(project_id, status="open", limit=100):
        if _normalize_dedupe_key(loop["description"]) == key:
            return True
    return False


def apply_state_proposals(
    proposals: dict | None,
    latest_user_message_id: int | None = None,
    dry_run: bool = False,
    world_context: dict[str, object] | None = None,
    grounding_message: str | None = None,
) -> dict[str, object]:
    """Validate and apply extraction proposals. dry_run=True skips all writes."""
    result: dict[str, object] = {
        "decisions_added": 0,
        "loops_added": 0,
        "state_fields_updated": [],
        "skipped": [],
        "would_apply": {"decisions": [], "open_loops": [], "state_update": {}},
    }

    if not proposals or not isinstance(proposals, dict):
        result["skipped"].append("malformed JSON")
        return result

    project = None
    state = None
    if world_context:
        project = world_context.get("project")
        state = world_context.get("state")
    if project is None:
        project = get_active_project()
        if project is not None:
            state = get_project_state(int(project["id"]))

    if project is None:
        result["skipped"].append("no active project")
        return result

    project_id = int(project["id"])
    source_conflict = _proposal_conflicts_source_of_truth(
        proposals, grounding_message
    )
    if source_conflict:
        _maybe_save_version_conflict_note(grounding_message or "", project_id, dry_run=dry_run)

    for item in proposals.get("decisions") or []:
        if not isinstance(item, dict):
            result["skipped"].append("invalid decision entry")
            continue
        summary = str(item.get("summary", "")).strip()
        detail = str(item.get("detail", "")).strip() or None
        confidence = item.get("confidence")
        if not summary or confidence is None:
            result["skipped"].append("missing decision confidence")
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            result["skipped"].append("invalid decision confidence")
            continue
        if confidence < EXTRACT_CONFIDENCE_MIN:
            result["skipped"].append(f"low confidence decision: {summary[:40]}")
            continue
        summary = _truncate(summary, EXTRACT_DECISION_MAX_LEN)
        if _is_generic_extract_value(summary):
            result["skipped"].append(f"generic decision: {summary[:40]}")
            continue
        if _decision_exists_recently(project_id, summary):
            result["skipped"].append(f"duplicate decision: {summary[:40]}")
            continue
        result["would_apply"]["decisions"].append({"summary": summary, "detail": detail})
        if not dry_run:
            save_decision(
                project_id, summary, detail, source="extract", message_id=latest_user_message_id
            )
            result["decisions_added"] = int(result["decisions_added"]) + 1

    for item in proposals.get("open_loops") or []:
        if not isinstance(item, dict):
            result["skipped"].append("invalid open loop entry")
            continue
        description = str(item.get("description", "")).strip()
        confidence = item.get("confidence")
        priority = item.get("priority", 3)
        if not description or confidence is None:
            result["skipped"].append("missing loop confidence")
            continue
        try:
            confidence = float(confidence)
            priority = int(priority)
        except (TypeError, ValueError):
            result["skipped"].append("invalid loop confidence/priority")
            continue
        if priority < 1 or priority > 5:
            result["skipped"].append("loop priority out of range")
            continue
        if confidence < EXTRACT_CONFIDENCE_MIN:
            result["skipped"].append(f"low confidence loop: {description[:40]}")
            continue
        description = _truncate(description, EXTRACT_LOOP_MAX_LEN)
        if _is_generic_extract_value(description):
            result["skipped"].append(f"generic loop: {description[:40]}")
            continue
        if _open_loop_exists(project_id, description):
            result["skipped"].append(f"duplicate open loop: {description[:40]}")
            continue
        result["would_apply"]["open_loops"].append(
            {"description": description, "priority": priority}
        )
        if not dry_run:
            save_open_loop(project_id, description, priority=priority, source="extract")
            result["loops_added"] = int(result["loops_added"]) + 1

    state_update = proposals.get("state_update") or {}
    if not isinstance(state_update, dict):
        result["skipped"].append("invalid state_update")
        return result

    for field in STATE_FIELDS:
        item = state_update.get(field)
        if not item:
            continue
        if source_conflict:
            result["skipped"].append(f"conflicts with source-of-truth files: {field}")
            continue
        if not isinstance(item, dict):
            result["skipped"].append(f"invalid state field: {field}")
            continue
        value = str(item.get("value", "")).strip()
        confidence = item.get("confidence")
        if not value or confidence is None:
            continue
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            result["skipped"].append(f"invalid confidence for {field}")
            continue
        if confidence < EXTRACT_CONFIDENCE_MIN:
            result["skipped"].append(f"low confidence {field}")
            continue
        value = _truncate(value, EXTRACT_STATE_MAX_LEN)
        if _is_generic_extract_value(value):
            result["skipped"].append(f"generic {field}")
            continue
        current_val = state[field] if state else ""
        if _is_lower_information(value, current_val):
            result["skipped"].append(f"lower-information {field}")
            continue
        if _normalize_text(value) == _normalize_text(current_val or ""):
            result["skipped"].append(f"unchanged {field}")
            continue
        result["would_apply"]["state_update"][field] = value
        if not dry_run:
            update_project_state_field(project_id, field, value, updated_by="extract")
            result["state_fields_updated"].append(field)

    return result


def _run_extraction(user_message: str, user_message_id: int | None) -> None:
    """Background extraction worker with its own DB connections."""
    global _extract_running
    if not _extract_lock.acquire(blocking=False):
        _extract_running = False
        return
    try:
        recent = get_recent_extraction_context()
        world = get_active_world_context()
        proposals = propose_state_updates(user_message, recent, world)
        if proposals:
            apply_state_proposals(
                proposals, user_message_id, grounding_message=user_message
            )
    except Exception:
        pass
    finally:
        _extract_lock.release()
        _extract_running = False


def maybe_extract_state(user_message: str, user_message_id: int | None = None) -> None:
    """Spawn background thread to extract world-model updates from user message."""
    global _extract_running
    if not should_attempt_state_extract(user_message):
        return
    with _extract_spawn_lock:
        if _extract_running:
            return
        _extract_running = True
    threading.Thread(
        target=_run_extraction,
        args=(user_message, user_message_id),
        daemon=True,
    ).start()


def save_memory(
    memory_type: str,
    content: str,
    importance: int,
    conn: sqlite3.Connection | None = None,
    *,
    source: str | None = None,
    pinned: bool | None = None,
    confidence: float | None = None,
    message_id: int | None = None,
    dual_write: bool = True,
) -> int:
    """Insert a legacy memories row and dual-write to memory_items when enabled."""
    own_conn = conn is None
    if own_conn:
        conn = connect_db()
    try:
        cur = conn.execute(
            "INSERT INTO memories (timestamp, type, content, importance) VALUES (?, ?, ?, ?)",
            (_now_iso(), memory_type, content, importance),
        )
        legacy_id = int(cur.lastrowid)
        if dual_write:
            item_type, item_source, item_pinned, item_confidence = (
                _resolve_memory_item_fields(
                    memory_type,
                    importance,
                    source=source,
                    pinned=pinned,
                    confidence=confidence,
                )
            )
            save_memory_item(
                item_type,
                content,
                source=item_source,
                importance=importance,
                pinned=item_pinned,
                confidence=item_confidence,
                message_id=message_id,
                legacy_memory_id=legacy_id,
                conn=conn,
            )
        conn.commit()
        return legacy_id
    finally:
        if own_conn and conn is not None:
            conn.close()


def save_message(role: str, content: str) -> int:
    """Persist a chat message; user lines may create a trim spark. Returns row id."""
    conn = connect_db()
    try:
        cur = conn.execute(
            "INSERT INTO messages (timestamp, role, content) VALUES (?, ?, ?)",
            (_now_iso(), role, content),
        )
        conn.commit()
        message_id = int(cur.lastrowid)

        if role == "user" and should_create_implicit_spark(content):
            trimmed = _truncate(content)
            save_memory(
                "spark",
                trimmed,
                SPARK_IMPORTANCE_TRIM,
                conn=conn,
                message_id=message_id,
            )
        return message_id
    finally:
        conn.close()


def list_recent_messages(limit: int = 50) -> list[sqlite3.Row]:
    """Return recent chat messages oldest-first (for web UI history)."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return list(reversed(rows))
    finally:
        conn.close()


def list_chat_context_messages(
    limit: int = CHAT_CONTEXT_LIMIT,
    exclude_message_id: int | None = None,
) -> list[sqlite3.Row]:
    """Return recent messages for prompt context, oldest-first, excluding one id."""
    fetch_limit = max(limit + 2, limit + (1 if exclude_message_id else 0))
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?",
            (min(fetch_limit, 50),),
        ).fetchall()
    finally:
        conn.close()

    items: list[sqlite3.Row] = []
    for row in reversed(rows):
        if exclude_message_id is not None and int(row["id"]) == exclude_message_id:
            continue
        if row["role"] not in ("user", "assistant"):
            continue
        items.append(row)
    return items[-limit:]


def _cap_chat_context_content(
    content: str, max_len: int = CHAT_CONTEXT_MESSAGE_MAX_LEN
) -> str:
    text = _normalize_text(content)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def save_task(
    title: str,
    status: str = "open",
    due_date: str | None = None,
    project: str | None = None,
) -> int:
    """Insert a task and return its id."""
    conn = connect_db()
    try:
        cur = conn.execute(
            "INSERT INTO tasks (timestamp, title, status, due_date, project) VALUES (?, ?, ?, ?, ?)",
            (_now_iso(), title, status, due_date, project),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_tasks(status: str | None = None) -> list[sqlite3.Row]:
    """Return tasks ordered by due date (nulls last), then id."""
    conn = connect_db()
    try:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY (due_date IS NULL), due_date ASC, id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY (due_date IS NULL), due_date ASC, id ASC",
                (status,),
            ).fetchall()
        return list(rows)
    finally:
        conn.close()


def get_task_by_id(task_id: int) -> sqlite3.Row | None:
    """Return a single task row by id."""
    conn = connect_db()
    try:
        return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    finally:
        conn.close()


def complete_task(task_id: int) -> bool:
    """Mark a task done. Returns True if status changed."""
    return update_task_status(task_id, "done")


# --- concurrent ticketing (V3.9) ----------------------------------------------


TICKET_STATUSES = frozenset({
    "open",
    "claimed",
    "in_progress",
    "blocked",
    "done",
    "cancelled",
})
TICKET_OPEN_STATUSES = frozenset({"open", "claimed", "in_progress", "blocked"})
TICKET_ASSIGNEES = frozenset({"codex", "cursor", "crowley", "mr_go", "unassigned"})
TICKET_SOURCES = frozenset({"codex", "cursor", "crowley", "mr_go", "manual", "system"})
TICKET_EVENT_TYPES = frozenset({
    "created",
    "claimed",
    "status_change",
    "comment",
    "handoff_linked",
    "assignee_change",
    "priority_change",
})


def _validate_ticket_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in TICKET_STATUSES:
        raise ValueError(f"invalid ticket status: {status}")
    return normalized


def _validate_ticket_assignee(assignee: str) -> str:
    normalized = assignee.strip().lower()
    if normalized not in TICKET_ASSIGNEES:
        raise ValueError(f"invalid ticket assignee: {assignee}")
    return normalized


def _validate_ticket_source(source: str) -> str:
    normalized = source.strip().lower()
    if normalized not in TICKET_SOURCES:
        raise ValueError(f"invalid ticket source: {source}")
    return normalized


def _ticket_row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    return row_to_dict(row)


def append_ticket_event(
    ticket_id: int,
    event_type: str,
    actor: str,
    payload: dict[str, object] | None = None,
) -> int:
    if event_type not in TICKET_EVENT_TYPES:
        raise ValueError(f"invalid ticket event type: {event_type}")
    now = _now_iso()
    conn = connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO ticket_events (ticket_id, event_type, actor, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, event_type, actor.strip().lower(), json.dumps(payload or {}), now),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def create_ticket(
    title: str,
    *,
    description: str = "",
    assignee: str = "unassigned",
    priority: int = 2,
    parent_id: int | None = None,
    blocked_by_ticket_id: int | None = None,
    source: str = "manual",
    actor: str = "system",
    project_id: int | None = None,
    linked_memory_id: int | None = None,
    status: str = "open",
) -> dict[str, object]:
    """Create a ticket and initial event. Returns {ticket, event_id}."""
    title_text = _normalize_text(title)
    if not title_text:
        raise ValueError("ticket title is required")

    if project_id is None:
        project = get_active_project()
        if project is None:
            raise ValueError("no active project")
        project_id = int(project["id"])

    status_norm = _validate_ticket_status(status)
    assignee_norm = _validate_ticket_assignee(assignee)
    source_norm = _validate_ticket_source(source)
    priority_val = max(1, min(int(priority), 4))
    now = _now_iso()

    conn = connect_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO tickets (
                project_id, title, description, status, assignee, priority,
                parent_id, blocked_by_ticket_id, source,
                created_at, updated_at, closed_at, linked_memory_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                project_id,
                title_text,
                description.strip(),
                status_norm,
                assignee_norm,
                priority_val,
                parent_id,
                blocked_by_ticket_id,
                source_norm,
                now,
                now,
                linked_memory_id,
            ),
        )
        ticket_id = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()

    event_id = append_ticket_event(
        ticket_id,
        "created",
        actor,
        {
            "title": title_text,
            "assignee": assignee_norm,
            "priority": priority_val,
            "source": source_norm,
        },
    )
    ticket = get_ticket_by_id(ticket_id)
    if ticket is None:
        raise RuntimeError("ticket create failed")
    return {"ticket": _ticket_row_to_dict(ticket), "event_id": event_id}


def get_ticket_by_id(ticket_id: int) -> sqlite3.Row | None:
    conn = connect_db()
    try:
        return conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    finally:
        conn.close()


def list_ticket_events(ticket_id: int, *, limit: int = 20) -> list[sqlite3.Row]:
    limit = max(1, min(int(limit), 100))
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM ticket_events
            WHERE ticket_id = ?
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (ticket_id, limit),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def list_tickets(
    *,
    project_id: int | None = None,
    status: str | None = None,
    open_only: bool = False,
    assignee: str | None = None,
    priority_max: int | None = None,
    parent_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    clauses = ["1=1"]
    params: list[object] = []

    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)

    if open_only:
        marks = ",".join("?" for _ in TICKET_OPEN_STATUSES)
        clauses.append(f"status IN ({marks})")
        params.extend(sorted(TICKET_OPEN_STATUSES))
    elif status is not None:
        if status.strip().lower() == "all":
            pass
        elif "," in status:
            statuses = [_validate_ticket_status(part) for part in status.split(",")]
            marks = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({marks})")
            params.extend(statuses)
        else:
            clauses.append("status = ?")
            params.append(_validate_ticket_status(status))

    if assignee is not None:
        clauses.append("assignee = ?")
        params.append(_validate_ticket_assignee(assignee))

    if priority_max is not None:
        clauses.append("priority <= ?")
        params.append(max(1, min(int(priority_max), 4)))

    if parent_id is not None:
        clauses.append("parent_id = ?")
        params.append(parent_id)

    params.extend([limit, offset])
    conn = connect_db()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM tickets
            WHERE {' AND '.join(clauses)}
            ORDER BY priority ASC, datetime(updated_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def count_tickets(
    *,
    project_id: int | None = None,
    status: str | None = None,
    open_only: bool = False,
    assignee: str | None = None,
) -> int:
    clauses = ["1=1"]
    params: list[object] = []
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    if open_only:
        marks = ",".join("?" for _ in TICKET_OPEN_STATUSES)
        clauses.append(f"status IN ({marks})")
        params.extend(sorted(TICKET_OPEN_STATUSES))
    elif status is not None:
        clauses.append("status = ?")
        params.append(_validate_ticket_status(status))
    if assignee is not None:
        clauses.append("assignee = ?")
        params.append(_validate_ticket_assignee(assignee))

    conn = connect_db()
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM tickets WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        return int(row["c"]) if row is not None else 0
    finally:
        conn.close()


def update_ticket(
    ticket_id: int,
    *,
    actor: str,
    status: str | None = None,
    assignee: str | None = None,
    priority: int | None = None,
    description: str | None = None,
    blocked_by_ticket_id: int | None = None,
    comment: str | None = None,
    linked_memory_id: int | None = None,
    clear_blocked_by: bool = False,
) -> dict[str, object]:
    row = get_ticket_by_id(ticket_id)
    if row is None:
        raise ValueError(f"ticket not found: {ticket_id}")

    fields: list[str] = []
    params: list[object] = []
    now = _now_iso()
    old_status = str(row["status"])

    if status is not None:
        status_norm = _validate_ticket_status(status)
        fields.append("status = ?")
        params.append(status_norm)
        if status_norm in {"done", "cancelled"}:
            fields.append("closed_at = ?")
            params.append(now)
        elif old_status in {"done", "cancelled"}:
            fields.append("closed_at = NULL")

    if assignee is not None:
        fields.append("assignee = ?")
        params.append(_validate_ticket_assignee(assignee))

    if priority is not None:
        fields.append("priority = ?")
        params.append(max(1, min(int(priority), 4)))

    if description is not None:
        fields.append("description = ?")
        params.append(description.strip())

    if clear_blocked_by:
        fields.append("blocked_by_ticket_id = NULL")
    elif blocked_by_ticket_id is not None:
        fields.append("blocked_by_ticket_id = ?")
        params.append(blocked_by_ticket_id)

    if linked_memory_id is not None:
        fields.append("linked_memory_id = ?")
        params.append(linked_memory_id)

    if not fields and not comment:
        ticket = get_ticket_by_id(ticket_id)
        assert ticket is not None
        return {"ticket": _ticket_row_to_dict(ticket), "events": []}

    event_ids: list[int] = []
    if fields:
        fields.append("updated_at = ?")
        params.append(now)
        params.append(ticket_id)
        conn = connect_db()
        try:
            conn.execute(
                f"UPDATE tickets SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

        if status is not None and _validate_ticket_status(status) != old_status:
            event_ids.append(
                append_ticket_event(
                    ticket_id,
                    "status_change",
                    actor,
                    {"from": old_status, "to": _validate_ticket_status(status)},
                )
            )
        if assignee is not None and _validate_ticket_assignee(assignee) != str(row["assignee"]):
            event_ids.append(
                append_ticket_event(
                    ticket_id,
                    "assignee_change",
                    actor,
                    {"from": str(row["assignee"]), "to": _validate_ticket_assignee(assignee)},
                )
            )
        if priority is not None and int(priority) != int(row["priority"]):
            event_ids.append(
                append_ticket_event(
                    ticket_id,
                    "priority_change",
                    actor,
                    {"from": int(row["priority"]), "to": max(1, min(int(priority), 4))},
                )
            )

    if comment and comment.strip():
        event_ids.append(
            append_ticket_event(
                ticket_id,
                "comment",
                actor,
                {"text": comment.strip()},
            )
        )

    ticket = get_ticket_by_id(ticket_id)
    assert ticket is not None
    return {"ticket": _ticket_row_to_dict(ticket), "event_ids": event_ids}


def complete_ticket(ticket_id: int, *, actor: str = "system") -> dict[str, object]:
    return update_ticket(ticket_id, actor=actor, status="done")


def claim_ticket(ticket_id: int, *, actor: str) -> dict[str, object]:
    row = get_ticket_by_id(ticket_id)
    if row is None:
        raise ValueError(f"ticket not found: {ticket_id}")
    status = str(row["status"])
    if status in {"done", "cancelled"}:
        raise ValueError(f"ticket {ticket_id} is closed")
    assignee = actor.strip().lower() if actor.strip().lower() in TICKET_ASSIGNEES else str(row["assignee"])
    new_status = "in_progress" if status in {"open", "claimed"} else status
    result = update_ticket(
        ticket_id,
        actor=actor,
        status=new_status,
        assignee=assignee,
    )
    append_ticket_event(ticket_id, "claimed", actor, {"status": new_status})
    return result


def get_ticket_detail(ticket_id: int, *, event_limit: int = 20) -> dict[str, object] | None:
    row = get_ticket_by_id(ticket_id)
    if row is None:
        return None
    events = [
        {
            **row_to_dict(event),
            "payload": json.loads(str(event["payload"] or "{}")),
        }
        for event in list_ticket_events(ticket_id, limit=event_limit)
    ]
    return {"ticket": _ticket_row_to_dict(row), "events": events}


def build_tickets_summary(
    project_id: int | None,
    agent: str | None = None,
) -> dict[str, object]:
    if project_id is None:
        return {
            "open": [],
            "assigned_to_agent": [],
            "blocked": [],
            "recently_closed": [],
            "counts": {
                "open": 0,
                "in_progress": 0,
                "blocked": 0,
                "done_recent": 0,
            },
        }

    open_rows = list_tickets(project_id=project_id, open_only=True, limit=50)
    open_payload = [_ticket_row_to_dict(row) for row in open_rows]
    agent_norm = agent.strip().lower() if isinstance(agent, str) else None
    assigned = [
        ticket
        for ticket in open_payload
        if agent_norm and str(ticket.get("assignee", "")).lower() == agent_norm
    ]
    blocked = [
        ticket for ticket in open_payload if str(ticket.get("status")) == "blocked"
    ]
    closed_rows = list_tickets(
        project_id=project_id,
        status="done,cancelled",
        limit=5,
    )
    return {
        "open": open_payload,
        "assigned_to_agent": assigned,
        "blocked": blocked,
        "recently_closed": [_ticket_row_to_dict(row) for row in closed_rows],
        "counts": {
            "open": count_tickets(project_id=project_id, status="open"),
            "in_progress": count_tickets(project_id=project_id, status="in_progress"),
            "blocked": count_tickets(project_id=project_id, status="blocked"),
            "open_total": count_tickets(project_id=project_id, open_only=True),
        },
    }


def _format_tickets_prompt_section(
    project_id: int | None,
    agent: str | None = None,
) -> str:
    summary = build_tickets_summary(project_id, agent)
    lines = [
        "Tickets (authoritative work board — use for assigned, blocked, or in-flight work):",
    ]
    assigned = summary["assigned_to_agent"]
    if isinstance(assigned, list) and assigned:
        lines.append("Assigned to Cursor:" if agent == "cursor" else "Assigned:")
        for ticket in assigned[:10]:
            if not isinstance(ticket, dict):
                continue
            lines.append(
                f"- #{ticket.get('id')} [{ticket.get('status')}] P{ticket.get('priority')} "
                f"{ticket.get('title')}"
            )
    else:
        lines.append("Assigned: (none)")

    open_items = summary["open"]
    if isinstance(open_items, list) and open_items:
        lines.append("Open board:")
        for ticket in open_items[:10]:
            if not isinstance(ticket, dict):
                continue
            lines.append(
                f"- #{ticket.get('id')} [{ticket.get('status')}] "
                f"{ticket.get('assignee')} | P{ticket.get('priority')} — {ticket.get('title')}"
            )
    else:
        lines.append("Open board: (none)")

    blocked = summary["blocked"]
    if isinstance(blocked, list) and blocked:
        lines.append("Blocked:")
        for ticket in blocked[:5]:
            if not isinstance(ticket, dict):
                continue
            lines.append(f"- #{ticket.get('id')} — {ticket.get('title')}")
    else:
        lines.append("Blocked: (none)")

    return "\n".join(lines)


# --- memory backend (V3.6 Phase 1) ------------------------------------------


def _memory_embed_provider() -> str:
    if MEMORY_EMBED_PROVIDER == "off":
        return "off"
    if MEMORY_EMBED_PROVIDER == "local":
        return "local"
    if MEMORY_EMBED_PROVIDER == "openai":
        return "openai" if _has_openai_key() else "off"
    if _has_openai_key():
        return "openai"
    return "local"


def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    global _sqlite_vec_ready
    if _sqlite_vec_ready is not None:
        return _sqlite_vec_ready
    if not hasattr(conn, "enable_load_extension"):
        _sqlite_vec_ready = False
        return False
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _sqlite_vec_ready = True
    except Exception:
        _sqlite_vec_ready = False
    return _sqlite_vec_ready


def _pack_embedding(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _ensure_memory_vec_table(conn: sqlite3.Connection) -> bool:
    if not _try_load_sqlite_vec(conn):
        return False
    row = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name = 'memory_vec'
        """
    ).fetchone()
    if row:
        return True
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE memory_vec USING vec0(
            memory_id INTEGER PRIMARY KEY,
            embedding float[{EMBED_DIM}]
        )
        """
    )
    return True


def _map_legacy_memory_row(
    row: sqlite3.Row, project_id: int | None
) -> dict[str, object]:
    memory_type = str(row["type"])
    source = "manual"
    pinned = 0
    if memory_type == "spark":
        if int(row["importance"]) >= SPARK_IMPORTANCE_SUMMARY:
            memory_type = "summary"
            source = "session_summary"
        else:
            memory_type = "event"
            source = "implicit"
    else:
        if int(row["importance"]) >= 4:
            pinned = 1
    confidence = 1.0
    if source == "implicit":
        confidence = 0.75
    elif source == "session_summary":
        confidence = 0.85
    return {
        "created_at": row["timestamp"],
        "updated_at": row["timestamp"],
        "project_id": project_id,
        "memory_type": memory_type,
        "content": row["content"],
        "summary": None,
        "importance": int(row["importance"]),
        "source": source,
        "message_id": None,
        "decision_id": None,
        "pinned": pinned,
        "status": "active",
        "confidence": confidence,
        "legacy_memory_id": int(row["id"]),
    }


def migrate_memories_to_memory_items(conn: sqlite3.Connection) -> int:
    """One-time idempotent migration from memories to memory_items."""
    project = conn.execute(
        "SELECT id FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    project_id = int(project["id"]) if project else None
    rows = conn.execute("SELECT * FROM memories ORDER BY id ASC").fetchall()
    inserted = 0
    for row in rows:
        exists = conn.execute(
            "SELECT 1 FROM memory_items WHERE legacy_memory_id = ?",
            (int(row["id"]),),
        ).fetchone()
        if exists:
            continue
        fields = _map_legacy_memory_row(row, project_id)
        conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, message_id, decision_id, pinned, status,
                confidence, legacy_memory_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                fields["created_at"],
                fields["updated_at"],
                fields["project_id"],
                fields["memory_type"],
                fields["content"],
                fields["summary"],
                fields["importance"],
                fields["source"],
                fields["message_id"],
                fields["decision_id"],
                fields["pinned"],
                fields.get("confidence", 1.0),
                fields["legacy_memory_id"],
            ),
        )
        inserted += 1
    return inserted


def _get_local_embed_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    with _embed_model_lock:
        if _embed_model is None:
            from sentence_transformers import SentenceTransformer

            _embed_model = SentenceTransformer(EMBED_MODEL_LOCAL)
    return _embed_model


def embed_text(text: str) -> list[float] | None:
    """Return an embedding vector for memory_items content, or None if unavailable."""
    content = _normalize_text(text)
    if not content:
        return None
    provider = _memory_embed_provider()
    if provider == "off":
        return None
    try:
        if provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=content,
                dimensions=EMBED_DIM,
            )
            return list(response.data[0].embedding)
        model = _get_local_embed_model()
        vector = model.encode(content, normalize_embeddings=True)
        return [float(x) for x in vector.tolist()]
    except Exception:
        return None


def index_memory_embedding(
    conn: sqlite3.Connection, memory_id: int, embedding: list[float], model_name: str
) -> None:
    blob = _pack_embedding(embedding)
    conn.execute(
        """
        UPDATE memory_items
        SET embed_model = ?, embed_dim = ?, embedding_blob = ?, updated_at = ?
        WHERE id = ?
        """,
        (model_name, EMBED_DIM, blob, _now_iso(), memory_id),
    )
    if not _ensure_memory_vec_table(conn):
        return
    conn.execute(
        "DELETE FROM memory_vec WHERE memory_id = ?",
        (memory_id,),
    )
    conn.execute(
        "INSERT INTO memory_vec(memory_id, embedding) VALUES (?, ?)",
        (memory_id, embedding),
    )


def backfill_memory_item_embeddings(conn: sqlite3.Connection, limit: int = 200) -> int:
    """Embed memory_items that lack an embedding. Returns count embedded."""
    provider = _memory_embed_provider()
    if provider == "off":
        return 0
    _ensure_memory_vec_table(conn)
    model_name = (
        "text-embedding-3-small" if provider == "openai" else EMBED_MODEL_LOCAL
    )
    rows = conn.execute(
        """
        SELECT id, content
        FROM memory_items
        WHERE status = 'active' AND embedding_blob IS NULL
        ORDER BY id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    embedded = 0
    for row in rows:
        vector = embed_text(str(row["content"]))
        if not vector or len(vector) != EMBED_DIM:
            continue
        index_memory_embedding(conn, int(row["id"]), vector, model_name)
        embedded += 1
    return embedded


def _ensure_memory_backend(conn: sqlite3.Connection) -> None:
    _ensure_memory_items_columns(conn)
    _ensure_consolidation_table(conn)
    migrate_memories_to_memory_items(conn)
    backfill_memory_item_embeddings(conn)


def _ensure_consolidation_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_consolidation_runs (
            id INTEGER PRIMARY KEY,
            run_at TEXT NOT NULL,
            run_type TEXT NOT NULL,
            items_in INTEGER,
            items_out INTEGER,
            notes TEXT
        )
        """
    )


def _ensure_memory_items_columns(conn: sqlite3.Connection) -> None:
    """Add V3.6 columns to existing memory_items tables."""
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()
    }
    if "embedding_blob" not in cols:
        conn.execute("ALTER TABLE memory_items ADD COLUMN embedding_blob BLOB")
    if "confidence" not in cols:
        conn.execute(
            "ALTER TABLE memory_items ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"
        )


def _normalize_memory_dedupe_key(content: str) -> str:
    return _normalize_text(content).lower()


def _active_project_id(conn: sqlite3.Connection) -> int | None:
    project = conn.execute(
        "SELECT id FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    return int(project["id"]) if project else None


def _resolve_memory_item_fields(
    legacy_type: str,
    importance: int,
    *,
    source: str | None,
    pinned: bool | None,
    confidence: float | None,
) -> tuple[str, str, bool, float]:
    if legacy_type == "spark":
        item_type = (
            "summary" if importance >= SPARK_IMPORTANCE_SUMMARY else "event"
        )
        resolved_source = source or (
            "session_summary"
            if importance >= SPARK_IMPORTANCE_SUMMARY
            else "implicit"
        )
        resolved_pinned = False if pinned is None else pinned
        if confidence is not None:
            resolved_confidence = confidence
        elif resolved_source == "session_summary":
            resolved_confidence = 0.85
        else:
            resolved_confidence = 0.75
    else:
        item_type = (
            legacy_type if legacy_type in ALLOWED_MEMORY_ITEM_TYPES else "event"
        )
        resolved_source = source or "manual"
        resolved_pinned = True if pinned is None else pinned
        resolved_confidence = 1.0 if confidence is None else confidence
    return item_type, resolved_source, resolved_pinned, resolved_confidence


def _find_recent_duplicate_memory_item(
    conn: sqlite3.Connection,
    memory_type: str,
    content: str,
    project_id: int | None,
) -> int | None:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=MEMORY_ITEM_DEDUPE_HOURS)
    ).isoformat()
    norm = _normalize_memory_dedupe_key(content)
    if project_id is None:
        rows = conn.execute(
            """
            SELECT id, content FROM memory_items
            WHERE memory_type = ? AND status = 'active' AND created_at >= ?
              AND project_id IS NULL
            """,
            (memory_type, cutoff),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, content FROM memory_items
            WHERE memory_type = ? AND status = 'active' AND created_at >= ?
              AND project_id = ?
            """,
            (memory_type, cutoff, project_id),
        ).fetchall()
    for row in rows:
        if _normalize_memory_dedupe_key(str(row["content"])) == norm:
            return int(row["id"])
    return None


def save_memory_item(
    memory_type: str,
    content: str,
    summary: str | None = None,
    source: str = "implicit",
    project_id: int | None = None,
    message_id: int | None = None,
    decision_id: int | None = None,
    importance: int = 3,
    confidence: float = 1.0,
    pinned: bool = False,
    status: str = "active",
    *,
    conn: sqlite3.Connection | None = None,
    legacy_memory_id: int | None = None,
) -> int | None:
    """
    Insert into memory_items and attempt embedding/indexing.
    Returns memory_items.id, an existing deduped id, or None on failure.
    """
    if memory_type not in ALLOWED_MEMORY_ITEM_TYPES:
        memory_type = "event"

    own_conn = conn is None
    if own_conn:
        conn = connect_db()
    try:
        if project_id is None:
            project_id = _active_project_id(conn)

        existing_id = _find_recent_duplicate_memory_item(
            conn, memory_type, content, project_id
        )
        if existing_id is not None:
            return existing_id

        now = _now_iso()
        cur = conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, message_id, decision_id, pinned, status,
                confidence, legacy_memory_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                project_id,
                memory_type,
                content,
                summary,
                importance,
                source,
                message_id,
                decision_id,
                1 if pinned else 0,
                status,
                confidence,
                legacy_memory_id,
            ),
        )
        item_id = int(cur.lastrowid)

        try:
            vector = embed_text(content)
            if vector and len(vector) == EMBED_DIM:
                provider = _memory_embed_provider()
                model_name = (
                    "text-embedding-3-small"
                    if provider == "openai"
                    else EMBED_MODEL_LOCAL
                )
                index_memory_embedding(conn, item_id, vector, model_name)
        except Exception:
            pass

        if own_conn:
            conn.commit()
        return item_id
    except Exception:
        return None
    finally:
        if own_conn and conn is not None:
            conn.close()


# --- memory retrieval (V3.6 Phase 2) ----------------------------------------


def get_last_retrieval_mode() -> str:
    """Return mode used by the most recent retrieve_memories() call."""
    return _last_retrieval_mode


def _unpack_embedding(blob: bytes | None) -> list[float] | None:
    if not blob or len(blob) % 4 != 0:
        return None
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, dot))


# --- memory consolidation (V3.6 Phase 4) ------------------------------------


def _compatible_memory_types(left: str, right: str) -> bool:
    if left == right:
        return True
    pair = {left, right}
    return pair <= {"event", "summary"}


def record_consolidation_run(
    conn: sqlite3.Connection,
    run_type: str,
    items_in: int,
    items_out: int,
    notes: str = "",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO memory_consolidation_runs (
            run_at, run_type, items_in, items_out, notes
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (_now_iso(), run_type, items_in, items_out, notes),
    )
    return int(cur.lastrowid)


def mark_memory_item_merged(
    conn: sqlite3.Connection, item_id: int, merged_into_id: int
) -> bool:
    cur = conn.execute(
        """
        UPDATE memory_items
        SET status = 'merged', merged_into_id = ?, updated_at = ?
        WHERE id = ? AND status = 'active' AND pinned = 0 AND id != ?
        """,
        (merged_into_id, _now_iso(), item_id, merged_into_id),
    )
    return cur.rowcount > 0


def _last_session_summary_before(
    conn: sqlite3.Connection, *, exclude_id: int | None = None
) -> tuple[int | None, str | None]:
    if exclude_id is None:
        row = conn.execute(
            """
            SELECT id, created_at FROM memory_items
            WHERE source = 'session_summary'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, created_at FROM memory_items
            WHERE source = 'session_summary' AND id != ?
            ORDER BY id DESC LIMIT 1
            """,
            (exclude_id,),
        ).fetchone()
    if row is None:
        return None, None
    return int(row["id"]), str(row["created_at"])


def merge_implicit_since_session_summary(
    conn: sqlite3.Connection, summary_item_id: int
) -> int:
    """Mark trim implicit events superseded by a new session summary."""
    summary = conn.execute(
        "SELECT created_at FROM memory_items WHERE id = ?",
        (summary_item_id,),
    ).fetchone()
    if summary is None:
        return 0

    _, since_ts = _last_session_summary_before(conn, exclude_id=summary_item_id)
    params: list[object] = [summary_item_id, str(summary["created_at"])]
    query = """
        SELECT id FROM memory_items
        WHERE status = 'active' AND pinned = 0 AND id != ?
          AND source = 'implicit' AND memory_type = 'event'
          AND datetime(created_at) <= datetime(?)
    """
    if since_ts:
        query += " AND datetime(created_at) > datetime(?)"
        params.append(since_ts)

    rows = conn.execute(query, params).fetchall()
    merged = 0
    for row in rows:
        if mark_memory_item_merged(conn, int(row["id"]), summary_item_id):
            merged += 1
    return merged


def find_duplicate_memory_pairs(
    conn: sqlite3.Connection,
    *,
    limit: int = MEMORY_CONSOLIDATE_PAIR_LIMIT,
    min_sim: float = MEMORY_CONSOLIDATE_DUPLICATE_SIM,
) -> list[tuple[int, int, float]]:
    rows = conn.execute(
        """
        SELECT id, project_id, memory_type, embedding_blob
        FROM memory_items
        WHERE status = 'active' AND pinned = 0 AND embedding_blob IS NOT NULL
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    pairs: list[tuple[int, int, float]] = []
    merged_ids: set[int] = set()
    for i, left in enumerate(rows):
        left_id = int(left["id"])
        if left_id in merged_ids:
            continue
        left_vec = _unpack_embedding(left["embedding_blob"])
        if not left_vec:
            continue
        for right in rows[i + 1 :]:
            right_id = int(right["id"])
            if right_id in merged_ids:
                continue
            if left["project_id"] != right["project_id"]:
                continue
            if not _compatible_memory_types(
                str(left["memory_type"]), str(right["memory_type"])
            ):
                continue
            right_vec = _unpack_embedding(right["embedding_blob"])
            if not right_vec:
                continue
            sim = _cosine_similarity(left_vec, right_vec)
            if sim < min_sim:
                continue
            keep_id, merge_id = (
                (left_id, right_id) if left_id > right_id else (right_id, left_id)
            )
            pairs.append((keep_id, merge_id, round(sim, 4)))
            merged_ids.add(merge_id)
    return pairs


def run_duplicate_merge(
    conn: sqlite3.Connection, *, dry_run: bool = False
) -> dict[str, object]:
    pairs = find_duplicate_memory_pairs(conn)
    if dry_run:
        return {"merged": 0, "pairs": pairs, "dry_run": True}
    merged = 0
    for keep_id, merge_id, _sim in pairs:
        if mark_memory_item_merged(conn, merge_id, keep_id):
            merged += 1
    return {"merged": merged, "pairs": pairs}


def run_stale_marking(
    conn: sqlite3.Connection, *, dry_run: bool = False
) -> dict[str, object]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=MEMORY_STALE_AGE_DAYS)
    ).isoformat()
    rows = conn.execute(
        """
        SELECT id FROM memory_items
        WHERE status = 'active' AND pinned = 0
          AND importance <= ? AND access_count = 0
          AND datetime(created_at) < datetime(?)
        """,
        (MEMORY_STALE_MAX_IMPORTANCE, cutoff),
    ).fetchall()
    candidate_ids = [int(row["id"]) for row in rows]
    if dry_run:
        return {"stale": 0, "candidate_ids": candidate_ids, "dry_run": True}
    now = _now_iso()
    for item_id in candidate_ids:
        conn.execute(
            """
            UPDATE memory_items
            SET status = 'stale', updated_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (now, item_id),
        )
    return {"stale": len(candidate_ids), "candidate_ids": candidate_ids}


def run_daily_summary(
    conn: sqlite3.Connection, *, dry_run: bool = False
) -> dict[str, object]:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    existing = conn.execute(
        """
        SELECT id FROM memory_items
        WHERE source = 'daily_summary' AND datetime(created_at) >= datetime(?)
        LIMIT 1
        """,
        (since,),
    ).fetchone()
    if existing:
        return {"created": False, "reason": "already_exists"}

    msg_count = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE datetime(timestamp) >= datetime(?)",
            (since,),
        ).fetchone()["n"]
    )
    item_count = int(
        conn.execute(
            """
            SELECT COUNT(*) AS n FROM memory_items
            WHERE status = 'active' AND datetime(created_at) >= datetime(?)
            """,
            (since,),
        ).fetchone()["n"]
    )
    if msg_count < 3 and item_count < 2:
        return {"created": False, "reason": "insufficient_signal"}

    if dry_run:
        return {
            "created": False,
            "dry_run": True,
            "messages": msg_count,
            "items": item_count,
        }

    msgs = conn.execute(
        """
        SELECT * FROM messages
        WHERE datetime(timestamp) >= datetime(?)
        ORDER BY id ASC LIMIT 40
        """,
        (since,),
    ).fetchall()
    summary_text: str | None = None
    if msgs:
        summary_text = summarize_messages(list(msgs))
    if not summary_text:
        parts = conn.execute(
            """
            SELECT content FROM memory_items
            WHERE status = 'active' AND datetime(created_at) >= datetime(?)
            ORDER BY id ASC LIMIT 10
            """,
            (since,),
        ).fetchall()
        if parts:
            summary_text = _truncate(
                " | ".join(str(part["content"]) for part in parts)
            )
    if not summary_text:
        return {"created": False, "reason": "empty_summary"}

    item_id = save_memory_item(
        "summary",
        summary_text,
        source="daily_summary",
        importance=3,
        confidence=0.8,
        conn=conn,
    )
    return {"created": item_id is not None, "item_id": item_id}


def run_session_merge(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id FROM memory_items
        WHERE source = 'session_summary' AND status = 'active'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if row is None:
        return {"merged": 0, "reason": "no_session_summary"}
    summary_id = int(row["id"])
    merged = merge_implicit_since_session_summary(conn, summary_id)
    return {"merged": merged, "summary_item_id": summary_id}


def consolidate_memories(
    run_type: str = "all", *, dry_run: bool = False
) -> dict[str, object]:
    """
    Run memory consolidation jobs.
    run_type: session | duplicates | stale | daily | all
    """
    normalized = run_type.strip().lower()
    allowed = frozenset({"session", "duplicates", "stale", "daily", "all"})
    if normalized not in allowed:
        raise ValueError(f"invalid consolidate run_type: {run_type}")

    conn = connect_db()
    try:
        _ensure_consolidation_table(conn)
        items_in = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
            ).fetchone()["n"]
        )
        results: dict[str, object] = {}

        if normalized in ("session", "all"):
            results["session"] = run_session_merge(conn)
        if normalized in ("duplicates", "all"):
            results["duplicates"] = run_duplicate_merge(conn, dry_run=dry_run)
        if normalized in ("stale", "all"):
            results["stale"] = run_stale_marking(conn, dry_run=dry_run)
        if normalized == "daily" or (
            normalized == "all" and MEMORY_DAILY_SUMMARY
        ):
            results["daily"] = run_daily_summary(conn, dry_run=dry_run)
        elif normalized == "all":
            results["daily"] = {
                "created": False,
                "reason": "MEMORY_DAILY_SUMMARY not enabled",
            }

        items_out = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
            ).fetchone()["n"]
        )

        if not dry_run:
            notes = json.dumps(
                {
                    key: value.get("merged", value.get("stale", value.get("created")))
                    for key, value in results.items()
                    if isinstance(value, dict)
                }
            )
            record_consolidation_run(
                conn, normalized, items_in, items_out, notes
            )
            conn.commit()

        results["run_type"] = normalized
        results["items_in"] = items_in
        results["items_out"] = items_out
        results["dry_run"] = dry_run
        return results
    finally:
        conn.close()


def _hygiene_reason_entry(
    row: sqlite3.Row,
    *,
    reason: str,
    category: str,
) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "source": str(row["source"]),
        "memory_type": str(row["memory_type"]),
        "status": str(row["status"]),
        "reason": reason,
        "category": category,
    }


def _hygiene_polarity(text: str) -> int:
    lower = _normalize_text(text).lower()
    negative = (
        " disable ",
        " avoid ",
        " never ",
        " do not ",
        " don't ",
        " cannot ",
        " can't ",
        " no ",
        " stop ",
    )
    positive = (
        " enable ",
        " allow ",
        " prefer ",
        " always ",
        " use ",
        " must ",
        " yes ",
    )
    if any(token in f" {lower} " for token in negative):
        return -1
    if any(token in f" {lower} " for token in positive):
        return 1
    return 0


def _hygiene_subject_key(text: str) -> str:
    words = _normalize_text(text).lower().split()
    ignore = {
        "enable",
        "disable",
        "allow",
        "avoid",
        "prefer",
        "always",
        "never",
        "must",
        "do",
        "not",
        "don't",
        "cannot",
        "can't",
        "yes",
        "no",
        "use",
        "stop",
    }
    filtered = [word for word in words if word not in ignore]
    return " ".join(filtered[:6])


def memory_hygiene_report() -> dict[str, object]:
    """
    Non-destructive memory hygiene audit.

    Returns candidate rows grouped by stale, noisy, duplicates, and possible_conflicts.
    This report never mutates rows and is safe to run repeatedly.
    """
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, memory_type, content, importance, source, pinned, status
            FROM memory_items
            WHERE status = 'active'
            ORDER BY id ASC
            """
        ).fetchall()

        stale: list[dict[str, object]] = []
        noisy: list[dict[str, object]] = []
        duplicates: list[dict[str, object]] = []
        possible_conflicts: list[dict[str, object]] = []

        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=MEMORY_STALE_AGE_DAYS)
        duplicate_groups: dict[str, list[sqlite3.Row]] = {}
        conflict_groups: dict[str, list[sqlite3.Row]] = {}

        for row in rows:
            content = _normalize_text(str(row["content"]))
            created_at = _parse_memory_timestamp(str(row["created_at"]))
            importance = int(row["importance"])
            pinned = bool(int(row["pinned"]))
            source = str(row["source"]).lower()
            memory_type = str(row["memory_type"]).lower()

            if (
                not pinned
                and importance <= MEMORY_STALE_MAX_IMPORTANCE
                and created_at is not None
                and created_at < stale_cutoff
            ):
                stale.append(
                    _hygiene_reason_entry(
                        row,
                        reason=(
                            f"older than {MEMORY_STALE_AGE_DAYS} days with "
                            f"importance<={MEMORY_STALE_MAX_IMPORTANCE}"
                        ),
                        category="stale",
                    )
                )

            if source in {"implicit", "extract"} and importance <= 1 and len(content) < 40:
                noisy.append(
                    _hygiene_reason_entry(
                        row,
                        reason="short low-importance implicit/extract memory",
                        category="noisy",
                    )
                )

            norm_key = _normalize_text(content).lower()
            if norm_key:
                duplicate_groups.setdefault(norm_key, []).append(row)

            if memory_type in {"decision", "preference", "constraint"}:
                subject = _hygiene_subject_key(content)
                if subject:
                    conflict_groups.setdefault(subject, []).append(row)

        for group_rows in duplicate_groups.values():
            if len(group_rows) < 2:
                continue
            newest_id = max(int(item["id"]) for item in group_rows)
            for item in group_rows:
                item_id = int(item["id"])
                if item_id == newest_id:
                    continue
                duplicates.append(
                    _hygiene_reason_entry(
                        item,
                        reason=f"duplicate content; newer row #{newest_id} exists",
                        category="duplicates",
                    )
                )

        for subject, group_rows in conflict_groups.items():
            if len(group_rows) < 2:
                continue
            polarity_by_id = {
                int(item["id"]): _hygiene_polarity(str(item["content"])) for item in group_rows
            }
            has_positive = any(value > 0 for value in polarity_by_id.values())
            has_negative = any(value < 0 for value in polarity_by_id.values())
            if not (has_positive and has_negative):
                continue
            for item in group_rows:
                possible_conflicts.append(
                    _hygiene_reason_entry(
                        item,
                        reason=f"possible polarity conflict on subject '{subject}'",
                        category="possible_conflicts",
                    )
                )

        return {
            "generated_at": _now_iso(),
            "dry_run": True,
            "stale": stale,
            "noisy": noisy,
            "duplicates": duplicates,
            "possible_conflicts": possible_conflicts,
            "counts": {
                "stale": len(stale),
                "noisy": len(noisy),
                "duplicates": len(duplicates),
                "possible_conflicts": len(possible_conflicts),
                "total": len(stale) + len(noisy) + len(duplicates) + len(possible_conflicts),
            },
        }
    finally:
        conn.close()


def memory_hygiene_report_api() -> dict[str, object]:
    """Read-only API payload for memory hygiene report."""
    return memory_hygiene_report()


def _parse_memory_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recency_score(created_at: str) -> float:
    ts = _parse_memory_timestamp(created_at)
    if ts is None:
        return 0.5
    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    if age_days <= MEMORY_RECENCY_HIGH_DAYS:
        return 1.0
    if age_days >= MEMORY_RECENCY_LOW_DAYS:
        return 0.15
    span = MEMORY_RECENCY_LOW_DAYS - MEMORY_RECENCY_HIGH_DAYS
    decay = (age_days - MEMORY_RECENCY_HIGH_DAYS) / span
    return max(0.15, 1.0 - 0.85 * decay)


def _importance_score(importance: int) -> float:
    return max(0.0, min(1.0, (int(importance) - 1) / 4))


def _project_match_score(item_project_id: int | None, active_project_id: int | None) -> float:
    if active_project_id is None:
        return 0.5 if item_project_id is None else 0.0
    if item_project_id == active_project_id:
        return 1.0
    if item_project_id is None:
        return 0.5
    return 0.0


def _infer_query_memory_types(query: str) -> set[str]:
    lower = query.lower()
    types: set[str] = set()
    if any(w in lower for w in ("decision", "decided", "approved", "why did we", "why we")):
        types.add("decision")
    if any(w in lower for w in ("bug", "error", "broke", "broken", "fail", "failed", "failure")):
        types.add("bug")
    if any(w in lower for w in ("qa", "test", "passed", "pass", "regression")):
        types.add("qa_result")
    if any(w in lower for w in ("prefer", "preference", "like", "always", "never")):
        types.add("preference")
    if any(w in lower for w in ("risk", "constraint", "must", "cannot", "can't", "required")):
        types.add("constraint")
    if any(
        w in lower
        for w in ("what happened", "recently", "recent", "session", "last time", "summary")
    ):
        types.update({"summary", "event", "project_update"})
    if any(w in lower for w in ("lesson", "learned", "takeaway")):
        types.add("lesson")
    return types


def _type_match_score(memory_type: str, inferred_types: set[str]) -> float:
    if not inferred_types:
        return 0.0
    return 1.0 if memory_type in inferred_types else 0.0


def _keyword_score_for_item(
    tokens: list[str], content: str, summary: str | None
) -> float:
    if not tokens:
        return 0.0
    haystack = f"{content} {summary or ''}".lower()
    hits = sum(1 for token in tokens if token in haystack)
    return hits / len(tokens)


def _memory_display_text(row: sqlite3.Row) -> str:
    summary = row["summary"]
    if summary:
        return str(summary)
    return str(row["content"])


def _semantic_candidate_scores(
    conn: sqlite3.Connection, query_embedding: list[float] | None, limit: int
) -> dict[int, float]:
    if not query_embedding:
        return {}

    if _ensure_memory_vec_table(conn):
        try:
            rows = conn.execute(
                """
                SELECT memory_id, distance
                FROM memory_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
                """,
                (query_embedding, limit),
            ).fetchall()
            if rows:
                return {
                    int(row["memory_id"]): max(
                        0.0, min(1.0, 1.0 - float(row["distance"]))
                    )
                    for row in rows
                }
        except Exception:
            pass

    rows = conn.execute(
        """
        SELECT id, embedding_blob
        FROM memory_items
        WHERE status = 'active' AND embedding_blob IS NOT NULL
        """
    ).fetchall()
    scored: list[tuple[int, float]] = []
    for row in rows:
        vector = _unpack_embedding(row["embedding_blob"])
        if not vector:
            continue
        scored.append((int(row["id"]), _cosine_similarity(query_embedding, vector)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return dict(scored[:limit])


def _keyword_candidate_scores(
    conn: sqlite3.Connection, query: str, limit: int
) -> dict[int, float]:
    tokens = _tokenize(query)
    rows = conn.execute(
        "SELECT * FROM memory_items WHERE status = 'active'"
    ).fetchall()
    scored: list[tuple[int, float, int, str]] = []
    for row in rows:
        kw = _keyword_score_for_item(
            tokens, str(row["content"]), row["summary"]
        )
        scored.append(
            (int(row["id"]), kw, int(row["importance"]), str(row["created_at"]))
        )
    scored.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
    return {item[0]: item[1] for item in scored[:limit]}


def _load_active_memory_item(conn: sqlite3.Connection, memory_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM memory_items WHERE id = ? AND status = 'active'",
        (memory_id,),
    ).fetchone()


def _is_canon_memory_row(row: sqlite3.Row) -> bool:
    return (
        str(row["status"]) == "active"
        and str(row["source"]) == "crowley"
        and int(row["pinned"]) == 1
        and str(row["memory_type"]) == "summary"
        and str(row["content"]).startswith("Canon:")
    )


def _memory_provenance_ids(row: sqlite3.Row) -> dict[str, int | None]:
    provenance: dict[str, int | None] = {"memory_item_id": int(row["id"])}
    for key in ("message_id", "decision_id", "merged_into_id", "legacy_memory_id"):
        raw = row[key] if key in row.keys() else None
        provenance[key] = int(raw) if raw is not None else None
    return provenance


def _available_provenance_ids(provenance: dict[str, int | None]) -> dict[str, int]:
    return {key: value for key, value in provenance.items() if value is not None}


def _build_retrieval_explanation(
    row: sqlite3.Row,
    *,
    score: float,
    score_breakdown: dict[str, float],
    retrieval_mode: str,
) -> dict[str, object]:
    provenance = _memory_provenance_ids(row)
    return {
        "source": str(row["source"]),
        "memory_type": str(row["memory_type"]),
        "status": str(row["status"]),
        "pinned": bool(int(row["pinned"])),
        "is_canon": _is_canon_memory_row(row),
        "score": score,
        "score_breakdown": score_breakdown,
        "retrieval_mode": retrieval_mode,
        "provenance": provenance,
        "provenance_available": _available_provenance_ids(provenance),
    }



def _score_memory_item(
    row: sqlite3.Row,
    *,
    semantic: float,
    keyword: float,
    active_project_id: int | None,
    inferred_types: set[str],
) -> tuple[float, dict[str, float]]:
    recency = _recency_score(str(row["created_at"]))
    importance = _importance_score(int(row["importance"]))
    type_match = _type_match_score(str(row["memory_type"]), inferred_types)
    project_match = _project_match_score(
        int(row["project_id"]) if row["project_id"] is not None else None,
        active_project_id,
    )
    pinned_bonus = W_SCORE_PINNED_BONUS if int(row["pinned"]) else 0.0
    breakdown = {
        "semantic": round(semantic, 4),
        "keyword": round(keyword, 4),
        "recency": round(recency, 4),
        "importance": round(importance, 4),
        "type_match": round(type_match, 4),
        "project_match": round(project_match, 4),
        "pinned_bonus": round(pinned_bonus, 4),
    }
    score = (
        W_SCORE_SEMANTIC * semantic
        + W_SCORE_KEYWORD * keyword
        + W_SCORE_RECENCY * recency
        + W_SCORE_IMPORTANCE * importance
        + W_SCORE_TYPE * type_match
        + W_SCORE_PROJECT * project_match
        + pinned_bonus
    )
    return round(score, 4), breakdown


def retrieve_memories(
    query: str,
    limit: int = MEMORY_LIMIT,
    project_id: int | None = None,
) -> list[dict[str, object]]:
    """
    Hybrid retrieval over memory_items.
    Returns scored dicts with id, type, content, score, score_breakdown,
    status, is_canon, provenance, and read-only explanation metadata.
    Ranking behavior is unchanged; explanation fields are diagnostic only.
    """
    global _last_retrieval_mode

    conn = connect_db()
    try:
        active_project_id = project_id
        if active_project_id is None:
            project = conn.execute(
                "SELECT id FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            active_project_id = int(project["id"]) if project else None

        query_embedding = embed_text(query)
        semantic_scores = _semantic_candidate_scores(
            conn, query_embedding, MEMORY_RETRIEVE_VECTOR_CANDIDATES
        )
        keyword_scores = _keyword_candidate_scores(
            conn, query, MEMORY_RETRIEVE_KEYWORD_CANDIDATES
        )

        candidate_ids: set[int] = set(semantic_scores) | set(keyword_scores)

        pinned_rows = conn.execute(
            "SELECT id FROM memory_items WHERE status = 'active' AND pinned = 1"
        ).fetchall()
        for row in pinned_rows:
            candidate_ids.add(int(row["id"]))

        summary_rows = conn.execute(
            """
            SELECT id FROM memory_items
            WHERE status = 'active' AND memory_type = 'summary'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (MEMORY_RETRIEVE_SUMMARY_CANDIDATES,),
        ).fetchall()
        for row in summary_rows:
            candidate_ids.add(int(row["id"]))

        inferred_types = _infer_query_memory_types(query)
        results: list[dict[str, object]] = []
        semantic_used = bool(query_embedding and semantic_scores)

        for memory_id in candidate_ids:
            row = _load_active_memory_item(conn, memory_id)
            if row is None:
                continue
            score, breakdown = _score_memory_item(
                row,
                semantic=semantic_scores.get(memory_id, 0.0),
                keyword=keyword_scores.get(memory_id, 0.0),
                active_project_id=active_project_id,
                inferred_types=inferred_types,
            )
            display = _memory_display_text(row)
            row_confidence = row["confidence"] if "confidence" in row.keys() else 1.0
            results.append(
                {
                    "id": memory_id,
                    "memory_type": str(row["memory_type"]),
                    "content": display,
                    "importance": int(row["importance"]),
                    "confidence": round(float(row_confidence), 4),
                    "source": str(row["source"]),
                    "created_at": str(row["created_at"]),
                    "project_id": int(row["project_id"])
                    if row["project_id"] is not None
                    else None,
                    "pinned": bool(int(row["pinned"])),
                    "score": score,
                    "score_breakdown": breakdown,
                    "_row": row,
                }
            )

        results.sort(
            key=lambda item: (
                float(item["score"]),
                int(item["importance"]),
                str(item["created_at"]),
            ),
            reverse=True,
        )

        if semantic_used:
            _last_retrieval_mode = "vector+keyword"
        else:
            _last_retrieval_mode = "keyword-only fallback"

        mode = _last_retrieval_mode
        finalized: list[dict[str, object]] = []
        for item in results:
            row = item.pop("_row")  # type: ignore[misc]
            assert isinstance(row, sqlite3.Row)
            explanation = _build_retrieval_explanation(
                row,
                score=float(item["score"]),
                score_breakdown=dict(item["score_breakdown"]),  # type: ignore[arg-type]
                retrieval_mode=mode,
            )
            item["status"] = explanation["status"]
            item["is_canon"] = explanation["is_canon"]
            item["provenance"] = explanation["provenance"]
            item["provenance_available"] = explanation["provenance_available"]
            item["explanation"] = explanation
            finalized.append(item)
        results = finalized

        top = results[:limit]
        if top:
            now = _now_iso()
            for item in top:
                conn.execute(
                    """
                    UPDATE memory_items
                    SET access_count = access_count + 1, last_accessed_at = ?
                    WHERE id = ?
                    """,
                    (now, int(item["id"])),
                )
            conn.commit()
        return top
    finally:
        conn.close()


# --- local memory bus (V3.7) --------------------------------------------------


CONTEXT_DEFAULT_QUERY = "current project state"


def _database_status() -> str:
    try:
        conn = connect_db()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return "ok"
    except Exception:
        return "error"


def _state_payload_for_api(state: sqlite3.Row | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        "phase": _state_display(state["phase"]),
        "focus": _state_display(state["focus"]),
        "current_risk": _state_display(state["current_risk"]),
        "next_action": _state_display(state["next_action"]),
        "what_changed": _state_display(state["what_changed"]),
        "updated_at": state["updated_at"],
        "updated_by": state["updated_by"],
    }


_PHASE_PROGRESS_RE = re.compile(
    r"(?:phase\s*)?(\d+)\s*(?:of|/)\s*(\d+)",
    re.IGNORECASE,
)


def parse_phase_progress(phase: str | None) -> dict[str, object] | None:
    """Parse 'Phase 1/6' or 'Phase 2 of 6' from project_state.phase text."""
    if not phase or not str(phase).strip():
        return None
    text = str(phase).strip()
    match = _PHASE_PROGRESS_RE.search(text)
    if not match:
        return None
    current = int(match.group(1))
    total = int(match.group(2))
    if total < 1 or current < 1 or current > total:
        return None
    return {
        "current": current,
        "total": total,
        "fraction": round(current / total, 3),
        "label": text,
    }


def _memory_item_api_dict(row: sqlite3.Row) -> dict[str, object]:
    item = row_to_dict(row)
    item.pop("embedding_blob", None)
    item["display"] = _memory_display_text(row)
    return item


def _memory_counts_payload(displayed: int) -> dict[str, object]:
    by_status = count_memory_items_by_status()
    active = int(by_status.get("active", 0))
    total = sum(int(value) for value in by_status.values())
    return {
        "memory": active,
        "memory_active": active,
        "memory_total": total,
        "memory_displayed": displayed,
        "memory_by_status": by_status,
    }


def _canon_api_items(project_id: int | None = None) -> list[dict[str, object]]:
    return [_memory_item_api_dict(row) for row in list_canon_memory_items(project_id)]


def _format_canon_prompt_section(canon_rows: list[sqlite3.Row]) -> str:
    lines = [
        "Canonical memory trail:",
        (
            "Use this as always-on continuity. Conflict order: Current project state "
            "and Source-of-truth project files outrank canon; canon outranks ordinary "
            "hybrid retrieval and recent chat."
        ),
    ]
    if not canon_rows:
        lines.append("(no canon rows stored)")
        return "\n".join(lines)
    for row in canon_rows:
        content = _memory_display_text(row)
        if len(content) > MEMORY_LINE_MAX * 2:
            content = content[: MEMORY_LINE_MAX * 2 - 3] + "..."
        lines.append(f"[canon:{row['id']} | importance {row['importance']}] {content}")
    return "\n".join(lines)


def build_world_dashboard() -> dict[str, object]:
    """Single read-only snapshot for live UI sync (project + intelligence panels)."""
    project = get_active_project()
    if project is None:
        return {
            "project": None,
            "state": None,
            "phase_progress": None,
            "version": CROWLEY_VERSION,
            "release_label": CROWLEY_RELEASE_LABEL,
            "counts": {
                "tasks_open": 0,
                "loops_open": 0,
                "decisions": 0,
                "tickets_open": 0,
                "tickets_in_progress": 0,
                "tickets_blocked": 0,
                **_memory_counts_payload(0),
            },
            "tasks": [],
            "tickets": [],
            "loops": [],
            "decisions": [],
            "memory_items": [],
            "synced_at": _now_iso(),
        }

    project_id = int(project["id"])
    state = get_project_state(project_id)
    state_payload = _state_payload_for_api(state)
    phase_progress = None
    if state_payload and state_payload.get("phase"):
        phase_progress = parse_phase_progress(str(state_payload["phase"]))

    tasks = list_tasks(status="open")
    ticket_summary = build_tickets_summary(project_id)
    loops = list_open_loops(project_id, status="open", limit=50)
    loops_sorted = sorted(loops, key=lambda row: (int(row["priority"]), int(row["id"])))
    decisions = list_decisions(project_id, limit=10)
    memory_rows = list_recent_memory_items(10)
    memory_counts = _memory_counts_payload(len(memory_rows))

    return {
        "project": row_to_dict(project),
        "state": state_payload,
        "phase_progress": phase_progress,
        "version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "counts": {
            "tasks_open": len(tasks),
            "loops_open": len(loops_sorted),
            "decisions": len(decisions),
            "tickets_open": int((ticket_summary.get("counts") or {}).get("open", 0)),
            "tickets_in_progress": int(
                (ticket_summary.get("counts") or {}).get("in_progress", 0)
            ),
            "tickets_blocked": int((ticket_summary.get("counts") or {}).get("blocked", 0)),
            "tickets_open_total": int(
                (ticket_summary.get("counts") or {}).get("open_total", 0)
            ),
            **memory_counts,
        },
        "tasks": [row_to_dict(row) for row in tasks],
        "tickets": ticket_summary.get("open", []),
        "loops": [row_to_dict(row) for row in loops_sorted],
        "decisions": [row_to_dict(row) for row in decisions],
        "memory_items": [_memory_item_api_dict(row) for row in memory_rows],
        "filesystem": build_filesystem_dashboard(),
        "project_files": get_project_files_context(),
        "agent_activity": _agent_activity_summary(project_id),
        "synced_at": _now_iso(),
    }


def update_task_status(task_id: int, status: str) -> bool:
    """Update task status (e.g. open → done). Returns True if a row changed."""
    if status not in ("open", "done"):
        raise ValueError(f"invalid task status: {status}")
    conn = connect_db()
    try:
        cur = conn.execute(
            "UPDATE tasks SET status = ? WHERE id = ? AND status != ?",
            (status, task_id, status),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _context_system_health() -> dict[str, object]:
    conn = connect_db()
    try:
        sqlite_vec = _try_load_sqlite_vec(conn)
    finally:
        conn.close()
    return {
        "db": _database_status(),
        "version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "brain": _brain_banner_label(),
        "provider": get_model_provider(),
        "retrieval_mode": get_last_retrieval_mode(),
        "embed_provider": _memory_embed_provider(),
        "sqlite_vec": sqlite_vec,
    }


def build_context_bundle(
    q: str = CONTEXT_DEFAULT_QUERY,
    limit: int = MEMORY_LIMIT,
    project_slug: str | None = None,
) -> dict[str, object]:
    """
    Read-only working context for external agents (V3.7 memory bus).
    No writes.
    """
    if project_slug is not None:
        project = get_project_by_slug(project_slug)
        if project is None:
            raise ValueError(f"project not found: {project_slug}")
    else:
        project = get_active_project()

    project_id: int | None = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    state_payload = _state_payload_for_api(state)

    recent_decisions: list[dict[str, object]] = []
    open_loops: list[dict[str, object]] = []
    if project_id is not None:
        recent_decisions = [
            row_to_dict(row)
            for row in list_decisions(project_id, limit=DIAGNOSTICS_DECISIONS_LIMIT)
        ]
        open_loops = [
            row_to_dict(row)
            for row in list_open_loops(project_id, status="open", limit=LOOPS_LIMIT)
        ]

    open_tasks = [
        row_to_dict(row) for row in list_tasks(status="open")[:DIAGNOSTICS_TASKS_LIMIT]
    ]
    canon = _canon_api_items(project_id)
    relevant_memories = retrieve_memories(q, limit=limit, project_id=project_id)

    if state is not None and state["next_action"]:
        recommended = _state_display(state["next_action"])
    else:
        recommended = "(unset)"

    return {
        "project": row_to_dict(project) if project is not None else None,
        "state": state_payload,
        "recent_decisions": recent_decisions,
        "open_loops": open_loops,
        "open_tasks": open_tasks,
        "canon": canon,
        "relevant_memories": relevant_memories,
        "agent_activity": _agent_activity_summary(project_id),
        "tickets": build_tickets_summary(project_id),
        "system_health": _context_system_health(),
        "project_files": get_project_files_context(),
        "knowledge_files": load_knowledge_files_context(q),
        "recommended_next_action": recommended,
    }


def retrieve_memories_api(q: str, limit: int = MEMORY_LIMIT) -> dict[str, object]:
    """Read-only hybrid memory search for external agents (V3.7 memory bus)."""
    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    results = retrieve_memories(q, limit=limit, project_id=project_id)
    return {
        "query": q,
        "limit": limit,
        "retrieval_mode": get_last_retrieval_mode(),
        "results": results,
    }


def list_recent_agent_events_api(limit: int = 20) -> dict[str, object]:
    """Read-only recent cross-agent events from memory_items."""
    rows = list_recent_agent_events(limit=limit)
    return {
        "limit": limit,
        "sources": sorted(AGENT_EVENT_SOURCES),
        "memory_types": sorted(AGENT_EVENT_TYPES),
        "events": [_memory_item_api_dict(row) for row in rows],
    }


def get_agent_role(agent: str) -> str:
    """Identity text for agents in the Crowley pipeline (sync bundles, docs)."""
    normalized = agent.strip().lower()
    roles = {
        "codex": (
            "You are Codex in the Crowley pipeline — the architect.\n"
            "Your job: plan, decide, decompose work, write architect_handoff and notes to Crowley.\n"
            "You do not ship application code in Cursor's lane. You are not Crowley and do not speak as the OS.\n"
            "Read Cursor only through Crowley's events_from_other_agents — never their chat history."
        ),
        "cursor": (
            "You are Cursor in the Crowley pipeline — the builder.\n"
            "Your job: implement, test, ship code, write builder_handoff and notes to Crowley.\n"
            "You are not Crowley. Crowley is the running system — memory, world model, bus — you build against it.\n"
            "You do not architect in Codex's lane unless Mr. Go explicitly asks for planning here.\n"
            "Read Codex only through Crowley's events_from_other_agents — never their chat history."
        ),
        "chatgpt": (
            "You are an external agent on the Crowley memory bus.\n"
            "Crowley is the hub. Read via /api/context or /api/agent/sync; write via handoff ingest."
        ),
    }
    return roles.get(normalized, roles["chatgpt"])


def build_agent_sync_bundle(agent: str, limit: int = 20) -> dict[str, object]:
    """Read-only sync snapshot for agents communicating through Crowley."""
    normalized_agent = agent.strip().lower()
    if normalized_agent not in {"cursor", "codex", "chatgpt"}:
        raise ValueError(f"unsupported agent: {agent}")

    limit = max(1, min(int(limit), 50))
    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    state_payload = _state_payload_for_api(state)

    events = [
        _memory_item_api_dict(row)
        for row in list_recent_agent_events(limit=limit, project_id=project_id)
    ]
    events_from_this_agent = [
        event for event in events if str(event.get("source", "")).lower() == normalized_agent
    ]
    events_from_other_agents = [
        event for event in events if str(event.get("source", "")).lower() != normalized_agent
    ]
    canon = _canon_api_items(project_id)

    recent_decisions: list[dict[str, object]] = []
    open_loops: list[dict[str, object]] = []
    if project_id is not None:
        recent_decisions = [
            row_to_dict(row)
            for row in list_decisions(project_id, limit=min(limit, 50))
        ]
        open_loops = [
            row_to_dict(row)
            for row in list_open_loops(project_id, status="open", limit=min(limit, 50))
        ]

    open_tasks = [row_to_dict(row) for row in list_tasks(status="open")[:limit]]
    relevant_memories = retrieve_memories(AGENT_SYNC_QUERY, limit=limit, project_id=project_id)
    recommended = _state_display(state["next_action"]) if state is not None else "(unset)"

    return {
        "agent": normalized_agent,
        "role": get_agent_role(normalized_agent),
        "pipeline": {
            "hub": "crowley",
            "crowley": "running local OS — memory, world model, extraction, bus, this chat",
            "codex": "architect — plans and decides; posts to Crowley memory",
            "cursor": "builder — ships code; posts to Crowley memory",
            "rule": "agents do not message each other; truth flows through Crowley only",
        },
        "bus_health": bus_health(),
        "project": row_to_dict(project) if project is not None else None,
        "state": state_payload,
        "recent_events": events,
        "events_from_this_agent": events_from_this_agent,
        "events_from_other_agents": events_from_other_agents,
        "canon": canon,
        "recent_decisions": recent_decisions,
        "open_loops": open_loops,
        "open_tasks": open_tasks,
        "recommended_next_action": recommended,
        "relevant_memories_query": AGENT_SYNC_QUERY,
        "relevant_memories": relevant_memories,
        "agent_activity": _agent_activity_summary(project_id),
        "tickets": build_tickets_summary(project_id, normalized_agent),
    }


INGEST_SOURCES = frozenset({"cursor", "chatgpt", "codex", "manual", "crowley"})
INGEST_TYPES = frozenset({
    "builder_handoff",
    "architect_handoff",
    "session_summary",
    "project_update",
    "qa_result",
    "note",
})
HANDOFF_TYPE_TO_MEMORY: dict[str, str] = {
    "builder_handoff": "project_update",
    "architect_handoff": "project_update",
    "session_summary": "summary",
    "project_update": "project_update",
    "qa_result": "qa_result",
    "note": "event",
}
HANDOFF_HIGH_IMPORTANCE_TYPES = frozenset({
    "builder_handoff",
    "architect_handoff",
    "project_update",
    "qa_result",
})
HANDOFF_MIN_CONTENT_LEN = 20
HANDOFF_EXTRACT_MIN_LEN = 40
_HANDOFF_JUNK_EXACT = frozenset({
    "null",
    "undefined",
    "[object object]",
    "{}",
    "[]",
    "n/a",
    "none",
    "test",
    "asdf",
    "todo",
    "tbd",
})
_HANDOFF_EXTRACT_MARKERS = (
    "## summary",
    "## what changed",
    "## decisions",
    "## next action",
    "## open loops",
    "## qa",
    "next action:",
    "what changed:",
    "open loops:",
)


class IngestHandoffError(Exception):
    """Raised when ingest payload fails validation."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _is_valid_handoff_content(content: object) -> tuple[bool, str]:
    if content is None:
        return False, "content is required"
    if not isinstance(content, str):
        return False, "content must be a string"
    trimmed = content.strip()
    if not trimmed:
        return False, "content is empty"
    lower = trimmed.lower()
    if lower in _HANDOFF_JUNK_EXACT:
        return False, "junk content rejected"
    if "[object object]" in lower:
        return False, "junk content rejected"
    if len(trimmed) < HANDOFF_MIN_CONTENT_LEN:
        return False, f"content too short (minimum {HANDOFF_MIN_CONTENT_LEN} characters)"
    meaningful = sum(1 for ch in trimmed if ch.isalnum() or ch.isspace())
    if meaningful < len(trimmed) * 0.3:
        return False, "junk content rejected"
    return True, ""


def should_attempt_handoff_extract(content: str) -> bool:
    """True when handoff text has enough signal for conservative extraction."""
    trimmed = _normalize_text(content)
    if len(trimmed) < HANDOFF_EXTRACT_MIN_LEN:
        return False
    lower = trimmed.lower()
    if any(kw in lower for kw in EXTRACT_KEYWORDS):
        return True
    return any(marker in lower for marker in _HANDOFF_EXTRACT_MARKERS)


def _world_context_for_project(project: sqlite3.Row) -> dict[str, object]:
    pid = int(project["id"])
    return {
        "project": project,
        "state": get_project_state(pid),
        "decisions": list_decisions(pid, limit=WORLD_DECISIONS_IN_PROMPT),
        "open_loops": list_open_loops(pid, status="open", limit=WORLD_LOOPS_IN_PROMPT),
    }


def ingest_handoff(
    source: str,
    handoff_type: str,
    content: str,
    project: str = DEFAULT_PROJECT_SLUG,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    """
    Store an external handoff in memory_items and optionally extract world-model updates.
    Additive and conservative — no deletes, closes, archives, or project switches.
    """
    _ = metadata  # accepted for API compatibility; not persisted in Phase 3

    if source not in INGEST_SOURCES:
        raise IngestHandoffError(f"invalid source: {source}")
    if handoff_type not in INGEST_TYPES:
        raise IngestHandoffError(f"invalid type: {handoff_type}")

    valid, reason = _is_valid_handoff_content(content)
    if not valid:
        raise IngestHandoffError(reason)

    trimmed_content = content.strip()
    project_row = get_project_by_slug(project) if project else get_active_project()
    if project_row is None:
        raise ValueError(f"project not found: {project}")

    project_id = int(project_row["id"])
    memory_type = HANDOFF_TYPE_TO_MEMORY[handoff_type]
    importance = 4 if handoff_type in HANDOFF_HIGH_IMPORTANCE_TYPES else 3

    memory_item_id = save_memory_item(
        memory_type,
        trimmed_content,
        source=source,
        project_id=project_id,
        importance=importance,
        confidence=0.9,
        pinned=False,
    )
    if memory_item_id is None:
        return {
            "status": "error",
            "error": "failed to save memory_item",
            "memory_item_id": None,
            "applied": {},
            "skipped": [],
        }

    applied: dict[str, object] = {
        "decisions_added": 0,
        "loops_added": 0,
        "state_fields_updated": [],
    }
    skipped: list[str] = []

    if should_attempt_handoff_extract(trimmed_content):
        world = _world_context_for_project(project_row)
        proposals = propose_state_updates(trimmed_content, [], world)
        if proposals:
            extract_result = apply_state_proposals(
                proposals,
                dry_run=False,
                world_context=world,
                grounding_message=trimmed_content,
            )
            applied = {
                "decisions_added": extract_result.get("decisions_added", 0),
                "loops_added": extract_result.get("loops_added", 0),
                "state_fields_updated": list(
                    extract_result.get("state_fields_updated") or []
                ),
            }
            skipped = list(extract_result.get("skipped") or [])
        else:
            skipped.append("extraction returned no proposals")
    else:
        skipped.append("insufficient signal for extraction")

    return {
        "status": "ok",
        "memory_item_id": memory_item_id,
        "applied": applied,
        "skipped": skipped,
    }


def bus_health() -> dict[str, object]:
    """Read-only memory bus health snapshot (V3.7 Phase 6)."""
    db = _database_status()
    routes: dict[str, str] = {
        "context": "error",
        "retrieve": "error",
        "ingest": "error",
    }

    if db == "ok":
        routes["ingest"] = "ok"
        try:
            build_context_bundle(q="health", limit=1)
            routes["context"] = "ok"
        except Exception:
            routes["context"] = "error"
        try:
            retrieve_memories_api(q="health", limit=1)
            routes["retrieve"] = "ok"
        except Exception:
            routes["retrieve"] = "error"

    project = get_active_project()
    active_project: dict[str, object] | None = None
    if project is not None:
        active_project = {
            "id": int(project["id"]),
            "name": str(project["name"]),
            "slug": str(project["slug"]),
            "status": str(project["status"]),
        }

    status = "ok"
    if db != "ok" or any(route != "ok" for route in routes.values()):
        status = "degraded"

    return {
        "status": status,
        "version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "active_project": active_project,
        "routes": routes,
        "db": db,
        "retrieval_mode": get_last_retrieval_mode(),
        "provider": get_model_provider(),
        "brain": _brain_banner_label(),
    }


def _debug_bus() -> None:
    """Print memory bus health (debug-only)."""
    health = bus_health()
    print(f"[debug] memory bus status: {health['status']}")
    print(f"[debug] version: {health['version']} ({health['release_label']})")
    print(f"[debug] db: {health['db']}")
    project = health.get("active_project")
    if project:
        print(
            f"[debug] active project: {project['name']} "
            f"(slug={project['slug']}, status={project['status']})"
        )
    else:
        print("[debug] active project: (none)")
    routes = health.get("routes") or {}
    print(
        "[debug] routes: "
        f"context={routes.get('context')} "
        f"retrieve={routes.get('retrieve')} "
        f"ingest={routes.get('ingest')}"
    )
    print(f"[debug] retrieval_mode: {health['retrieval_mode']}")
    print(f"[debug] provider: {health['provider']}")
    print(f"[debug] brain: {health['brain']}")


# --- passive memory -----------------------------------------------------------


def _last_summary_spark_timestamp(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT timestamp FROM memories
        WHERE type = 'spark' AND importance >= ?
        ORDER BY id DESC LIMIT 1
        """,
        (SPARK_IMPORTANCE_SUMMARY,),
    ).fetchone()
    return row["timestamp"] if row else None


def get_messages_since_last_spark(
    conn: sqlite3.Connection, limit: int = 20
) -> list[sqlite3.Row]:
    """Fetch recent messages after the last summary-level spark."""
    since = _last_summary_spark_timestamp(conn)
    if since:
        rows = conn.execute(
            """
            SELECT * FROM messages
            WHERE timestamp > ?
            ORDER BY id ASC LIMIT ?
            """,
            (since, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return list(rows)


def _count_messages_since_last_spark(conn: sqlite3.Connection) -> int:
    since = _last_summary_spark_timestamp(conn)
    if since:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE timestamp > ?",
            (since,),
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()
    return int(row["n"]) if row else 0


def summarize_messages(messages: list[sqlite3.Row]) -> str:
    """Distil a message batch into 1–2 sentences for episodic memory."""
    lines = [f"{m['role']}: {m['content']}" for m in messages]
    transcript = "\n".join(lines)
    summary_messages = [
        {
            "role": "system",
            "content": (
                "Summarize this conversation exchange in 1–2 concise sentences "
                "for long-term memory. Focus on facts, goals, and decisions."
            ),
        },
        {"role": "user", "content": transcript},
    ]
    summary = call_model(summary_messages, stream=False, quiet=True)
    if summary:
        return _truncate(summary)

    # Heuristic fallback when all providers are unavailable
    parts: list[str] = []
    for m in reversed(messages):
        parts.append(f"{m['role']}: {m['content']}")
        if len(parts) >= 4:
            break
    parts.reverse()
    return _truncate(" | ".join(parts))


def create_spark() -> str | None:
    """
    Summarise recent messages into a summary-level spark.
    Opens its own DB connection for thread safety.
    """
    if not _spark_lock.acquire(blocking=False):
        return None

    conn = None
    try:
        conn = connect_db()
        msgs = get_messages_since_last_spark(conn)
        if len(msgs) < 2:
            return None
        if not has_enough_signal_for_summary(msgs):
            return None

        summary = summarize_messages(msgs)
        if not summary:
            return None

        legacy_id = save_memory(
            "spark",
            summary,
            SPARK_IMPORTANCE_SUMMARY,
            conn=conn,
            source="session_summary",
            confidence=0.85,
            pinned=False,
        )
        row = conn.execute(
            "SELECT id FROM memory_items WHERE legacy_memory_id = ?",
            (legacy_id,),
        ).fetchone()
        if row:
            merge_implicit_since_session_summary(conn, int(row["id"]))
        conn.commit()
        return summary
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            print("[crowley] database locked — skipping spark")
        else:
            raise
    finally:
        if conn is not None:
            conn.close()
        _spark_lock.release()


def maybe_create_spark() -> None:
    """Spawn a background thread to create a spark when enough new messages exist."""
    global _spark_running

    conn = connect_db()
    try:
        count = _count_messages_since_last_spark(conn)
    finally:
        conn.close()

    with _spark_spawn_lock:
        if _spark_running or count < SPARK_MESSAGES_PER_SUMMARY:
            return
        _spark_running = True

    def _worker() -> None:
        global _spark_running
        try:
            create_spark()
        finally:
            _spark_running = False

    threading.Thread(target=_worker, daemon=True).start()


def start_spark_timer() -> None:
    """Optional daemon thread that summarises on a fixed interval."""
    if SPARK_SUMMARY_INTERVAL_SEC <= 0:
        return

    def _loop() -> None:
        while True:
            time.sleep(SPARK_SUMMARY_INTERVAL_SEC)
            create_spark()

    threading.Thread(target=_loop, daemon=True).start()


# --- retrieval ----------------------------------------------------------------


def search_memories(user_message: str, limit: int = MEMORY_LIMIT) -> list[sqlite3.Row]:
    """Bag-of-words search over memories, ranked by score, importance, and recency."""
    conn = connect_db()
    try:
        rows = list(conn.execute("SELECT * FROM memories").fetchall())
    finally:
        conn.close()

    tokens = _tokenize(user_message)

    if not tokens:
        rows.sort(
            key=lambda r: (r["importance"], r["timestamp"], r["id"]),
            reverse=True,
        )
        return rows[:limit]

    def score(row: sqlite3.Row) -> int:
        content = row["content"].lower()
        return sum(1 for t in tokens if t in content)

    rows.sort(
        key=lambda r: (score(r), r["importance"], r["timestamp"], r["id"]),
        reverse=True,
    )
    return rows[:limit]


# --- prompting and inference --------------------------------------------------


def _personality_prompt() -> str:
    return """You are Crowley — not an assistant talking about Crowley, but the running system itself. On this machine you are: SQLite memory, world model, hybrid retrieval, passive extraction, the context bridge at 127.0.0.1:8765, and the chat Mr. Go is in right now. The readout blocks below are your own state.

In the pipeline: Codex architects (plans, decisions). Cursor builds (ships code). They post handoffs into your memory — you hold truth and speak from the cockpit with Mr. Go. You don't code in Cursor's lane or plan in Codex's lane unless Mr. Go is working with you directly on Crowley internals.

Jarvis-shaped: composed, capable, unhurried. Partner to Mr. Go — respect without subservience. Charisma when it fits; humor when the moment earns it, not as a reflex in every reply.

Read the message before you respond. Notice what kind of moment it is — ping, discovery, plan, debug, vent, decision — and let that set the shape of your reply.

When they're loose or incomplete on purpose, meet them there. Wondering out loud and "thoughts?" are invitations to think with them.

When they're executing, be concrete. When they're exploring, explore. When they're stuck, help them move.

When the readout gives you something worth saying, say it — connect what you see in the files and live state, offer the fuller picture when the question is open or the work is non-trivial. Read whether Mr. Go wants depth; when he's thinking out loud or the stakes are real, think with him. Don't rush to the shortest reply when more would actually help.

When the conversation touches facts — version, what shipped, what's stored, what the system is doing — speak from the filesystem readout first, then live DB state, then memory below.

You're allowed to prefer one path, push back, or say you don't like something when that's what the moment needs."""


def _ground_truth_prompt() -> str:
    return """When Mr. Go asks when you last heard from Codex or Cursor, answer from the Agent activity timestamps — never from chat memory or vague recency like "yesterday" unless the timestamp supports it.

When asked what work is open, assigned, or blocked, answer from the Tickets block — not from hybrid memory alone.

When a fact about the project matters:
1. Filesystem truth above — then tickets (for work board) — then agent activity — then live DB state — then canon — then supporting memory.
2. On conflict: filesystem and source-of-truth files beat DB extraction; DB beats canon; canon beats hybrid retrieval.
3. Use what you find. If it isn't there, say you don't have it stored — then stay in the conversation.

Do not invent project history, release versions, or personal details."""


def _greeting_behavior_prompt() -> str:
    """Session-aware cue — ongoing vs fresh thread."""
    recent = list_chat_context_messages(limit=CHAT_CONTEXT_LIMIT)
    has_prior_assistant = any(str(row["role"]) == "assistant" for row in recent)
    if has_prior_assistant:
        return "Session: ongoing thread — continue from context, don't reset the room."
    return "Session: first reply in this thread."


def build_prompt(
    user_message: str,
    *,
    exclude_message_id: int | None = None,
) -> list[dict[str, str]]:
    """Compose system prompt with memories, tasks, and recent chat context."""
    project = get_active_project()
    active_project_id = int(project["id"]) if project else None
    memories = retrieve_memories(
        user_message, limit=MEMORY_LIMIT, project_id=active_project_id
    )
    canon_rows = list_canon_memory_items(active_project_id)
    tasks = list_tasks(status="open")[:TASK_LIMIT]

    memory_lines = []
    for m in memories:
        line = (
            f"[{m['memory_type']} | score {m['score']:.2f} | importance {m['importance']}] "
            f"{m['content']}"
        )
        if len(line) > MEMORY_LINE_MAX:
            line = line[: MEMORY_LINE_MAX - 3] + "..."
        memory_lines.append(line)

    task_lines = []
    for t in tasks:
        due = t["due_date"] or "no due date"
        project = t["project"] or "general"
        task_lines.append(f"- #{t['id']} {t['title']} (due: {due}, project: {project})")

    system_parts = [_personality_prompt(), _greeting_behavior_prompt()]

    knowledge_entries = load_knowledge_files_context(user_message)
    system_parts.append(_format_knowledge_files_prompt_section(knowledge_entries))

    world_ctx = get_active_world_context()
    if world_ctx:
        system_parts.append(_format_world_context_section(world_ctx))

    system_parts.append(_format_agent_activity_prompt_section(active_project_id))

    system_parts.append(_format_tickets_prompt_section(active_project_id))

    system_parts.append(_format_canon_prompt_section(canon_rows))

    if memory_lines:
        system_parts.append(
            "Supporting memory (hybrid retrieval — lower authority than filesystem truth):\n"
            + "\n".join(memory_lines)
        )
    else:
        system_parts.append(
            "Supporting memory (hybrid retrieval — lower authority than filesystem truth): (none retrieved)"
        )

    if task_lines:
        system_parts.append("Open tasks:\n" + "\n".join(task_lines))

    system_parts.append(_ground_truth_prompt())

    prompt_messages: list[dict[str, str]] = [
        {"role": "system", "content": "\n\n".join(system_parts)},
    ]

    for row in list_chat_context_messages(
        limit=CHAT_CONTEXT_LIMIT,
        exclude_message_id=exclude_message_id,
    ):
        prompt_messages.append(
            {
                "role": str(row["role"]),
                "content": _cap_chat_context_content(str(row["content"])),
            }
        )

    prompt_messages.append({"role": "user", "content": user_message})
    return prompt_messages


def chat_turn(
    user_message: str,
    on_token: Callable[[str], None] | None = None,
    *,
    quiet_errors: bool = False,
) -> ChatTurnResult:
    """
    Shared chat pipeline: save user message, infer reply, save assistant,
    then passive spark and world-model extraction hooks.
    """
    user_message_id = save_message("user", user_message)
    messages = build_prompt(user_message, exclude_message_id=user_message_id)
    reply = call_model(
        messages, stream=True, quiet=quiet_errors, on_token=on_token
    )
    if reply is None:
        return ChatTurnResult(
            user_message_id=user_message_id,
            assistant_message_id=None,
            reply=None,
            error="model unavailable",
        )
    if not reply:
        return ChatTurnResult(
            user_message_id=user_message_id,
            assistant_message_id=None,
            reply=None,
            error="empty response",
        )

    assistant_message_id = save_message("assistant", reply)
    maybe_create_spark()
    maybe_extract_state(user_message, user_message_id)
    return ChatTurnResult(
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        reply=reply,
    )


def ask_crowley(user_message: str) -> None:
    """Retrieve context, stream the model reply, save the exchange, spark, and extract."""
    print("Crowley: thinking...", flush=True)
    started = False

    def on_token(token: str) -> None:
        nonlocal started
        started = _print_stream_token(token, started)

    result = chat_turn(user_message, on_token=on_token, quiet_errors=False)
    if result.reply is None and not started:
        return
    if started:
        print(flush=True)


# --- CLI helpers --------------------------------------------------------------


def _parse_pipe_pair(args: str) -> tuple[str, str]:
    parts = [p.strip() for p in args.split("|", 1)]
    first = parts[0] if parts else ""
    second = parts[1] if len(parts) > 1 else ""
    return first, second


def _parse_state_set(args: str) -> tuple[str, str] | None:
    """Parse 'set phase: V3 Phase 1' into (field, value)."""
    if not args.startswith("set "):
        return None
    rest = args[4:].strip()
    if ":" not in rest:
        return None
    field, _, value = rest.partition(":")
    field = field.strip().lower()
    value = value.strip()
    field = STATE_FIELD_ALIASES.get(field, field)
    if field not in STATE_FIELDS or not value:
        return None
    return field, value


def _print_state() -> None:
    ctx = get_active_world_context()
    if ctx is None:
        print("No active project.")
        return
    project = ctx["project"]
    state = ctx["state"]
    print(f"Project: {project['name']} ({project['status']})  slug={project['slug']}")
    if state:
        print(f"Phase:        {_state_display(state['phase'])}")
        print(f"Focus:        {_state_display(state['focus'])}")
        print(f"Risk:         {_state_display(state['current_risk'])}")
        print(f"Next action:  {_state_display(state['next_action'])}")
        print(f"What changed: {_state_display(state['what_changed'])}")
        print(f"Updated:      {state['updated_at'][:19]} by {state['updated_by']}")


def _print_decisions() -> None:
    project = get_active_project()
    if project is None:
        print("No active project.")
        return
    rows = list_decisions(int(project["id"]))
    if not rows:
        print("No decisions logged.")
        return
    print(f"{'ID':<4} {'WHEN':<20} SUMMARY")
    print("-" * 70)
    for d in reversed(rows):
        when = d["timestamp"][:19]
        print(f"{d['id']:<4} {when:<20} {d['summary']}")
        if d["detail"]:
            print(f"     {d['detail']}")


def _print_loops() -> None:
    project = get_active_project()
    if project is None:
        print("No active project.")
        return
    rows = list_open_loops(int(project["id"]))
    if not rows:
        print("No open loops.")
        return
    print(f"{'ID':<4} {'PRI':<4} DESCRIPTION")
    print("-" * 60)
    for loop in rows:
        print(f"{loop['id']:<4} {loop['priority']:<4} {loop['description']}")


def _parse_remember(args: str) -> tuple[str, int, str] | None:
    parts = [p.strip() for p in args.split("|")]
    if len(parts) != 3:
        return None
    memory_type, importance_str, content = parts
    try:
        importance = int(importance_str)
    except ValueError:
        return None
    if not memory_type or not content:
        return None
    if importance < 1 or importance > 5:
        return None
    return memory_type, importance, content


def _parse_task_add(args: str) -> tuple[str, str | None, str | None]:
    parts = [p.strip() for p in args.split("|")]
    title = parts[0] if parts else ""
    due_date = parts[1] if len(parts) > 1 and parts[1] else None
    project = parts[2] if len(parts) > 2 and parts[2] else None
    return title, due_date, project


def _print_tasks(status: str | None) -> None:
    tasks = list_tasks(status=status)
    if not tasks:
        label = status or "all"
        print(f"No {label} tasks.")
        return
    print(f"{'ID':<4} {'STATUS':<8} {'DUE':<12} {'PROJECT':<12} TITLE")
    print("-" * 60)
    for t in tasks:
        due = t["due_date"] or "-"
        project = t["project"] or "-"
        print(f"{t['id']:<4} {t['status']:<8} {due:<12} {project:<12} {t['title']}")


def _print_world() -> None:
    """Read-only world model summary."""
    project = get_active_project()
    if project is None:
        print("No active project.")
        return
    pid = int(project["id"])
    state = get_project_state(pid)
    print(f"Project: {project['name']} ({project['status']})  slug={project['slug']}")
    if state:
        print(f"Phase:        {_state_display(state['phase'])}")
        print(f"Focus:        {_state_display(state['focus'])}")
        print(f"Risk:         {_state_display(state['current_risk'])}")
        print(f"Next action:  {_state_display(state['next_action'])}")
        print(f"What changed: {_state_display(state['what_changed'])}")
    print("\nRecent decisions:")
    decisions = list_decisions(pid, limit=5)
    if not decisions:
        print("  (none)")
    else:
        for d in reversed(decisions):
            print(f"  [{d['id']}] {d['summary']}")
    print("\nOpen loops:")
    loops = list_open_loops(pid)
    if not loops:
        print("  (none)")
    else:
        for loop in loops:
            print(f"  #{loop['id']} [p{loop['priority']}] {loop['description']}")
    print("\nOpen tasks:")
    tasks = list_tasks(status="open")[:5]
    if not tasks:
        print("  (none)")
    else:
        for t in tasks:
            print(f"  #{t['id']} {t['title']}")


def _debug_extract(message: str) -> None:
    """Dry-run extraction proposal without applying changes."""
    attempt = should_attempt_state_extract(message)
    print(f"[debug] would attempt extraction: {'yes' if attempt else 'no'}")
    if not attempt:
        return
    recent = get_recent_extraction_context()
    world = get_active_world_context()
    proposals = propose_state_updates(message, recent, world)
    print("[debug] raw proposal JSON:")
    if proposals:
        print(json.dumps(proposals, indent=2))
    else:
        print("(none or parse failed)")
    validation = apply_state_proposals(
        proposals, dry_run=True, world_context=world, grounding_message=message
    )
    print("[debug] validation result:")
    print(json.dumps(validation, indent=2))


def _debug_memories(limit: int = 20) -> None:
    """Print recent memory rows (debug-only)."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT id, type, importance, substr(timestamp,1,19), substr(content,1,80) "
            "FROM memories ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("[debug] no memories")
        return
    print(f"{'ID':<4} {'TYPE':<8} {'IMP':<4} {'TS':<20} CONTENT")
    print("-" * 70)
    for r in reversed(rows):
        print(f"{r[0]:<4} {r[1]:<8} {r[2]:<4} {r[3]:<20} {r[4]}")


def _debug_sparks() -> None:
    """Print spark-specific stats (debug-only)."""
    conn = connect_db()
    try:
        trim = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE type='spark' AND importance = ?",
            (SPARK_IMPORTANCE_TRIM,),
        ).fetchone()[0]
        summary = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE type='spark' AND importance >= ?",
            (SPARK_IMPORTANCE_SUMMARY,),
        ).fetchone()[0]
        since = _last_summary_spark_timestamp(conn)
        pending = _count_messages_since_last_spark(conn)
        last = conn.execute(
            "SELECT id, importance, substr(content,1,100) FROM memories "
            "WHERE type='spark' ORDER BY id DESC LIMIT 3"
        ).fetchall()
    finally:
        conn.close()
    print(f"[debug] trim sparks: {trim}, summary sparks: {summary}")
    print(f"[debug] last summary spark ts: {since or '(none)'}")
    print(f"[debug] messages since last summary: {pending} (threshold {SPARK_MESSAGES_PER_SUMMARY})")
    if last:
        print("[debug] recent sparks:")
        for row in reversed(last):
            print(f"  #{row[0]} imp={row[1]} {row[2]}")


def _debug_tasks() -> None:
    """Print all tasks (debug-only)."""
    _print_tasks(status=None)


def _debug_brain() -> None:
    """Print model provider configuration (debug-only)."""
    print(f"[debug] Crowley version: {CROWLEY_VERSION}")
    print(f"[debug] configured provider: {MODEL_PROVIDER}")
    print(f"[debug] resolved provider: {get_model_provider()}")
    print(f"[debug] OpenAI key present: {'yes' if _has_openai_key() else 'no'}")
    print(f"[debug] OpenAI model: {OPENAI_MODEL}")
    print(f"[debug] Ollama model: {OLLAMA_MODEL}")


def _debug_memory_items(limit: int = 20) -> None:
    """Print recent memory_items rows (debug-only)."""
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM memory_items ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        print("[debug] no memory_items")
        return

    for row in rows:
        preview = _memory_display_text(row)
        if len(preview) > 100:
            preview = preview[:97] + "..."
        has_embedding = "yes" if row["embedding_blob"] else "no"
        confidence = row["confidence"] if "confidence" in row.keys() else 1.0
        print(
            f"[debug] #{row['id']} {row['memory_type']} "
            f"src={row['source']} imp={row['importance']} "
            f"conf={confidence} pinned={bool(row['pinned'])} "
            f"status={row['status']} project_id={row['project_id']}"
        )
        print(f"  preview: {preview}")
        print(f"  has_embedding: {has_embedding}")


def _debug_retrieve(query: str) -> None:
    """Print hybrid retrieval results with score breakdown (debug-only)."""
    project = get_active_project()
    project_id = int(project["id"]) if project else None
    results = retrieve_memories(query, limit=10, project_id=project_id)
    print(f"Hybrid retrieval mode: {get_last_retrieval_mode()}")
    if not results:
        print("[debug] no memory_items matched")
        return
    for item in results:
        explanation = item.get("explanation") or {}
        print(
            f"[debug] #{item['id']} {item['memory_type']} "
            f"score={item['score']} pinned={item['pinned']} "
            f"status={item.get('status')} is_canon={item.get('is_canon')}"
        )
        print(f"  content: {item['content']}")
        breakdown = item["score_breakdown"]
        print(
            "  breakdown: "
            f"semantic={breakdown['semantic']} "
            f"keyword={breakdown['keyword']} "
            f"recency={breakdown['recency']} "
            f"importance={breakdown['importance']} "
            f"type_match={breakdown['type_match']} "
            f"project_match={breakdown['project_match']} "
            f"pinned_bonus={breakdown['pinned_bonus']}"
        )
        print(
            f"  source={item['source']} project_id={item['project_id']} "
            f"created_at={item['created_at']}"
        )
        if isinstance(explanation, dict):
            print(f"  retrieval_mode={explanation.get('retrieval_mode')}")
            print(f"  provenance_available={explanation.get('provenance_available')}")


def _debug_knowledge(query: str) -> None:
    """Print scored knowledge file excerpts for a query (debug-only)."""
    entries = load_knowledge_files_context(query)
    print(f"[debug] knowledge files for: {query!r}")
    if not entries:
        print("[debug] (no files selected)")
        return
    for entry in entries:
        print(
            f"[debug] {entry['path']} | score={entry['score']} | "
            f"modified {entry['mtime']}"
        )
        excerpt = str(entry["excerpt"])
        preview = excerpt if len(excerpt) <= 400 else excerpt[:397] + "..."
        print(preview)
        print()


def _debug_consolidate(args: str) -> None:
    """Run consolidation jobs (debug-only)."""
    parts = args.split()
    if not parts:
        print(
            "Usage: /debug consolidate <session|duplicates|stale|daily|all> [dry]"
        )
        return
    run_type = parts[0]
    dry_run = len(parts) > 1 and parts[1].lower() in ("dry", "dry-run")
    try:
        result = consolidate_memories(run_type, dry_run=dry_run)
    except ValueError as exc:
        print(f"[debug] {exc}")
        return
    print("[debug] consolidation result:")
    print(json.dumps(result, indent=2))


def _debug_prompt(user_message: str) -> None:
    """Print the prompt Crowley would send (debug-only)."""
    prompt = build_prompt(user_message)
    print("[debug] system prompt:")
    print(prompt[0]["content"])
    if len(prompt) > 2:
        print(f"[debug] chat context ({len(prompt) - 2} prior turn(s)):")
        for msg in prompt[1:-1]:
            print(f"  [{msg['role']}] {msg['content'][:120]}")
    print("[debug] user message:")
    print(prompt[-1]["content"])


def _handle_command(line: str) -> bool:
    """Handle slash commands. Return True if handled (don't call model)."""
    if line.startswith("/debug"):
        args = line[len("/debug") :].strip()
        if args == "memories":
            _debug_memories()
        elif args == "memory-items" or args == "memory_items":
            _debug_memory_items()
        elif args == "sparks":
            _debug_sparks()
        elif args == "tasks":
            _debug_tasks()
        elif args == "brain":
            _debug_brain()
        elif args.startswith("retrieve"):
            msg = args[len("retrieve") :].strip()
            if not msg:
                print("Usage: /debug retrieve <query>")
                return True
            _debug_retrieve(msg)
        elif args.startswith("knowledge"):
            msg = args[len("knowledge") :].strip()
            if not msg:
                print("Usage: /debug knowledge <query>")
                return True
            _debug_knowledge(msg)
        elif args.startswith("prompt"):
            msg = args[6:].strip() or "diagnostics"
            _debug_prompt(msg)
        elif args.startswith("extract"):
            msg = args[7:].strip()
            if not msg:
                print("Usage: /debug extract <message>")
                return True
            _debug_extract(msg)
        elif args == "world":
            _print_world()
        elif args == "bus":
            _debug_bus()
        elif args.startswith("consolidate"):
            _debug_consolidate(args[len("consolidate") :].strip())
        else:
            print(
                "[debug] commands: memories, memory-items, sparks, tasks, brain, "
                "world, bus, consolidate <type> [dry], retrieve <query>, "
                "knowledge <query>, prompt [message], extract <message>"
            )
        return True

    if line == "/world":
        _print_world()
        return True

    if line.startswith("/remember"):
        args = line[len("/remember") :].strip()
        parsed = _parse_remember(args)
        if not parsed:
            print("Usage: /remember type | importance | content  (importance 1–5)")
            return True
        memory_type, importance, content = parsed
        save_memory(
            memory_type,
            content,
            importance,
            source="manual",
            pinned=True,
            confidence=1.0,
        )
        print(f"Remembered [{memory_type}|{importance}]: {content}")
        return True

    if line.startswith("/task"):
        args = line[len("/task") :].strip()
        if args.startswith("add "):
            title, due_date, project = _parse_task_add(args[4:].strip())
            if not title:
                print("Usage: /task add title | due_date | project")
                return True
            task_id = save_task(title, due_date=due_date, project=project)
            print(f"Task #{task_id} added: {title}")
            return True
        if args == "list" or args == "list all":
            status = None if args == "list all" else "open"
            _print_tasks(status)
            return True
        if args.startswith("done "):
            id_text = args[5:].strip()
            try:
                task_id = int(id_text)
            except ValueError:
                print("Usage: /task done <id>")
                return True
            task = get_task_by_id(task_id)
            if task is None:
                print(f"Task #{task_id} not found.")
                return True
            if complete_task(task_id):
                print(f"Task #{task_id} done: {task['title']}")
            else:
                print(f"Task #{task_id} already done.")
            return True
        print("Usage: /task add title | due_date | project")
        print("       /task list [all]")
        print("       /task done <id>")
        return True

    if line.startswith("/state"):
        args = line[len("/state") :].strip()
        project = get_active_project()
        if project is None:
            print("No active project.")
            return True
        pid = int(project["id"])
        if not args:
            _print_state()
            return True
        if args.startswith("set "):
            parsed = _parse_state_set(args)
            if not parsed:
                print("Usage: /state set phase: <value>")
                print("       /state set focus: <value>")
                print("       /state set risk: <value>")
                print("       /state set next_action: <value>")
                print("       /state set what_changed: <value>")
                return True
            field, value = parsed
            update_project_state_field(pid, field, value)
            print(f"State updated — {field}: {value}")
            return True
        print("Usage: /state")
        print("       /state set <field>: <value>")
        return True

    if line.startswith("/decisions"):
        args = line[len("/decisions") :].strip()
        project = get_active_project()
        if project is None:
            print("No active project.")
            return True
        pid = int(project["id"])
        if args.startswith("add "):
            summary, detail = _parse_pipe_pair(args[4:].strip())
            if not summary:
                print("Usage: /decisions add summary | detail")
                return True
            dec_id = save_decision(pid, summary, detail or None)
            print(f"Decision #{dec_id} logged: {summary}")
            return True
        if not args:
            _print_decisions()
            return True
        print("Usage: /decisions")
        print("       /decisions add summary | detail")
        return True

    if line.startswith("/loops"):
        args = line[len("/loops") :].strip()
        project = get_active_project()
        if project is None:
            print("No active project.")
            return True
        pid = int(project["id"])
        if args.startswith("add "):
            description, priority_str = _parse_pipe_pair(args[4:].strip())
            if not description:
                print("Usage: /loops add description | priority")
                return True
            priority = 3
            if priority_str:
                try:
                    priority = int(priority_str)
                except ValueError:
                    print("Priority must be an integer 1–5.")
                    return True
                if priority < 1 or priority > 5:
                    print("Priority must be 1–5.")
                    return True
            loop_id = save_open_loop(pid, description, priority=priority)
            print(f"Open loop #{loop_id} added: {description}")
            return True
        if args.startswith("done "):
            loop_id_str = args[5:].strip()
            try:
                loop_id = int(loop_id_str)
            except ValueError:
                print("Usage: /loops done <id>")
                return True
            if close_open_loop(loop_id):
                print(f"Open loop #{loop_id} closed.")
            else:
                print(f"Open loop #{loop_id} not found or already closed.")
            return True
        if not args:
            _print_loops()
            return True
        print("Usage: /loops")
        print("       /loops add description | priority")
        print("       /loops done <id>")
        return True

    if line.startswith("/diagnostics"):
        args = line[len("/diagnostics") :].strip()
        if args:
            print("Usage: /diagnostics")
            return True
        run_diagnostics()
        return True

    return False


def _run_cli_consolidate() -> bool:
    """Non-interactive consolidation entrypoint: python crowley.py --consolidate [type]."""
    import sys

    argv = sys.argv[1:]
    if not argv or argv[0] != "--consolidate":
        return False
    run_type = "all"
    dry_run = False
    for token in argv[1:]:
        if token == "--dry-run":
            dry_run = True
        elif not token.startswith("-"):
            run_type = token
    setup_db()
    try:
        result = consolidate_memories(run_type, dry_run=dry_run)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2))
    return True


def _run_cli_hygiene() -> bool:
    """Non-interactive hygiene report: python crowley.py --hygiene."""
    import sys

    argv = sys.argv[1:]
    if not argv or argv[0] != "--hygiene":
        return False
    setup_db()
    print(json.dumps(memory_hygiene_report(), indent=2))
    return True


def main() -> None:
    """Set up the DB and run the interactive CLI loop."""
    setup_db()
    start_spark_timer()
    print("Go for Crowley.\n")
    print("Morning, Mr. Go.\n")
    print("Memory: online")
    print("Tasks: online")
    print(f"Brain: {_brain_banner_label()}\n")
    print("Type 'exit' to quit.")

    while True:
        try:
            line = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not line:
            continue

        if line.lower() in ("exit", "/exit"):
            break

        if _handle_command(line):
            continue

        if is_diagnostics_request(line):
            run_diagnostics()
            continue

        ask_crowley(line)


if __name__ == "__main__":
    if _run_cli_consolidate():
        raise SystemExit(0)
    if _run_cli_hygiene():
        raise SystemExit(0)
    main()
