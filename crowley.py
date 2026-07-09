#!/usr/bin/env python3
"""Crowley V4.0 — local AI OS with cognitive memory and context orchestration."""

from __future__ import annotations

import json
import os
import re
import struct
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cli_shell
import conversation_runtime
import crowley_core
import agent_sync_bundle
import memory_embeddings
import memory_retrieval
import memory_store
import model_runtime
import ollama
import portable_context
import world_state

if __name__ == "__main__":
    sys.modules.setdefault("crowley", sys.modules[__name__])

try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

# --- local env (optional .env file, never committed) --------------------------


def _load_local_env() -> None:
    """Load KEY=VALUE lines from .env into os.environ if not already set."""
    crowley_core.load_local_env()


_load_local_env()

# --- constants ----------------------------------------------------------------

CROWLEY_VERSION = "4.0.0"
CROWLEY_RELEASE_LABEL = "Crowley V4.0 Cognitive Memory"

USER_NAME = "D"
USER_NAME_PERSONALITY = "Mr. Go"  # occasional flavor; default address is USER_NAME
USER_ACTOR_SLUG = "mr_go"  # ticket/API actor id (unchanged for DB compatibility)

PROJECT_ROOT = crowley_core.PROJECT_ROOT
DEFAULT_DB_PATH = crowley_core.DEFAULT_DB_PATH


def get_db_path() -> Path:
    """Return the active SQLite database path (override, env, or default)."""
    return crowley_core.get_db_path()


def set_db_path(path: Path | str) -> Path:
    """Point Crowley at a specific database file (used by tests)."""
    global DB_PATH
    DB_PATH = crowley_core.set_db_path(path)
    return DB_PATH


def reset_db_path() -> Path:
    """Clear test overrides and return to env/default database path."""
    global DB_PATH
    DB_PATH = crowley_core.reset_db_path()
    return DB_PATH


DB_PATH = get_db_path()
VERSIONS_MD_PATH = PROJECT_ROOT / "VERSIONS.md"
PROJECT_STATE_MD_PATH = PROJECT_ROOT / "docs" / "PROJECT_STATE.md"
PROJECT_FILES_EXCERPT_MAX = 480

KNOWLEDGE_FILES = [
    "VERSIONS.md",
    "docs/WHERE_WE_ARE.md",
    "docs/PROJECT_STATE.md",
    "docs/PRE_V4_QUALITY_PLAN.md",
    "docs/PRE_V4_FUTURE_RELEASE_LADDER.md",
    "docs/PRE_V4_RELEASE_PLAN.md",
    "docs/MEMORY_HIERARCHY.md",
    "docs/ARCHITECTURE.md",
    "docs/V3.9.6_WORKSPACE_POLISH.md",
    "docs/V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md",
    "docs/V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md",
    "docs/V3.9.1_REPOSITORY_AND_CI.md",
    "docs/V3.9.4_AGENT_VISIBILITY.md",
    "docs/V3.9.3_PLANNING_WORKFLOW.md",
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

MODEL_PROVIDER = model_runtime.MODEL_PROVIDER
MODEL_PROVIDER_OPTIONS = model_runtime.MODEL_PROVIDER_OPTIONS
OPENAI_MODEL = model_runtime.OPENAI_MODEL
OLLAMA_MODEL = model_runtime.OLLAMA_MODEL
ANTHROPIC_MODEL_OPTIONS = model_runtime.ANTHROPIC_MODEL_OPTIONS

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

def _resolve_embed_provider_setting() -> str:
    raw = os.environ.get("CROWLEY_EMBED_PROVIDER", "auto").strip().lower()
    if raw in ("off", "auto", "local", "openai"):
        return raw
    return "auto"


def is_test_mode() -> bool:
    """True when CROWLEY_TEST_MODE is enabled (unified CI/local test profile)."""
    return crowley_core.is_test_mode()


TEST_MODE_STUB_REPLY = model_runtime.TEST_MODE_STUB_REPLY


MEMORY_EMBED_PROVIDER = _resolve_embed_provider_setting()
EMBED_MODEL_LOCAL = "all-MiniLM-L6-v2"
EMBED_DIM = 384

_embed_backfill_attempted = False

MEMORY_RETRIEVE_VECTOR_CANDIDATES = 20
MEMORY_RETRIEVE_KEYWORD_CANDIDATES = 20
MEMORY_RETRIEVE_SUMMARY_CANDIDATES = 5
MEMORY_RECENCY_HIGH_DAYS = 7
MEMORY_RECENCY_LOW_DAYS = 90

W_SCORE_SEMANTIC = 0.50
W_SCORE_KEYWORD = 0.20
W_SCORE_RECENCY = 0.08
W_SCORE_IMPORTANCE = 0.12
W_SCORE_TYPE = 0.05
W_SCORE_PROJECT = 0.05
W_SCORE_PINNED_BONUS = 0.10
W_SCORE_OPEN_TICKET_BOOST = 0.12

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
MEMORY_GATE_PROMOTED_TYPES = frozenset({
    "decision",
    "constraint",
    "preference",
    "lesson",
    "qa_result",
    "project_update",
})
MEMORY_GATE_BYPASS_TYPES = frozenset({"summary"})
MEMORY_GATE_BYPASS_SOURCES = frozenset({
    "daily_summary",
    "consolidation",
    "canon",
    "portable_terminal",
})
MEMORY_GATE_CONFIDENCE_MIN = 0.5
MEMORY_GATE_WHY_MIN_LEN = 8

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
_sqlite_vec_loaded_conns: set[int] = set()
_sqlite_vec_failure_reason: str | None = None
_sqlite_vec_failure_logged = False
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
    return crowley_core.now_iso()


def _normalize_text(text: str) -> str:
    return crowley_core.normalize_text(text)


def _truncate(text: str, max_len: int = MAX_TRIM_LEN) -> str:
    return crowley_core.truncate(text, max_len=max_len)


def _tokenize(text: str) -> list[str]:
    return crowley_core.tokenize(text)


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
    return model_runtime._has_openai_key()


def _has_anthropic_key() -> bool:
    return model_runtime._has_anthropic_key()


def _default_anthropic_model() -> str:
    return model_runtime._default_anthropic_model()


def get_brain_settings_path() -> Path:
    """Path to persisted runtime brain preference (provider routing)."""
    return model_runtime.get_brain_settings_path()


def set_brain_settings_path(path: Path | str | None) -> Path | None:
    """Point brain settings at a specific file (tests) or back to default."""
    return model_runtime.set_brain_settings_path(path)


def _normalize_brain_config(raw: dict[str, object] | None) -> dict[str, str | None]:
    return model_runtime._normalize_brain_config(raw)


def _load_brain_config_from_disk() -> dict[str, str | None] | None:
    return model_runtime._load_brain_config_from_disk()


def get_brain_config() -> dict[str, str | None]:
    """Active brain routing config: provider + optional model override."""
    return model_runtime.get_brain_config()


def get_model_provider_setting() -> str:
    """Configured provider mode (persisted when switched in UI)."""
    return model_runtime.get_model_provider_setting()


def set_brain_config(provider: str, model: str | None = None) -> dict[str, str | None]:
    """Persist runtime brain preference and apply immediately."""
    return model_runtime.set_brain_config(provider, model)


def set_model_provider_setting(provider: str) -> str:
    """Persist provider only (legacy API)."""
    return model_runtime.set_model_provider_setting(provider)


def reset_model_provider_setting() -> None:
    """Clear in-memory and on-disk brain preference (tests)."""
    model_runtime.reset_model_provider_setting()


def list_ollama_models(timeout: float = 3.0) -> list[str]:
    """Return installed Ollama model names from the local daemon."""
    return model_runtime.list_ollama_models(timeout=timeout)


def _probe_ollama_reachable(timeout: float = 2.0) -> bool:
    """Lightweight Ollama reachability check (no model load)."""
    return model_runtime._probe_ollama_reachable(timeout=timeout)


def _available_providers() -> list[str]:
    return model_runtime._available_providers(
        has_openai_key=_has_openai_key,
        has_anthropic_key=_has_anthropic_key,
        probe_ollama_reachable=_probe_ollama_reachable,
    )


def get_model_provider() -> str:
    """Return resolved provider for inference."""
    return model_runtime.get_model_provider(
        get_provider_setting=get_model_provider_setting,
        available_providers=_available_providers,
    )


def get_active_model_name() -> str:
    """Return the model id used for the current brain selection."""
    return model_runtime.get_active_model_name(
        get_brain_config_func=get_brain_config,
        get_model_provider_func=get_model_provider,
        list_ollama_models_func=list_ollama_models,
    )


def probe_model_availability() -> dict[str, object]:
    """Structured model availability for health/runtime diagnostics."""
    return model_runtime.probe_model_availability(
        is_test_mode=is_test_mode,
        has_openai_key=_has_openai_key,
        has_anthropic_key=_has_anthropic_key,
        probe_ollama_reachable=_probe_ollama_reachable,
        get_provider_setting=get_model_provider_setting,
        get_model_provider_func=get_model_provider,
    )


def _runtime_retrieval_label(mode: str) -> str:
    return model_runtime._runtime_retrieval_label(mode)


def build_runtime_diagnostics() -> dict[str, object]:
    """Operator-facing runtime block for /api/health."""
    return model_runtime.build_runtime_diagnostics(
        memory_embed_provider=_memory_embed_provider,
        connect_db=connect_db,
        try_load_sqlite_vec=_try_load_sqlite_vec,
        get_sqlite_vec_failure_reason=get_sqlite_vec_failure_reason,
        get_last_retrieval_mode=get_last_retrieval_mode,
        probe_model_availability_func=probe_model_availability,
        is_test_mode=is_test_mode,
    )


def _brain_provider_label(provider: str) -> str:
    return model_runtime._brain_provider_label(
        provider,
        get_model_provider_func=get_model_provider,
    )


def _brain_banner_label() -> str:
    return model_runtime._brain_banner_label(
        get_brain_config_func=get_brain_config,
        get_model_provider_func=get_model_provider,
        get_active_model_name_func=get_active_model_name,
        brain_provider_label_func=_brain_provider_label,
    )


def _brain_provider_models(provider: str) -> list[str]:
    return model_runtime._brain_provider_models(
        provider,
        list_ollama_models_func=list_ollama_models,
    )


def _brain_provider_available(provider: str) -> bool:
    return model_runtime._brain_provider_available(
        provider,
        available_providers=_available_providers,
        has_openai_key=_has_openai_key,
        has_anthropic_key=_has_anthropic_key,
        probe_ollama_reachable=_probe_ollama_reachable,
    )


def get_brain_snapshot() -> dict[str, object]:
    """Runtime brain routing for UI switcher and health."""
    return model_runtime.get_brain_snapshot(
        is_test_mode=is_test_mode,
        get_brain_config_func=get_brain_config,
        get_model_provider_func=get_model_provider,
        get_active_model_name_func=get_active_model_name,
        brain_provider_label_func=_brain_provider_label,
        brain_banner_label_func=_brain_banner_label,
        brain_provider_models_func=_brain_provider_models,
        brain_provider_available_func=_brain_provider_available,
    )


def _print_stream_token(token: str, started: bool) -> bool:
    return model_runtime._print_stream_token(token, started)


def _ollama_chunk_text(chunk: object) -> str:
    """Extract streamable text from an Ollama chat chunk (content or thinking)."""
    return model_runtime._ollama_chunk_text(chunk)


def _iter_ollama_tokens(
    messages: list[dict[str, str]], *, model: str | None = None, think: bool = False
) -> Iterator[str]:
    yield from model_runtime._iter_ollama_tokens(
        messages,
        model=model,
        think=think,
        get_active_model_name_func=get_active_model_name,
    )


def _iter_openai_tokens(
    messages: list[dict[str, str]], *, model: str | None = None
) -> Iterator[str]:
    yield from model_runtime._iter_openai_tokens(
        messages,
        model=model,
        get_active_model_name_func=get_active_model_name,
    )


def _anthropic_payload(
    messages: list[dict[str, str]], model: str, *, stream: bool
) -> dict[str, object]:
    return model_runtime._anthropic_payload(messages, model, stream=stream)


def _iter_anthropic_tokens(
    messages: list[dict[str, str]], *, model: str | None = None
) -> Iterator[str]:
    yield from model_runtime._iter_anthropic_tokens(
        messages,
        model=model,
        get_active_model_name_func=get_active_model_name,
    )


def _call_ollama(
    messages: list[dict[str, str]],
    stream: bool,
    *,
    model: str | None = None,
    think: bool = False,
) -> str:
    return model_runtime._call_ollama(
        messages,
        stream,
        model=model,
        think=think,
        get_active_model_name_func=get_active_model_name,
        iter_ollama_tokens=_iter_ollama_tokens,
    )


def _call_openai(
    messages: list[dict[str, str]], stream: bool, *, model: str | None = None
) -> str:
    return model_runtime._call_openai(
        messages,
        stream,
        model=model,
        get_active_model_name_func=get_active_model_name,
        iter_openai_tokens=_iter_openai_tokens,
    )


def _call_anthropic(
    messages: list[dict[str, str]], stream: bool, *, model: str | None = None
) -> str:
    return model_runtime._call_anthropic(
        messages,
        stream,
        model=model,
        get_active_model_name_func=get_active_model_name,
        iter_anthropic_tokens=_iter_anthropic_tokens,
    )


def _iter_provider_tokens(
    provider: str, messages: list[dict[str, str]]
) -> Iterator[str]:
    yield from model_runtime._iter_provider_tokens(
        provider,
        messages,
        iter_openai_tokens=_iter_openai_tokens,
        iter_anthropic_tokens=_iter_anthropic_tokens,
        iter_ollama_tokens=_iter_ollama_tokens,
    )


def _call_provider(
    provider: str, messages: list[dict[str, str]], stream: bool
) -> str:
    return model_runtime._call_provider(
        provider,
        messages,
        stream,
        call_openai=_call_openai,
        call_anthropic=_call_anthropic,
        call_ollama=_call_ollama,
    )


def _auto_fallback_providers(primary: str) -> list[str]:
    return model_runtime._auto_fallback_providers(primary)


def iter_model_tokens(
    messages: list[dict[str, str]], *, quiet: bool = True
) -> Iterator[str]:
    """Yield completion tokens from the resolved provider."""
    yield from model_runtime.iter_model_tokens(
        messages,
        quiet=quiet,
        is_test_mode=is_test_mode,
        get_model_provider_func=get_model_provider,
        get_model_provider_setting_func=get_model_provider_setting,
        has_openai_key=_has_openai_key,
        has_anthropic_key=_has_anthropic_key,
        iter_provider_tokens=_iter_provider_tokens,
        available_providers=_available_providers,
        auto_fallback_providers=_auto_fallback_providers,
    )


def call_model(
    messages: list[dict[str, str]],
    stream: bool = True,
    quiet: bool = False,
    on_token: Callable[[str], None] | None = None,
) -> str | None:
    """Call the configured model provider."""
    return model_runtime.call_model(
        messages,
        stream=stream,
        quiet=quiet,
        on_token=on_token,
        is_test_mode=is_test_mode,
        get_model_provider_func=get_model_provider,
        get_model_provider_setting_func=get_model_provider_setting,
        has_openai_key=_has_openai_key,
        has_anthropic_key=_has_anthropic_key,
        call_provider=_call_provider,
        iter_model_tokens_func=iter_model_tokens,
        available_providers=_available_providers,
        auto_fallback_providers=_auto_fallback_providers,
        print_stream_token=_print_stream_token,
    )


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
    return crowley_core.row_to_dict(row)


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
    return crowley_core.connect_db()


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
                legacy_memory_id INTEGER UNIQUE,
                metadata_json TEXT
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
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY,
                recorded_at TEXT NOT NULL,
                metric_type TEXT NOT NULL,
                value REAL,
                label TEXT,
                payload TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_system_metrics_type_time
                ON system_metrics(metric_type, recorded_at);
            CREATE TABLE IF NOT EXISTS activity_pulses (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                agent TEXT NOT NULL,
                verb TEXT NOT NULL,
                ticket_id INTEGER,
                summary TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_activity_pulses_project_time
                ON activity_pulses(project_id, created_at);
            """
        )
        _seed_default_project(conn)
        try:
            _ensure_memory_backend(conn)
        except Exception:
            pass
        try:
            import write_audit

            write_audit.ensure_write_audit_table(conn)
            import conflict_engine

            conflict_engine.ensure_conflicts_table(conn)
            import observability_store

            observability_store.ensure_tables(conn)
            import sparks

            sparks.setup_spark_tables(conn)
        except Exception:
            pass
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


def get_active_project(*args, **kwargs) -> sqlite3.Row | None:
    return world_state.get_active_project(sys.modules[__name__], *args, **kwargs)



def get_project_by_slug(*args, **kwargs) -> sqlite3.Row | None:
    return world_state.get_project_by_slug(sys.modules[__name__], *args, **kwargs)



def get_project_state(*args, **kwargs) -> sqlite3.Row | None:
    return world_state.get_project_state(sys.modules[__name__], *args, **kwargs)



def update_project_state_field(*args, **kwargs) -> None:
    return world_state.update_project_state_field(sys.modules[__name__], *args, **kwargs)



def save_decision(*args, **kwargs) -> int:
    return world_state.save_decision(sys.modules[__name__], *args, **kwargs)



def list_decisions(*args, **kwargs) -> list[sqlite3.Row]:
    return world_state.list_decisions(sys.modules[__name__], *args, **kwargs)



def save_open_loop(*args, **kwargs) -> int:
    return world_state.save_open_loop(sys.modules[__name__], *args, **kwargs)



def list_open_loops(*args, **kwargs) -> list[sqlite3.Row]:
    return world_state.list_open_loops(sys.modules[__name__], *args, **kwargs)



def close_open_loop(*args, **kwargs) -> bool:
    return world_state.close_open_loop(sys.modules[__name__], *args, **kwargs)



def _state_display(value: str | None) -> str:
    if value is None or value == "":
        return "(unset)"
    return value


def get_active_world_context(*args, **kwargs) -> dict[str, object] | None:
    return world_state.get_active_world_context(sys.modules[__name__], *args, **kwargs)



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
    return memory_store.list_recent_memory_items(sys.modules[__name__], limit)



def count_memory_items_by_status() -> dict[str, int]:
    """Return memory_items counts grouped by status."""
    return memory_store.count_memory_items_by_status(sys.modules[__name__])



def list_memory_items(
    *,
    q: str | None = None,
    source: str | None = None,
    agent_id: str | None = None,
    memory_tier: str | None = None,
    memory_type: str | None = None,
    status: str | None = "active",
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[sqlite3.Row], int]:
    """Return filtered memory_items plus total count before pagination."""
    return memory_store.list_memory_items(
        sys.modules[__name__],
        q=q,
        source=source,
        agent_id=agent_id,
        memory_tier=memory_tier,
        memory_type=memory_type,
        status=status,
        limit=limit,
        offset=offset,
    )



def get_memory_item_api_by_id(memory_id: int) -> dict[str, object] | None:
    """Return one memory item for read APIs (any status)."""
    return memory_store.get_memory_item_api_by_id(sys.modules[__name__], memory_id)



def get_portable_session_api(session_receipt_id: int) -> dict[str, object] | None:
    """Portable terminal session receipt plus linked sparks."""
    conn = connect_db()
    try:
        row = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE id = ? AND source = ? AND memory_type = 'summary'
            """,
            (int(session_receipt_id), PORTABLE_TERMINAL_SOURCE),
        ).fetchone()
        if row is None:
            return None
        sparks = _portable_session_sparks(conn, int(session_receipt_id))
    finally:
        conn.close()
    return {
        "session": _memory_item_api_dict(row),
        "sparks": [_memory_item_api_dict(spark) for spark in sparks],
    }


def list_recent_memory_updates(*, limit: int = 20) -> list[dict[str, object]]:
    """Recent memory_items ordered by updated_at for inspect.recent_updates."""
    return memory_store.list_recent_memory_updates(sys.modules[__name__], limit=limit)



def build_memory_lineage(memory_id: int) -> dict[str, object] | None:
    """Lineage for a memory item: merged_into, metadata promotion fields."""
    return memory_store.build_memory_lineage(sys.modules[__name__], memory_id)



def explain_memory_in_retrieval(
    memory_id: int, *, q: str | None = None
) -> dict[str, object] | None:
    """Explain why a memory appears in retrieval for a query."""
    return memory_store.explain_memory_in_retrieval(sys.modules[__name__], memory_id, q=q)



def build_writeback_inspect_result(session_receipt_id: int) -> dict[str, object] | None:
    """Inspectable writeback result for one portable session."""
    session = get_portable_session_api(session_receipt_id)
    if session is None:
        return None
    conn = connect_db()
    try:
        session_row = conn.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (int(session_receipt_id),),
        ).fetchone()
        if session_row is None:
            return None
        spark_rows = _portable_session_sparks(conn, int(session_receipt_id))
        is_fixture = _is_test_fixture_portable_session(session_row, spark_rows)
        canonical_ids, duplicate_map = _canonical_staged_spark_ids(spark_rows)
        spark_details: list[dict[str, object]] = []
        for spark_row in spark_rows:
            evaluation = _evaluate_portable_spark_acceptance(
                session_row=session_row,
                spark_row=spark_row,
                spark_rows=spark_rows,
                is_test_fixture=is_fixture,
                canonical_ids=canonical_ids,
                conn=conn,
            )
            spark_id = int(spark_row["id"])
            destination_id: int | None = spark_id
            if evaluation.get("duplicate_of") is not None:
                destination_id = int(evaluation["duplicate_of"])
            elif str(spark_row["status"]) == "active":
                destination_id = spark_id
            elif str(spark_row["status"]) == "merged" and spark_row["merged_into_id"]:
                destination_id = int(spark_row["merged_into_id"])
            spark_details.append(
                {
                    **evaluation,
                    "destination_memory_id": destination_id,
                    "current_status": str(spark_row["status"] or ""),
                }
            )
    finally:
        conn.close()
    return {
        "session_receipt_id": int(session_receipt_id),
        "session": session["session"],
        "sparks": session["sparks"],
        "evaluations": spark_details,
    }


def list_recent_portable_ingests(*, limit: int = 20) -> list[dict[str, object]]:
    """Recent chatgpt portable writeback ingests for inspect.recent_ingests."""
    limit = max(1, min(int(limit), 50))
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE source = ? AND memory_type = 'summary'
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (PORTABLE_TERMINAL_SOURCE, limit),
        ).fetchall()
        ingests: list[dict[str, object]] = []
        for row in rows:
            session_id = int(row["id"])
            meta = _memory_item_metadata(row)
            surface = str(meta.get("surface") or "").strip().lower()
            sparks = _portable_session_sparks(conn, session_id)
            ingests.append(
                {
                    "session_receipt_id": session_id,
                    "created_at": str(row["created_at"]),
                    "surface": surface,
                    "summary": str(row["content"] or ""),
                    "spark_count": len(sparks),
                    "spark_ids": [int(s["id"]) for s in sparks],
                }
            )
        return ingests
    finally:
        conn.close()


def enrich_writeback_ingest_result(result: dict[str, object]) -> dict[str, object]:
    """Add inspectable summaries to writeback ingest response (#814)."""
    if result.get("status") != "ok":
        return result
    enriched = dict(result)
    session_id = result.get("session_receipt_id")
    if session_id is not None:
        receipt = get_memory_item_api_by_id(int(session_id))
        if receipt is not None:
            enriched["session_receipt"] = {
                "id": receipt.get("id"),
                "summary": receipt.get("content"),
                "created_at": receipt.get("created_at"),
            }
    spark_summaries: list[dict[str, object]] = []
    for spark_id in result.get("spark_ids") or []:
        spark = get_memory_item_api_by_id(int(spark_id))
        if spark is None:
            continue
        spark_summaries.append(
            {
                "id": spark.get("id"),
                "status": spark.get("status"),
                "summary": spark.get("summary"),
                "content_preview": _truncate(str(spark.get("content") or ""), 160),
                "session_receipt_id": session_id,
            }
        )
    enriched["sparks"] = spark_summaries
    enriched["inspect_tool"] = "inspect.writeback_result"
    enriched["inspect_args"] = {"session_receipt_id": session_id}
    return enriched


def _read_doc_excerpt(path: Path, *, max_lines: int = 40) -> str:
    if not path.is_file():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()[:max_lines]
    return "\n".join(lines)


def build_release_planning_bundle() -> dict[str, object]:
    """Bounded filesystem release truth for GPT planning."""
    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    return {
        "version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "state": _state_payload_for_api(state) if state is not None else None,
        "versions_excerpt": _read_doc_excerpt(PROJECT_ROOT / "VERSIONS.md", max_lines=25),
        "where_we_are_excerpt": _read_doc_excerpt(
            PROJECT_ROOT / "docs" / "WHERE_WE_ARE.md", max_lines=55
        ),
        "project_state_excerpt": _read_doc_excerpt(
            PROJECT_ROOT / "docs" / "PROJECT_STATE.md", max_lines=35
        ),
    }


def build_planning_ticket_bundle(ticket_id: int) -> dict[str, object] | None:
    """Ticket detail plus task-frame context for implementation planning."""
    import tickets as tickets_mod

    detail = tickets_mod.get_ticket_detail(ticket_id, include_memories=True)
    if detail is None:
        return None
    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    task_frame = build_task_frame_context(project_id, "chatgpt")
    return {
        "ticket": detail,
        "task_frame": task_frame,
        "release": {
            "version": CROWLEY_VERSION,
            "release_label": CROWLEY_RELEASE_LABEL,
        },
    }


def build_qa_visibility_bundle() -> dict[str, object]:
    """Codex-style QA visibility without shell access."""
    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    hygiene = memory_hygiene_report_api()
    tickets_summary = build_tickets_summary(project_id, "chatgpt") if project_id else {}
    conn = connect_db()
    try:
        conn.execute("SELECT 1").fetchone()
        db_status = "ok"
    except Exception:
        db_status = "error"
    finally:
        conn.close()
    bundle: dict[str, object] = {
        "version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "db": db_status,
        "runtime": build_runtime_diagnostics(),
        "embed_provider": _memory_embed_provider(),
        "hygiene": hygiene,
        "tickets": {
            "open_total": tickets_summary.get("open_total"),
            "assigned_to_chatgpt": tickets_summary.get("assigned_to_agent"),
            "blocked": tickets_summary.get("blocked"),
        },
        "test_mode": os.environ.get("CROWLEY_TEST_MODE", "").strip() in {"1", "true", "yes"},
    }
    try:
        import github_read as _github_read

        bundle["github"] = _github_read.github_status()
    except Exception as exc:
        name = type(exc).__name__
        if name == "GitHubNotConfiguredError":
            bundle["github"] = {"configured": False}
        elif name == "GitHubReadError" or isinstance(exc, RuntimeError):
            bundle["github"] = {"configured": True, "error": str(exc)}
        else:
            raise
    return bundle


def get_decision_api_by_id(decision_id: int) -> dict[str, object] | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM decisions WHERE id = ?",
            (int(decision_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return row_to_dict(row)


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
    "lesson",
})
AGENT_SYNC_QUERY = "recent work by other agents current project changes blockers next action"
AGENT_SYNC_DECISIONS_CAP = 5
AGENT_SYNC_CONSTRAINTS_CAP = 5
AGENT_SYNC_OTHER_EVENTS_CAP = 5
AGENT_SYNC_OWN_EVENTS_CAP = 3
AGENT_SYNC_MEMORIES_MIN = 5
AGENT_SYNC_MEMORIES_MAX = 8
AGENT_SYNC_BUNDLE_SHAPE = "task_frame_v3910"
AGENT_SYNC_BUNDLE_SHAPE_LEGACY = "slim_v399"
WORLD_RELEVANT_MEMORIES_CAP = 6
SUPPORTING_MEMORIES_CAP = 4
TASK_FRAME_WORKING_ON_CAP = 6
ACTIVITY_PULSE_VERBS = frozenset(
    {"session_start", "claimed", "working", "note", "handoff", "minted", "closed"}
)
ACTIVITY_PULSE_AGENTS = frozenset({"cursor", "codex", "crowley", USER_ACTOR_SLUG})
ACTIVITY_PULSE_WINDOW_MINUTES = 45
ACTIVITY_WIRE_DEDUPE_MINUTES = 2
ACTIVITY_WIRE_STALE_MINUTES = 30
ACTIVITY_WIRE_AMBIENT_MIN_REAL = 2
ACTIVITY_WIRE_AGENT_STALE_HOURS = 6
ACTIVITY_WIRE_WORLD_CAP = 15
ACTIVITY_WIRE_SYNC_CAP = 5
PORTABLE_PACKET_VERSION = "1"
PORTABLE_PACKET_MAX_CHARS = 12_000
PORTABLE_PACKET_MEMORY_CAP = 4
PORTABLE_PACKET_WORKING_CAP = 5
PORTABLE_PACKET_WIRE_CAP = 3
PORTABLE_PACKET_DECISIONS_CAP = 5
PORTABLE_PACKET_CONSTRAINTS_CAP = 5
PORTABLE_WRITEBACK_LANES = (
    "learning",
    "work",
    "relationships",
    "money",
    "health",
    "operating_style",
)
PORTABLE_WRITEBACK_FORMAT = "crowley_terminal_writeback_v1"
PORTABLE_WRITEBACK_SENSITIVITIES = frozenset({"normal", "sensitive", "high"})
PORTABLE_TERMINAL_SOURCE = "portable_terminal"
PORTABLE_SPARK_STATUS = "staged"
_SUPPORTING_MEMORY_PREFERRED_TYPES = frozenset({
    "lesson",
    "constraint",
    "qa_result",
    "decision",
})
_SUPPORTING_MEMORY_TYPE_BOOST: dict[str, float] = {
    "lesson": 0.15,
    "constraint": 0.14,
    "qa_result": 0.13,
    "decision": 0.12,
    "preference": 0.10,
    "project_update": -0.08,
    "event": -0.10,
    "summary": -0.05,
}
HYGIENE_SHIPPED_LOOP_MARKERS = (
    "shipped",
    "done",
    "closed",
    "complete",
    "approved",
    "merged",
    "resolved",
)


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


def _ticket_linked_handoff(memory_id: int | None) -> dict[str, object] | None:
    if memory_id is None:
        return None
    conn = connect_db()
    try:
        row = _load_active_memory_item(conn, int(memory_id))
    finally:
        conn.close()
    if row is None:
        return {
            "memory_id": int(memory_id),
            "summary": "(memory not found)",
        }
    return {
        "memory_id": int(memory_id),
        "source": row["source"],
        "memory_type": row["memory_type"],
        "created_at": row["created_at"],
        "summary": _handoff_summary_line(str(row["content"])),
    }


def _tickets_by_linked_memory_ids(memory_ids: list[int]) -> dict[int, list[int]]:
    import memory_ticket_linkage

    return memory_ticket_linkage.batch_linked_ticket_ids(memory_ids)


def _handoff_next_action_line(content: str) -> str | None:
    """First useful line from a handoff Next Action section."""
    text = str(content or "").strip()
    if not text:
        return None
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("## next action"):
            in_section = True
            continue
        if in_section:
            if lower.startswith("##"):
                break
            if stripped.startswith("- "):
                value = stripped[2:].strip()
                return value or None
            if stripped:
                return stripped
    return None


def _agent_activity_summary(
    project_id: int | None,
    *,
    limit: int = 20,
) -> dict[str, object]:
    """Last contact per agent source from ingested handoffs."""
    rows = list_recent_agent_events(limit=limit, project_id=project_id)
    memory_ids = [int(row["id"]) for row in rows]
    linked_tickets = _tickets_by_linked_memory_ids(memory_ids)
    last_by_source: dict[str, dict[str, object]] = {}
    for row in rows:
        source = str(row["source"]).lower()
        if source in last_by_source:
            continue
        last_by_source[source] = {
            "source": source,
            "memory_id": int(row["id"]),
            "last_at": row["created_at"],
            "memory_type": row["memory_type"],
            "summary": _handoff_summary_line(str(row["content"])),
            "next_action": _handoff_next_action_line(str(row["content"])),
            "linked_ticket_ids": linked_tickets.get(int(row["id"]), []),
        }
    return {
        "last_by_source": last_by_source,
        "latest_contact": _latest_agent_contact(last_by_source),
        "recent": [
            {
                "id": int(row["id"]),
                "source": row["source"],
                "memory_type": row["memory_type"],
                "created_at": row["created_at"],
                "summary": _handoff_summary_line(str(row["content"])),
                "next_action": _handoff_next_action_line(str(row["content"])),
                "linked_ticket_ids": linked_tickets.get(int(row["id"]), []),
            }
            for row in rows
        ],
    }


def _latest_agent_contact(
    last_by_source: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    """Most recent agent contact across sources (for unscoped Agent Feed brief)."""
    latest: dict[str, object] | None = None
    latest_at = ""
    for source, entry in last_by_source.items():
        if not isinstance(entry, dict):
            continue
        at = str(entry.get("last_at") or "")
        if at > latest_at:
            latest_at = at
            latest = {**entry, "source": entry.get("source") or source}
    return latest


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
        ticket_note = ""
        linked = entry.get("linked_ticket_ids")
        if isinstance(linked, list) and linked:
            ticket_note = " [tickets: " + ", ".join(f"#{tid}" for tid in linked) + "]"
        lines.append(
            f"- Last {source}: {entry['last_at']} (memory #{entry['memory_id']}) — "
            f"{entry['summary']}{ticket_note}"
        )

    lines.append("Recent agent events (newest first):")
    for event in activity["recent"]:
        ticket_note = ""
        linked = event.get("linked_ticket_ids")
        if isinstance(linked, list) and linked:
            ticket_note = " [tickets: " + ", ".join(f"#{tid}" for tid in linked) + "]"
        lines.append(
            f"- [{event['created_at']}] {event['source']} | {event['memory_type']} — "
            f"{event['summary']}{ticket_note}"
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


from diagnostics import (  # noqa: E402
    format_diagnostics_prompt,
    gather_diagnostics_context,
    iter_diagnostics_tokens,
    run_diagnostics,
    _serialize_diagnostics_facts,
)

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


CONVERSATION_MODES = frozenset({
    "status",
    "planning",
    "exploration",
    "debug",
    "diagnostics",
    "bug",
    "casual",
})

_CONVERSATION_MODE_SHAPES: dict[str, str] = {
    "status": (
        "Brief bullets. Lead with filesystem truth, tickets, and Agent activity "
        "timestamps — never hybrid memory alone for agent timing. No preamble."
    ),
    "planning": (
        "Structured: context, options, tradeoffs, suggested next steps or "
        "ticket-ready slices."
    ),
    "exploration": (
        f"Think with {USER_NAME} — open, substantive, willing to go deep when the "
        "question warrants it."
    ),
    "debug": (
        "Methodical: what you know, hypotheses, what to check next. No guesses "
        "presented as fact."
    ),
    "diagnostics": (
        "Factual briefing tone — structured sections; say Unknown when data is "
        "missing."
    ),
    "bug": (
        "Reproduce steps, likely cause from evidence, concrete next fix or "
        "investigation step."
    ),
    "casual": (
        "Natural and warm — match the energy; stay useful without over-performing."
    ),
}


def classify_conversation_mode(*args, **kwargs):
    return conversation_runtime.classify_conversation_mode(sys.modules[__name__], *args, **kwargs)


def conversation_mode_answer_shape(*args, **kwargs):
    return conversation_runtime.conversation_mode_answer_shape(sys.modules[__name__], *args, **kwargs)


def _format_conversation_mode_prompt_section(*args, **kwargs):
    return conversation_runtime._format_conversation_mode_prompt_section(sys.modules[__name__], *args, **kwargs)


RESPONSE_DEPTHS = frozenset({"brief", "standard", "deep"})

_RESPONSE_DEPTH_EXPECTATIONS: dict[str, str] = {
    "brief": (
        "Short answer — bullets or a few tight sentences. No preamble or recap."
    ),
    "standard": (
        "Balanced length — enough detail to be useful without padding."
    ),
    "deep": (
        "Thorough when warranted — structured sections, reasoning, and options "
        "as needed."
    ),
}


def classify_response_depth(*args, **kwargs):
    return conversation_runtime.classify_response_depth(sys.modules[__name__], *args, **kwargs)


def response_depth_expectation(*args, **kwargs):
    return conversation_runtime.response_depth_expectation(sys.modules[__name__], *args, **kwargs)


def _format_response_depth_prompt_section(*args, **kwargs):
    return conversation_runtime._format_response_depth_prompt_section(sys.modules[__name__], *args, **kwargs)


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
        "constraint",
        f"Version claim conflict (known {CROWLEY_VERSION}): {snippet}",
        summary=f"User claim conflicts with authoritative release {CROWLEY_VERSION}",
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


def list_tasks(*args, **kwargs) -> list[sqlite3.Row]:
    return world_state.list_tasks(sys.modules[__name__], *args, **kwargs)



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


# --- concurrent ticketing (V3.9) — see tickets.py --------------------------------
from tickets import (  # noqa: E402
    TICKET_ASSIGNEES,
    TICKET_EVENT_TYPES,
    TICKET_OPEN_STATUSES,
    TICKET_SOURCES,
    TICKET_STATUSES,
    append_ticket_event,
    build_recent_changes_feed,
    build_tickets_summary,
    cancel_ticket,
    claim_ticket,
    complete_ticket,
    count_tickets,
    create_ticket,
    get_ticket_by_id,
    get_ticket_detail,
    group_tickets_by_parent,
    list_ticket_events,
    list_tickets,
    update_ticket,
    _format_tickets_prompt_section,
)


def _retrieval_ticket_seeds(
    summary: dict[str, object],
    agent: str | None = None,
    *,
    limit: int = 6,
) -> list[dict[str, object]]:
    """Open/in-flight tickets to scope hybrid retrieval (V3.9.9)."""
    seeds: list[dict[str, object]] = []
    seen: set[int] = set()

    def add(ticket: object) -> None:
        if not isinstance(ticket, dict):
            return
        raw_id = ticket.get("id")
        if raw_id is None:
            return
        ticket_id = int(raw_id)
        if ticket_id in seen:
            return
        seen.add(ticket_id)
        seeds.append(ticket)

    if agent:
        for ticket in summary.get("assigned_to_agent") or []:
            add(ticket)
    for ticket in summary.get("blocked") or []:
        add(ticket)
    open_rows = summary.get("open")
    if isinstance(open_rows, list):
        in_progress = [
            row
            for row in open_rows
            if isinstance(row, dict) and str(row.get("status")) == "in_progress"
        ]
        for ticket in sorted(
            in_progress,
            key=lambda row: (int(row.get("priority", 4)), int(row.get("id", 0))),
        ):
            add(ticket)
        if len(seeds) < limit:
            for ticket in sorted(
                [row for row in open_rows if isinstance(row, dict)],
                key=lambda row: (int(row.get("priority", 4)), int(row.get("id", 0))),
            ):
                add(ticket)
                if len(seeds) >= limit:
                    break
    return seeds[:limit]


def _parse_ticket_description(description: str) -> tuple[str, list[str]]:
    """Split ticket description body from Acceptance bullets (matches UI parser)."""
    text = str(description or "").strip()
    if not text:
        return "", []
    match = re.search(r"\n\s*Acceptance:\s*\n", text, flags=re.IGNORECASE)
    if not match:
        return text, []
    body = text[: match.start()].strip()
    acceptance: list[str] = []
    for line in text[match.end() :].splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            acceptance.append(stripped[2:].strip())
    return body, [item for item in acceptance if item]


def _initiative_keywords_for_ticket(ticket: dict[str, object]) -> list[str]:
    """Pull parent initiative title tokens when ticket belongs to a parent."""
    parent_id = ticket.get("parent_id")
    if parent_id is None:
        return []
    parent = get_ticket_by_id(int(parent_id))
    if parent is None:
        return []
    title = str(parent["title"] or "").strip()
    if not title:
        return []
    return [title]


def build_ticket_aware_retrieval_query(
    project_id: int | None,
    agent: str | None = None,
) -> tuple[str, list[dict[str, object]]]:
    """Build ticket-narrative retrieval query from current work (V3.9.10 #65)."""
    if project_id is None:
        return AGENT_SYNC_QUERY, []
    summary = build_tickets_summary(project_id, agent)
    seeds = _retrieval_ticket_seeds(summary, agent)
    if not seeds:
        return AGENT_SYNC_QUERY, []
    narrative_bits: list[str] = ["current work context"]
    for ticket in seeds:
        ticket_id = int(ticket["id"])
        title = str(ticket.get("title") or "").strip()
        status = str(ticket.get("status") or "open")
        description = str(ticket.get("description") or "")
        if not description:
            ticket_row = get_ticket_by_id(ticket_id)
            if ticket_row is not None:
                description = str(ticket_row["description"] or "")
        body, acceptance = _parse_ticket_description(description)
        narrative_bits.append(f"ticket #{ticket_id} [{status}] {title}")
        if body:
            narrative_bits.append(_truncate(body, 220))
        for criterion in acceptance[:6]:
            narrative_bits.append(criterion)
        for initiative in _initiative_keywords_for_ticket(ticket):
            narrative_bits.append(initiative)
    query = " ".join(bit for bit in narrative_bits if bit).strip()
    return query, seeds


def _recent_handoff_memory_ids(project_id: int | None, *, limit: int = 20) -> set[int]:
    """Handoff-timeline memory ids to dedupe from supporting retrieval."""
    activity = _agent_activity_summary(project_id, limit=limit)
    recent = activity.get("recent")
    if not isinstance(recent, list):
        return set()
    handoff_types = frozenset({"project_update", "summary", "event"})
    ids: set[int] = set()
    for event in recent:
        if not isinstance(event, dict) or event.get("id") is None:
            continue
        memory_type = str(event.get("memory_type") or "").lower()
        if memory_type in handoff_types:
            ids.add(int(event["id"]))
    return ids


def _supporting_memory_rank_key(item: dict[str, object]) -> tuple[float, int, str]:
    memory_type = str(item.get("memory_type") or "")
    boost = _SUPPORTING_MEMORY_TYPE_BOOST.get(memory_type, 0.0)
    ranked_score = float(item.get("score") or 0.0) + boost
    return (ranked_score, int(item.get("importance") or 0), str(item.get("created_at") or ""))


def _rank_supporting_memories(memories: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(memories, key=_supporting_memory_rank_key, reverse=True)


def retrieve_work_context_memories(*args, **kwargs) -> dict[str, object]:
    return world_state.retrieve_work_context_memories(sys.modules[__name__], *args, **kwargs)



def _task_frame_ticket_payload(ticket: dict[str, object]) -> dict[str, object]:
    """Ticket row with parsed description body and acceptance bullets."""
    description = str(ticket.get("description") or "")
    if not description and ticket.get("id") is not None:
        ticket_row = get_ticket_by_id(int(ticket["id"]))
        if ticket_row is not None:
            description = str(ticket_row["description"] or "")
    body, acceptance = _parse_ticket_description(description)
    payload: dict[str, object] = {
        "id": int(ticket["id"]),
        "title": str(ticket.get("title") or ""),
        "status": str(ticket.get("status") or "open"),
        "assignee": str(ticket.get("assignee") or ""),
        "priority": int(ticket.get("priority") or 4),
        "description": body,
        "acceptance": acceptance,
    }
    linked = ticket.get("linked_handoff")
    if isinstance(linked, dict):
        payload["linked_handoff"] = linked
    parent_id = ticket.get("parent_id")
    if parent_id is not None:
        payload["parent_id"] = int(parent_id)
    return payload


def build_task_frame_context(*args, **kwargs) -> dict[str, object]:
    return world_state.build_task_frame_context(sys.modules[__name__], *args, **kwargs)



def _cursor_in_progress_task_frame_tickets(
    task_frame: dict[str, object],
) -> list[dict[str, object]]:
    working_on = task_frame.get("working_on")
    if not isinstance(working_on, list):
        return []
    return [
        ticket
        for ticket in working_on
        if isinstance(ticket, dict) and str(ticket.get("status")) == "in_progress"
    ]


def _format_task_frame_prompt_section(project_id: int | None) -> str:
    """Compact Cursor task brief for operator chat prompts (V3.9.10 #68)."""
    if project_id is None:
        return ""
    frame = build_task_frame_context(project_id, "cursor")
    in_progress = _cursor_in_progress_task_frame_tickets(frame)
    if not in_progress:
        return ""

    lines = [
        "Task frame (current Cursor work — authoritative over hybrid retrieval for where-we-are):",
    ]
    for ticket in in_progress[:TASK_FRAME_WORKING_ON_CAP]:
        ticket_id = ticket.get("id")
        title = _truncate(str(ticket.get("title") or ""), 120)
        lines.append(f"- Ticket #{ticket_id} [in_progress]: {title}")
        acceptance = ticket.get("acceptance")
        if isinstance(acceptance, list):
            for item in acceptance[:4]:
                text = str(item).strip()
                if text:
                    lines.append(f"  - acceptance: {_truncate(text, 140)}")

    last_handoff = frame.get("last_handoff")
    if isinstance(last_handoff, dict):
        summary = str(last_handoff.get("summary") or "").strip()
        if summary:
            lines.append(f"- Last Cursor handoff: {_truncate(summary, 160)}")
        next_action = last_handoff.get("next_action")
        if isinstance(next_action, str) and next_action.strip():
            lines.append(
                f"- Next action from last handoff: {_truncate(next_action.strip(), 160)}"
            )

    return "\n".join(lines)


def _ticket_anchor_memories(
    project_id: int | None,
    tickets: list[dict[str, object]],
    *,
    per_ticket: int = 1,
) -> list[dict[str, object]]:
    """Pull at least one memory per in-flight ticket when content references it."""
    if project_id is None or not tickets:
        return []
    anchors: list[dict[str, object]] = []
    seen: set[int] = set()
    for ticket in tickets:
        status = str(ticket.get("status") or "")
        if status not in {"in_progress", "blocked"}:
            continue
        ticket_id = int(ticket["id"])
        title = str(ticket.get("title") or "").strip()
        ticket_row = get_ticket_by_id(ticket_id)
        if ticket_row is None:
            continue
        hits = retrieve_memories(
            f"ticket #{ticket_id} {title}",
            limit=12,
            project_id=project_id,
        )
        added = 0
        for hit in hits:
            memory_id = int(hit["id"])
            if memory_id in seen:
                continue
            conn = connect_db()
            try:
                row = _load_active_memory_item(conn, memory_id)
            finally:
                conn.close()
            if row is None or not _memory_relates_to_ticket(row, ticket_row):
                continue
            seen.add(memory_id)
            anchors.append(hit)
            added += 1
            if added >= per_ticket:
                break
    return anchors

# --- memory backend (V3.6 Phase 1) ------------------------------------------


def _memory_embed_provider() -> str:
    return memory_embeddings.memory_embed_provider(sys.modules[__name__])



def _try_load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    return memory_embeddings.try_load_sqlite_vec(sys.modules[__name__], conn)



def get_sqlite_vec_failure_reason() -> str | None:
    """Return the last sqlite-vec load failure reason, if any."""
    return memory_embeddings.get_sqlite_vec_failure_reason(sys.modules[__name__])



def _pack_embedding(vector: list[float]) -> bytes:
    return memory_embeddings.pack_embedding(vector)



def _vec_bind(vector: list[float]) -> bytes:
    """Packed float bytes for sqlite-vec INSERT and MATCH bindings."""
    return memory_embeddings.vec_bind(vector)



def _ensure_memory_vec_table(conn: sqlite3.Connection) -> bool:
    return memory_embeddings.ensure_memory_vec_table(sys.modules[__name__], conn)



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
    return memory_embeddings.get_local_embed_model(sys.modules[__name__])



def embed_text(text: str) -> list[float] | None:
    """Return an embedding vector for memory_items content, or None if unavailable."""
    return memory_embeddings.embed_text(sys.modules[__name__], text)



def index_memory_embedding(
    conn: sqlite3.Connection, memory_id: int, embedding: list[float], model_name: str
) -> None:
    return memory_embeddings.index_memory_embedding(
        sys.modules[__name__], conn, memory_id, embedding, model_name
    )



def backfill_memory_item_embeddings(conn: sqlite3.Connection, limit: int = 200) -> int:
    """Embed memory_items that lack an embedding. Returns count embedded."""
    return memory_embeddings.backfill_memory_item_embeddings(sys.modules[__name__], conn, limit)



def _ensure_memory_backend(conn: sqlite3.Connection) -> None:
    _ensure_memory_items_columns(conn)
    _ensure_consolidation_table(conn)
    migrate_memories_to_memory_items(conn)


def _lazy_backfill_embeddings(conn: sqlite3.Connection, *, limit: int = 50) -> None:
    """Optional embedding backfill — never required for startup or tests."""
    memory_embeddings.lazy_backfill_embeddings(sys.modules[__name__], conn, limit=limit)



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
    if "metadata_json" not in cols:
        conn.execute("ALTER TABLE memory_items ADD COLUMN metadata_json TEXT")
    try:
        import memory_ticket_linkage

        memory_ticket_linkage.ensure_linkage_column(conn)
    except Exception:
        pass


def _normalize_memory_dedupe_key(content: str) -> str:
    return _normalize_text(content).lower()


def _active_project_id(conn: sqlite3.Connection) -> int | None:
    return memory_store.active_project_id(conn)



def _resolve_memory_item_fields(
    legacy_type: str,
    importance: int,
    *,
    source: str | None,
    pinned: bool | None,
    confidence: float | None,
) -> tuple[str, str, bool, float]:
    return memory_store.resolve_memory_item_fields(
        sys.modules[__name__],
        legacy_type,
        importance,
        source=source,
        pinned=pinned,
        confidence=confidence,
    )



def _find_recent_duplicate_memory_item(
    conn: sqlite3.Connection,
    memory_type: str,
    content: str,
    project_id: int | None,
) -> int | None:
    return memory_store.find_recent_duplicate_memory_item(
        sys.modules[__name__], conn, memory_type, content, project_id
    )



MemoryGateOutcome = memory_store.MemoryGateOutcome



def _clamp_memory_importance(importance: int) -> int:
    return memory_store.clamp_memory_importance(importance)



def _clamp_memory_confidence(confidence: float) -> float:
    return memory_store.clamp_memory_confidence(confidence)



def _memory_gate_section_text(content: str, heading: str) -> str | None:
    return memory_store.memory_gate_section_text(sys.modules[__name__], content, heading)



def _parse_handoff_section_bullets(content: str, heading: str) -> list[str]:
    return memory_store.parse_handoff_section_bullets(content, heading)



def _extract_why_it_matters(content: str, summary: str | None = None) -> str | None:
    return memory_store.extract_why_it_matters(sys.modules[__name__], content, summary)



def _is_noisy_memory_content(content: str, *, memory_type: str) -> bool:
    return memory_store.is_noisy_memory_content(
        sys.modules[__name__], content, memory_type=memory_type
    )



def evaluate_memory_quality_gate(
    memory_type: str,
    content: str,
    *,
    summary: str | None = None,
    source: str = "implicit",
    importance: int = 3,
    confidence: float = 1.0,
    project_id: int | None = None,
) -> MemoryGateOutcome:
    """Return gate decision for a memory_items save (V3.9.9 quality gate)."""
    return memory_store.evaluate_memory_quality_gate(
        sys.modules[__name__],
        memory_type,
        content,
        summary=summary,
        source=source,
        importance=importance,
        confidence=confidence,
        project_id=project_id,
    )



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
    metadata: dict[str, object] | None = None,
    agent_id: str | None = None,
    write_action: str | None = None,
    conn: sqlite3.Connection | None = None,
    legacy_memory_id: int | None = None,
) -> int | None:
    """Insert into memory_items and attempt embedding/indexing."""
    return memory_store.save_memory_item(
        sys.modules[__name__],
        memory_type,
        content,
        summary=summary,
        source=source,
        project_id=project_id,
        message_id=message_id,
        decision_id=decision_id,
        importance=importance,
        confidence=confidence,
        pinned=pinned,
        status=status,
        metadata=metadata,
        agent_id=agent_id,
        write_action=write_action,
        conn=conn,
        legacy_memory_id=legacy_memory_id,
    )



def attach_memory_item_metadata(
    memory_item_id: int,
    metadata: dict[str, object],
    *,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Merge metadata onto an existing memory_items row."""
    return memory_store.attach_memory_item_metadata(
        sys.modules[__name__], memory_item_id, metadata, conn=conn
    )



# --- memory retrieval (V3.6 Phase 2) ----------------------------------------


def get_last_retrieval_mode() -> str:
    """Return mode used by the most recent retrieve_memories() call."""
    return memory_retrieval.get_last_retrieval_mode(sys.modules[__name__])



def _unpack_embedding(blob: bytes | None) -> list[float] | None:
    return memory_retrieval.unpack_embedding(blob)



def _cosine_similarity(a: list[float], b: list[float]) -> float:
    return memory_retrieval.cosine_similarity(a, b)



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


def _hygiene_loop_entry(
    row: sqlite3.Row,
    *,
    reason: str,
    category: str,
) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "description": str(row["description"]),
        "priority": int(row["priority"]),
        "status": str(row["status"]),
        "reason": reason,
        "category": category,
    }


def _hygiene_stale_open_loops(project_id: int) -> list[dict[str, object]]:
    """Open loops that likely match already-shipped work (read-only audit)."""
    done_ticket_ids = {
        int(row["id"])
        for row in list_tickets(
            project_id=project_id,
            status="done,cancelled",
            limit=200,
        )
    }
    candidates: list[dict[str, object]] = []
    for loop in list_open_loops(project_id, status="open", limit=100):
        description = str(loop["description"])
        lower = description.lower()
        reason: str | None = None
        if any(marker in lower for marker in HYGIENE_SHIPPED_LOOP_MARKERS):
            reason = "open loop mentions shipped or completed work"
        if reason is None:
            for match in re.finditer(r"#(\d+)", description):
                ticket_id = int(match.group(1))
                if ticket_id in done_ticket_ids:
                    reason = f"references closed ticket #{ticket_id}"
                    break
        if reason is not None:
            candidates.append(
                _hygiene_loop_entry(
                    loop,
                    reason=reason,
                    category="stale_loops",
                )
            )
    return candidates


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
        version_conflicts: list[dict[str, object]] = []
        stale_loops: list[dict[str, object]] = []

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

            if grounding_has_version_truth_conflict(str(row["content"])):
                version_conflicts.append(
                    _hygiene_reason_entry(
                        row,
                        reason="version claim conflicts with authoritative release",
                        category="version_conflicts",
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

        project = get_active_project()
        if project is not None:
            stale_loops = _hygiene_stale_open_loops(int(project["id"]))

        return {
            "generated_at": _now_iso(),
            "dry_run": True,
            "stale": stale,
            "noisy": noisy,
            "duplicates": duplicates,
            "possible_conflicts": possible_conflicts,
            "version_conflicts": version_conflicts,
            "stale_loops": stale_loops,
            "counts": {
                "stale": len(stale),
                "noisy": len(noisy),
                "duplicates": len(duplicates),
                "possible_conflicts": len(possible_conflicts),
                "version_conflicts": len(version_conflicts),
                "stale_loops": len(stale_loops),
                "total": (
                    len(stale)
                    + len(noisy)
                    + len(duplicates)
                    + len(possible_conflicts)
                    + len(version_conflicts)
                    + len(stale_loops)
                ),
            },
        }
    finally:
        conn.close()


def memory_hygiene_report_api() -> dict[str, object]:
    """Read-only API payload for memory hygiene report."""
    return memory_hygiene_report()


def _parse_memory_timestamp(value: str) -> datetime | None:
    return memory_retrieval.parse_memory_timestamp(value)



def _recency_score(created_at: str) -> float:
    return memory_retrieval.recency_score(sys.modules[__name__], created_at)



def _importance_score(importance: int) -> float:
    return memory_retrieval.importance_score(importance)



def _project_match_score(item_project_id: int | None, active_project_id: int | None) -> float:
    return memory_retrieval.project_match_score(item_project_id, active_project_id)



def _infer_query_memory_types(query: str) -> set[str]:
    return memory_retrieval.infer_query_memory_types(query)



def _type_match_score(memory_type: str, inferred_types: set[str]) -> float:
    return memory_retrieval.type_match_score(memory_type, inferred_types)



def _keyword_score_for_item(
    tokens: list[str], content: str, summary: str | None
) -> float:
    return memory_retrieval.keyword_score_for_item(tokens, content, summary)



def _memory_display_text(row: sqlite3.Row) -> str:
    summary = row["summary"]
    if summary:
        return str(summary)
    return str(row["content"])


def _semantic_candidate_scores(
    conn: sqlite3.Connection, query_embedding: list[float] | None, limit: int
) -> dict[int, float]:
    return memory_retrieval.semantic_candidate_scores(
        sys.modules[__name__], conn, query_embedding, limit
    )



def _keyword_candidate_scores(
    conn: sqlite3.Connection, query: str, limit: int
) -> dict[int, float]:
    return memory_retrieval.keyword_candidate_scores(sys.modules[__name__], conn, query, limit)



def _load_active_memory_item(conn: sqlite3.Connection, memory_id: int) -> sqlite3.Row | None:
    return memory_retrieval.load_active_memory_item(conn, memory_id)



def _is_canon_memory_row(row: sqlite3.Row) -> bool:
    return memory_retrieval.is_canon_memory_row(row)



def _memory_provenance_ids(row: sqlite3.Row) -> dict[str, int | None]:
    return memory_retrieval.memory_provenance_ids(row)



def _available_provenance_ids(provenance: dict[str, int | None]) -> dict[str, int]:
    return memory_retrieval.available_provenance_ids(provenance)



_MEMORY_TYPE_INCLUSION_LABELS = {
    "constraint": "constraint memory",
    "decision": "decision memory",
    "preference": "preference memory",
    "lesson": "lesson memory",
    "qa_result": "QA memory",
    "project_update": "project update memory",
    "summary": "summary memory",
    "event": "event memory",
    "bug": "bug memory",
}


def _extract_ticket_refs_from_query(query: str) -> set[int]:
    return memory_retrieval.extract_ticket_refs_from_query(query)



def _query_relates_to_ticket(query: str, ticket_row: sqlite3.Row) -> bool:
    return memory_retrieval.query_relates_to_ticket(sys.modules[__name__], query, ticket_row)



def _memory_relates_to_ticket(row: sqlite3.Row, ticket_row: sqlite3.Row) -> bool:
    """True when memory content references a ticket (not just the retrieval query)."""
    return memory_retrieval.memory_relates_to_ticket(sys.modules[__name__], row, ticket_row)



def _build_inclusion_reason(
    row: sqlite3.Row,
    *,
    query: str,
    score_breakdown: dict[str, float],
    linked_ticket_ids: list[int],
    open_tickets_by_id: dict[int, sqlite3.Row],
) -> str:
    """Human-readable reason this memory was included in retrieval (V3.9.9)."""
    return memory_retrieval.build_inclusion_reason(
        sys.modules[__name__],
        row,
        query=query,
        score_breakdown=score_breakdown,
        linked_ticket_ids=linked_ticket_ids,
        open_tickets_by_id=open_tickets_by_id,
    )



def _build_retrieval_explanation(
    row: sqlite3.Row,
    *,
    score: float,
    score_breakdown: dict[str, float],
    retrieval_mode: str,
    query: str = "",
    linked_ticket_ids: list[int] | None = None,
    open_tickets_by_id: dict[int, sqlite3.Row] | None = None,
) -> dict[str, object]:
    return memory_retrieval.build_retrieval_explanation(
        sys.modules[__name__],
        row,
        score=score,
        score_breakdown=score_breakdown,
        retrieval_mode=retrieval_mode,
        query=query,
        linked_ticket_ids=linked_ticket_ids,
        open_tickets_by_id=open_tickets_by_id,
    )



def _memory_item_attribution(row: sqlite3.Row) -> dict[str, object] | None:
    return memory_store.memory_item_attribution(sys.modules[__name__], row)




def _score_memory_item(
    row: sqlite3.Row,
    *,
    semantic: float,
    keyword: float,
    active_project_id: int | None,
    inferred_types: set[str],
) -> tuple[float, dict[str, float]]:
    return memory_retrieval.score_memory_item(
        sys.modules[__name__],
        row,
        semantic=semantic,
        keyword=keyword,
        active_project_id=active_project_id,
        inferred_types=inferred_types,
    )



def retrieve_memories(
    query: str,
    limit: int = MEMORY_LIMIT,
    project_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, object]]:
    """Hybrid retrieval over memory_items."""
    return memory_retrieval.retrieve_memories(
        sys.modules[__name__], query, limit, project_id=project_id, conn=conn
    )



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


def _state_payload_for_api(*args, **kwargs) -> dict[str, object] | None:
    return world_state._state_payload_for_api(sys.modules[__name__], *args, **kwargs)



_PHASE_PROGRESS_RE = re.compile(
    r"(?:phase\s*)?(\d+)\s*(?:of|/)\s*(\d+)",
    re.IGNORECASE,
)


def parse_phase_progress(*args, **kwargs) -> dict[str, object] | None:
    return world_state.parse_phase_progress(sys.modules[__name__], *args, **kwargs)



def _memory_item_layer(row: sqlite3.Row) -> str:
    return memory_store.memory_item_layer(sys.modules[__name__], row)



def _memory_item_api_dict(row: sqlite3.Row) -> dict[str, object]:
    return memory_store.memory_item_api_dict(sys.modules[__name__], row)



def _memory_counts_payload(*args, **kwargs) -> dict[str, object]:
    return world_state._memory_counts_payload(sys.modules[__name__], *args, **kwargs)



def _canon_api_items(*args, **kwargs) -> list[dict[str, object]]:
    return world_state._canon_api_items(sys.modules[__name__], *args, **kwargs)



def _agent_sync_memory_limit(limit: int) -> int:
    import agent_sync_envelope

    caps = agent_sync_envelope.section_caps(limit)
    return caps["memories"]


def _list_constraint_memories(*args, **kwargs) -> list[dict[str, object]]:
    return world_state._list_constraint_memories(sys.modules[__name__], *args, **kwargs)



def _agent_sync_event_dict(*args, **kwargs) -> dict[str, object]:
    return world_state._agent_sync_event_dict(sys.modules[__name__], *args, **kwargs)



def _format_canon_prompt_section(*args, **kwargs) -> str:
    return world_state._format_canon_prompt_section(sys.modules[__name__], *args, **kwargs)



def build_world_dashboard(*args, **kwargs) -> dict[str, object]:
    return world_state.build_world_dashboard(sys.modules[__name__], *args, **kwargs)



def update_task_status(*args, **kwargs) -> bool:
    return world_state.update_task_status(sys.modules[__name__], *args, **kwargs)



def record_system_metric(*args, **kwargs) -> None:
    return world_state.record_system_metric(sys.modules[__name__], *args, **kwargs)



def record_activity_pulse(*args, **kwargs) -> dict[str, object] | None:
    return world_state.record_activity_pulse(sys.modules[__name__], *args, **kwargs)



def list_activity_pulses(*args, **kwargs) -> list[dict[str, object]]:
    return world_state.list_activity_pulses(sys.modules[__name__], *args, **kwargs)



def _parse_iso_datetime(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _activity_wire_agent_label(agent: str) -> str:
    labels = {
        "cursor": "Cursor",
        "codex": "Codex",
        "crowley": "Crowley",
        USER_ACTOR_SLUG: USER_NAME,
    }
    return labels.get(str(agent).lower(), str(agent).title())


def _activity_wire_line(
    agent: str,
    verb: str,
    *,
    ticket_id: int | None = None,
    summary: str | None = None,
    ticket_title: str | None = None,
) -> str:
    """Narrative copy for live-wire rows (V3.9.11 #72)."""
    who = _activity_wire_agent_label(agent)
    verb_norm = str(verb).strip().lower()
    ticket_ref = f"ticket #{ticket_id}" if ticket_id is not None else None
    title_bit = f" — {_truncate(str(ticket_title), 80)}" if ticket_title else ""
    summary_text = str(summary).strip() if summary else ""

    if verb_norm == "session_start":
        return f"{who} opened a session"
    if verb_norm == "claimed" and ticket_ref:
        return f"{who} claimed {ticket_ref}{title_bit}"
    if verb_norm == "working" and ticket_ref:
        return f"{who} is on {ticket_ref}{title_bit}"
    if verb_norm == "note":
        return summary_text or f"{who} posted a note"
    if verb_norm == "handoff":
        if summary_text:
            return f"{who} handed off — {_truncate(summary_text, 140)}"
        return f"{who} handed off"
    if verb_norm == "minted":
        return summary_text or f"{who} minted tickets"
    if verb_norm == "closed" and ticket_ref:
        return f"{who} closed {ticket_ref}{title_bit}"
    if summary_text:
        return _truncate(summary_text, 160)
    if ticket_ref:
        return f"{who} — {ticket_ref}{title_bit}"
    return f"{who} — {verb_norm.replace('_', ' ')}"


def _ticket_event_wire_verb(event_type: str, payload: dict[str, object]) -> str:
    normalized = str(event_type or "event")
    if normalized == "claimed":
        return "claimed"
    if normalized == "created":
        return "minted"
    if normalized == "cancelled":
        return "closed"
    if normalized == "status_change":
        to_status = str(payload.get("to", "")).lower()
        if to_status == "done":
            return "closed"
        if to_status in {"in_progress", "claimed"}:
            return "claimed"
        return "working"
    if normalized == "handoff_linked":
        return "handoff"
    return "working"


def _pulse_to_wire_item(pulse: dict[str, object]) -> dict[str, object]:
    ticket_id = pulse.get("ticket_id")
    ticket_title = None
    if ticket_id is not None:
        row = get_ticket_by_id(int(ticket_id))
        if row is not None:
            ticket_title = str(row["title"])
    return {
        "id": f"pulse:{pulse['id']}",
        "kind": "pulse",
        "agent": str(pulse["agent"]),
        "verb": str(pulse["verb"]),
        "ticket_id": int(ticket_id) if ticket_id is not None else None,
        "line": _activity_wire_line(
            str(pulse["agent"]),
            str(pulse["verb"]),
            ticket_id=int(ticket_id) if ticket_id is not None else None,
            summary=str(pulse["summary"]) if pulse.get("summary") else None,
            ticket_title=ticket_title,
        ),
        "created_at": str(pulse["created_at"]),
        "is_ambient": False,
    }


def _changes_item_to_wire_item(item: dict[str, object]) -> dict[str, object]:
    kind = str(item.get("kind") or "event")
    if kind == "handoff":
        agent = str(item.get("source") or "crowley")
        linked = item.get("linked_ticket_ids")
        ticket_id = int(linked[0]) if isinstance(linked, list) and linked else None
        return {
            "id": str(item.get("id") or f"handoff:{item.get('created_at')}"),
            "kind": "handoff",
            "agent": agent,
            "verb": "handoff",
            "ticket_id": ticket_id,
            "line": _activity_wire_line(
                agent,
                "handoff",
                ticket_id=ticket_id,
                summary=str(item.get("summary") or ""),
            ),
            "created_at": str(item.get("created_at") or ""),
            "is_ambient": False,
        }

    payload: dict[str, object] = {}
    event_type = str(item.get("event_type") or "event")
    ticket_id = int(item["ticket_id"]) if item.get("ticket_id") is not None else None
    verb = _ticket_event_wire_verb(event_type, payload)
    agent = str(item.get("source") or "system")
    summary = str(item.get("summary") or "")
    return {
        "id": str(item.get("id") or f"ticket_event:{ticket_id}"),
        "kind": "ticket",
        "agent": agent,
        "verb": verb,
        "ticket_id": ticket_id,
        "line": summary or _activity_wire_line(
            agent,
            verb,
            ticket_id=ticket_id,
            ticket_title=str(item.get("ticket_title") or ""),
        ),
        "created_at": str(item.get("created_at") or ""),
        "is_ambient": False,
    }


def _dedupe_activity_wire_items(
    items: list[dict[str, object]],
    *,
    window_minutes: int = ACTIVITY_WIRE_DEDUPE_MINUTES,
) -> list[dict[str, object]]:
    """Drop same agent/verb/ticket rows inside the dedupe window (newest wins)."""
    kept: list[dict[str, object]] = []
    clusters: list[tuple[tuple[object, ...], datetime]] = []
    window = timedelta(minutes=max(1, int(window_minutes)))
    for item in items:
        if bool(item.get("is_ambient")):
            kept.append(item)
            continue
        key = (
            str(item.get("agent") or ""),
            str(item.get("verb") or ""),
            item.get("ticket_id"),
        )
        try:
            created = _parse_iso_datetime(str(item.get("created_at") or ""))
        except ValueError:
            kept.append(item)
            continue
        duplicate = False
        for seen_key, seen_at in clusters:
            if seen_key != key:
                continue
            if abs(created - seen_at) <= window:
                duplicate = True
                break
        if duplicate:
            continue
        clusters.append((key, created))
        kept.append(item)
    return kept


def _ambient_activity_wire_items(project_id: int) -> list[dict[str, object]]:
    """Fallback rows when the live feed is empty or stale (V3.9.11 #72)."""
    now = datetime.now(timezone.utc)
    now_iso = _now_iso()
    items: list[dict[str, object]] = []

    for row in list_tickets(
        project_id=project_id,
        status="in_progress",
        limit=5,
    ):
        ticket_id = int(row["id"])
        assignee = str(row["assignee"])
        items.append(
            {
                "id": f"ambient:ticket:{ticket_id}",
                "kind": "ambient",
                "agent": assignee,
                "verb": "working",
                "ticket_id": ticket_id,
                "line": _activity_wire_line(
                    assignee,
                    "working",
                    ticket_id=ticket_id,
                    ticket_title=str(row["title"]),
                ),
                "created_at": now_iso,
                "is_ambient": True,
            }
        )

    activity = _agent_activity_summary(project_id, limit=10)
    last_by_source = activity.get("last_by_source")
    if isinstance(last_by_source, dict):
        for source in ("cursor", "codex"):
            entry = last_by_source.get(source)
            if not isinstance(entry, dict):
                items.append(
                    {
                        "id": f"ambient:agent:{source}:missing",
                        "kind": "ambient",
                        "agent": source,
                        "verb": "session_start",
                        "ticket_id": None,
                        "line": f"No recent { _activity_wire_agent_label(source) } handoff on record",
                        "created_at": now_iso,
                        "is_ambient": True,
                    }
                )
                continue
            try:
                last_at = _parse_iso_datetime(str(entry.get("last_at") or ""))
            except ValueError:
                continue
            age = now - last_at.astimezone(timezone.utc)
            if age > timedelta(hours=ACTIVITY_WIRE_AGENT_STALE_HOURS):
                hours = int(age.total_seconds() // 3600)
                items.append(
                    {
                        "id": f"ambient:agent:{source}:stale",
                        "kind": "ambient",
                        "agent": source,
                        "verb": "note",
                        "ticket_id": None,
                        "line": (
                            f"{_activity_wire_agent_label(source)} last heard "
                            f"{hours}h ago"
                        ),
                        "created_at": now_iso,
                        "is_ambient": True,
                    }
                )

    state = get_project_state(project_id)
    if state is not None and state["focus"]:
        focus = _truncate(str(state["focus"]), 140)
        items.append(
            {
                "id": "ambient:focus",
                "kind": "ambient",
                "agent": "crowley",
                "verb": "note",
                "ticket_id": None,
                "line": f"Focus — {focus}",
                "created_at": now_iso,
                "is_ambient": True,
            }
        )
    return items


def _wire_needs_ambient(real_items: list[dict[str, object]]) -> bool:
    if len(real_items) < ACTIVITY_WIRE_AMBIENT_MIN_REAL:
        return True
    try:
        newest = _parse_iso_datetime(str(real_items[0].get("created_at") or ""))
    except ValueError:
        return True
    age = datetime.now(timezone.utc) - newest.astimezone(timezone.utc)
    return age > timedelta(minutes=ACTIVITY_WIRE_STALE_MINUTES)


def build_activity_wire(*args, **kwargs) -> dict[str, object]:
    return world_state.build_activity_wire(sys.modules[__name__], *args, **kwargs)



def _slim_activity_wire_for_agent(
    wire: dict[str, object],
    requester_agent: str,
    *,
    limit: int = ACTIVITY_WIRE_SYNC_CAP,
) -> dict[str, object]:
    """Slim wire for agent sync — other-agent motion first (V3.9.11 #73)."""
    cap = max(1, min(int(limit), ACTIVITY_WIRE_SYNC_CAP))
    items_raw = wire.get("items")
    items = items_raw if isinstance(items_raw, list) else []
    requester = requester_agent.strip().lower()
    other: list[dict[str, object]] = []
    own: list[dict[str, object]] = []
    ambient: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("is_ambient"):
            ambient.append(item)
        elif str(item.get("agent") or "").lower() == requester:
            own.append(item)
        else:
            other.append(item)
    slim_items = (other + own + ambient)[:cap]
    active_raw = wire.get("active_agents")
    active_agents = active_raw if isinstance(active_raw, list) else []
    return {
        "pinned_focus": wire.get("pinned_focus"),
        "active_agents": active_agents,
        "items": slim_items,
        "cap": cap,
    }


def get_metrics_summary_24h(*args, **kwargs) -> dict[str, object]:
    return world_state.get_metrics_summary_24h(sys.modules[__name__], *args, **kwargs)



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
        "runtime": build_runtime_diagnostics(),
    }


def build_context_bundle(*args, **kwargs) -> dict[str, object]:
    return world_state.build_context_bundle(sys.modules[__name__], *args, **kwargs)



def retrieve_memories_api(
    q: str,
    limit: int = MEMORY_LIMIT,
    *,
    depth: str | None = None,
    debug: bool = False,
) -> dict[str, object]:
    """Read-only hybrid memory search for external agents (V3.7 memory bus)."""
    import context_resolution
    import memory_quality

    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    resolved_depth = context_resolution.normalize_depth(depth)
    fetch_limit = max(limit * 3, 16) if resolved_depth else limit
    results = retrieve_memories(q, limit=fetch_limit, project_id=project_id)
    trace: dict[str, object] = {}
    if resolved_depth is not None:
        tickets_summary = build_tickets_summary(project_id)
        open_tickets = tickets_summary.get("open")
        candidate_tickets = (
            [dict(item) for item in open_tickets]
            if isinstance(open_tickets, list)
            else []
        )
        resolved, matched_tickets, trace = context_resolution.cross_source_resolve(
            [dict(item) for item in results],
            matched_tickets=candidate_tickets,
            query=q,
            depth=resolved_depth,
            debug=debug,
        )
        results = resolved[:limit]
        conn = connect_db()
        try:
            active_spark_count = context_resolution.count_active_sparks(
                conn,
                project_id=project_id,
            )
        finally:
            conn.close()
        trace = context_resolution.apply_memory_fallback_trace(
            trace,
            active_spark_count=active_spark_count,
            fallback_used=active_spark_count
            < context_resolution.COLD_START_ACTIVE_SPARK_THRESHOLD,
        )
        payload = {
            "query": q,
            "limit": limit,
            "depth": resolved_depth,
            "retrieval_mode": get_last_retrieval_mode(),
            "results": results,
            "hits": results,
            "matched_tickets": matched_tickets,
            "trace": trace,
        }
        return memory_quality.annotate_retrieval_payload(payload)
    payload = {
        "query": q,
        "limit": limit,
        "retrieval_mode": get_last_retrieval_mode(),
        "results": results,
        "hits": results,
    }
    return memory_quality.annotate_retrieval_payload(payload)


def build_retrieval_explainability_api(
    q: str,
    *,
    limit: int = MEMORY_LIMIT,
) -> dict[str, object]:
    """Structured explainability without chain-of-thought (V3.9.17 #119)."""
    import memory_tiers

    payload = retrieve_memories_api(q, limit=limit)
    results = payload.get("results")
    signals: list[dict[str, object]] = []
    if isinstance(results, list):
        for entry in results:
            if not isinstance(entry, dict):
                continue
            explanation = entry.get("explanation")
            exp = explanation if isinstance(explanation, dict) else {}
            tier = entry.get("memory_tier")
            if not tier:
                tier = memory_tiers.normalize_tier(str(exp.get("memory_tier", "working")))
            signals.append(
                {
                    "memory_id": entry.get("id"),
                    "memory_type": entry.get("memory_type") or exp.get("memory_type"),
                    "memory_tier": tier,
                    "score": exp.get("score"),
                    "inclusion_reason": exp.get("inclusion_reason"),
                    "attribution": exp.get("attribution"),
                    "provenance": exp.get("provenance"),
                }
            )
    return {
        "query": q,
        "limit": limit,
        "retrieval_mode": payload.get("retrieval_mode"),
        "signals": signals,
    }


def build_session_diff(
    since: str | None = None,
    *,
    project_id: int | None = None,
) -> dict[str, object]:
    """What changed since last session (V3.9.17 #120)."""
    conn = connect_db()
    try:
        if project_id is None:
            project_id = _active_project_id(conn)
        since_ts = since.strip() if since and since.strip() else None
        if since_ts is None:
            row = conn.execute(
                "SELECT datetime('now', '-24 hours') AS ts"
            ).fetchone()
            since_ts = str(row["ts"])

        ticket_rows = conn.execute(
            """
            SELECT * FROM tickets
            WHERE datetime(updated_at) >= datetime(?)
            ORDER BY datetime(updated_at) DESC
            LIMIT 50
            """,
            (since_ts,),
        ).fetchall()
        memory_rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE datetime(updated_at) >= datetime(?)
            ORDER BY datetime(updated_at) DESC
            LIMIT 50
            """,
            (since_ts,),
        ).fetchall()
        decision_rows = conn.execute(
            """
            SELECT * FROM decisions
            WHERE datetime(timestamp) >= datetime(?)
            ORDER BY datetime(timestamp) DESC
            LIMIT 20
            """,
            (since_ts,),
        ).fetchall()
    finally:
        conn.close()

    import tickets as tickets_mod

    return {
        "since": since_ts,
        "project_id": project_id,
        "tickets": [tickets_mod._ticket_row_to_dict(row) for row in ticket_rows],
        "memory": [_memory_item_api_dict(row) for row in memory_rows],
        "decisions": [row_to_dict(row) for row in decision_rows],
        "counts": {
            "tickets": len(ticket_rows),
            "memory": len(memory_rows),
            "decisions": len(decision_rows),
        },
    }


def build_simple_mode_payload(*, project_id: int | None = None) -> dict[str, object]:
    """Reduced surface for onboarding (V3.9.17 #122)."""
    project = get_active_project()
    if project_id is None and project is not None:
        project_id = int(project["id"])
    summary = build_tickets_summary(project_id)
    open_tasks = [row_to_dict(row) for row in list_tasks(status="open")[:10]]
    counts = count_memory_items_by_status()
    return {
        "mode": "simple",
        "project": row_to_dict(project) if project is not None else None,
        "tickets_open": summary.get("open", []),
        "tasks": open_tasks,
        "memory_active_count": int(counts.get("active", 0)),
        "hidden_surfaces": [
            "decisions",
            "lineage",
            "audit_log",
            "conflicts",
            "agent_internals",
        ],
    }


def run_memory_garbage_collection(*, dry_run: bool = False) -> dict[str, object]:
    """Duplicate prune + tier decay (V3.9.17 #121)."""
    import memory_tiers

    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    decay_result = memory_tiers.run_memory_decay(project_id=project_id, dry_run=dry_run)
    duplicates_pruned = 0
    conn = connect_db()
    try:
        params: list[object] = []
        where = "status = 'active'"
        if project_id is not None:
            where += " AND project_id = ?"
            params.append(project_id)
        rows = conn.execute(
            f"SELECT * FROM memory_items WHERE {where} ORDER BY datetime(created_at) DESC",
            params,
        ).fetchall()
        seen: dict[str, int] = {}
        now = _now_iso()
        for row in rows:
            key = _normalize_dedupe_key(str(row["content"]))
            if not key or len(key) < 12:
                continue
            if key in seen:
                duplicates_pruned += 1
                if not dry_run:
                    conn.execute(
                        "UPDATE memory_items SET status = 'stale', updated_at = ? WHERE id = ?",
                        (now, int(row["id"])),
                    )
            else:
                seen[key] = int(row["id"])
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return {
        **decay_result,
        "duplicates_pruned": duplicates_pruned,
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


def portable_writeback_contract() -> dict[str, object]:
    """Structured writeback shape for portable terminal sessions (V3.9.12 #76)."""
    return {
        "format": "crowley_terminal_writeback_v1",
        "description": (
            "End the external session with a fenced JSON block matching this shape. "
            "Crowley imports it locally — raw chat transcripts are not saved by default."
        ),
        "required_top_level": ["session"],
        "session_fields": ["summary", "surface", "model"],
        "spark_fields": ["content", "lane", "why_keep", "confidence", "sensitivity"],
        "allowed_lanes": list(PORTABLE_WRITEBACK_LANES),
        "allowed_sensitivities": sorted(PORTABLE_WRITEBACK_SENSITIVITIES),
        "optional_arrays": [
            "sparks",
            "decisions",
            "lessons",
            "open_loops",
            "corrections",
            "context_pull_candidates",
            "do_not_save",
        ],
        "example": {
            "session": {
                "summary": "Discussed V3.9.12 packet export scope with D.",
                "surface": "chatgpt",
                "model": "gpt-4.1",
            },
            "sparks": [
                {
                    "content": "D wants paste-ready packets under 12k chars.",
                    "lane": "work",
                    "why_keep": "Shapes portable terminal size discipline.",
                    "confidence": 0.85,
                    "sensitivity": "normal",
                }
            ],
            "context_pull_candidates": [
                "Latest Codex architect handoff on V3.9.12",
            ],
            "do_not_save": ["full chat transcript"],
        },
    }


def _portable_clip(text: object, limit: int = 240) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _portable_memory_rows(
    memories: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in memories[:PORTABLE_PACKET_MEMORY_CAP]:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        content = str(item.get("content") or "").strip()
        body = summary or content
        rows.append(
            {
                "id": item.get("id"),
                "memory_type": item.get("memory_type"),
                "source": item.get("source"),
                "text": _portable_clip(body, 220),
                "inclusion_reason": _portable_clip(item.get("inclusion_reason"), 160),
            }
        )
    return rows


def build_portable_context_packet(*args, **kwargs) -> dict[str, object]:
    return portable_context.build_portable_context_packet(sys.modules[__name__], *args, **kwargs)



def render_portable_context_packet_markdown(*args, **kwargs) -> str:
    return portable_context.render_portable_context_packet_markdown(sys.modules[__name__], *args, **kwargs)



@dataclass
class TerminalWritebackParseResult:
    """Validation outcome for portable terminal writeback (#77)."""

    ok: bool
    errors: list[str]
    writeback: dict[str, object] | None = None


def extract_terminal_writeback_json(raw: str) -> dict[str, object]:
    """Parse JSON from raw text or a markdown fenced code block."""
    text = raw.strip()
    if not text:
        raise ValueError("writeback text is empty")
    if text.startswith("{"):
        payload = json.loads(text)
    else:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        if not match:
            raise ValueError("no JSON object or fenced ```json block found")
        payload = json.loads(match.group(1).strip())
    if not isinstance(payload, dict):
        raise ValueError("writeback payload must be a JSON object")
    return payload


def _writeback_string_items(
    value: object,
    field: str,
    errors: list[str],
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    items: list[str] = []
    for index, entry in enumerate(value):
        if isinstance(entry, str):
            cleaned = entry.strip()
        elif isinstance(entry, dict):
            cleaned = str(
                entry.get("summary") or entry.get("content") or entry.get("text") or ""
            ).strip()
        else:
            cleaned = str(entry).strip()
        if not cleaned:
            errors.append(f"{field}[{index}] must be a non-empty string")
            continue
        items.append(cleaned)
    return items


def _normalize_terminal_spark(
    raw: object,
    index: int,
    errors: list[str],
) -> dict[str, object] | None:
    spark_errors: list[str] = []
    if not isinstance(raw, dict):
        errors.append(f"sparks[{index}] must be an object")
        return None
    content = str(raw.get("content") or "").strip()
    lane = str(raw.get("lane") or "").strip().lower()
    why_keep = str(raw.get("why_keep") or "").strip()
    sensitivity = str(raw.get("sensitivity") or "").strip().lower()
    confidence_raw = raw.get("confidence")

    if not content:
        spark_errors.append(f"sparks[{index}].content is required")
    if not lane:
        spark_errors.append(f"sparks[{index}].lane is required")
    elif lane not in PORTABLE_WRITEBACK_LANES:
        spark_errors.append(
            f"sparks[{index}].lane must be one of: {', '.join(PORTABLE_WRITEBACK_LANES)}"
        )
    if not why_keep:
        spark_errors.append(f"sparks[{index}].why_keep is required")
    if not sensitivity:
        spark_errors.append(f"sparks[{index}].sensitivity is required")
    elif sensitivity not in PORTABLE_WRITEBACK_SENSITIVITIES:
        spark_errors.append(
            f"sparks[{index}].sensitivity must be one of: "
            + ", ".join(sorted(PORTABLE_WRITEBACK_SENSITIVITIES))
        )
    confidence: float | None = None
    if confidence_raw is None or confidence_raw == "":
        spark_errors.append(f"sparks[{index}].confidence is required")
    else:
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            spark_errors.append(f"sparks[{index}].confidence must be a number")
        else:
            if confidence < 0.0 or confidence > 1.0:
                spark_errors.append(
                    f"sparks[{index}].confidence must be between 0 and 1"
                )

    if spark_errors:
        errors.extend(spark_errors)
        return None

    return {
        "content": content,
        "lane": lane,
        "why_keep": why_keep,
        "worth_reason": str(raw.get("worth_reason") or why_keep).strip(),
        "confidence": confidence if confidence is not None else 0.0,
        "sensitivity": sensitivity,
    }


def parse_terminal_writeback(*args, **kwargs) -> TerminalWritebackParseResult:
    return portable_context.parse_terminal_writeback(sys.modules[__name__], *args, **kwargs)



def _memory_item_metadata(row: sqlite3.Row) -> dict[str, object]:
    return memory_store.memory_item_metadata(row)



def _portable_session_receipt_metadata(
    writeback: dict[str, object],
) -> dict[str, object]:
    session = writeback.get("session")
    assert isinstance(session, dict)
    return {
        "writeback_format": writeback.get("format"),
        "surface": session.get("surface"),
        "model": session.get("model"),
        "provider": session.get("provider"),
        "decisions": writeback.get("decisions") or [],
        "lessons": writeback.get("lessons") or [],
        "open_loops": writeback.get("open_loops") or [],
        "corrections": writeback.get("corrections") or [],
        "context_pull_candidates": writeback.get("context_pull_candidates") or [],
        "spark_count": len(writeback.get("sparks") or []),
    }


def _portable_spark_metadata(
    spark: dict[str, object],
    *,
    session: dict[str, object],
    session_receipt_id: int | None,
) -> dict[str, object]:
    return {
        "candidate": True,
        "lane": spark.get("lane"),
        "why_keep": spark.get("why_keep"),
        "worth_reason": spark.get("why_keep"),
        "sensitivity": spark.get("sensitivity"),
        "surface": session.get("surface"),
        "model": session.get("model"),
        "provider": session.get("provider"),
        "session_receipt_id": session_receipt_id,
        "writeback_format": PORTABLE_WRITEBACK_FORMAT,
    }


def ingest_terminal_writeback(*args, **kwargs) -> dict[str, object]:
    return portable_context.ingest_terminal_writeback(sys.modules[__name__], *args, **kwargs)



WRITEBACK_ACCEPTANCE_CRITERIA: list[dict[str, str]] = [
    {
        "id": "chatgpt_surface",
        "description": "Session surface is chatgpt or chatgpt custom gpt",
    },
    {
        "id": "not_test_fixture",
        "description": "Session is not a dev/test fixture (fixture summary or duplicate storm)",
    },
    {
        "id": "spark_staged",
        "description": "Spark candidate status is staged or active",
    },
    {
        "id": "content_present",
        "description": "Spark has non-empty content",
    },
    {
        "id": "why_keep_present",
        "description": "Spark metadata includes why_keep or summary",
    },
    {
        "id": "dedup_canonical",
        "description": "Selected as the canonical row among duplicate staged content",
    },
    {
        "id": "no_active_duplicate",
        "description": "No identical active memory already exists",
    },
    {
        "id": "never_auto_pinned",
        "description": "Portable sparks remain unpinned on promotion",
    },
    {
        "id": "not_sensitive",
        "description": "Sensitive or high-sensitivity sparks remain staged for manual review",
    },
]
WRITEBACK_ACCEPTANCE_REQUIRED_CRITERIA = (
    "not_test_fixture",
    "spark_staged",
    "content_present",
    "why_keep_present",
    "dedup_canonical",
    "no_active_duplicate",
    "never_auto_pinned",
    "not_sensitive",
)

WRITEBACK_ACCEPTANCE_REPORT_PATH = PROJECT_ROOT / ".crowley" / "writeback_acceptance_report.json"

_TEST_FIXTURE_SUMMARY_MARKERS = (
    "v3.9.12 writeback parser scope",
    "bridge verify.",
)


def _normalize_writeback_content(content: str) -> str:
    return " ".join(content.strip().lower().split())


def _portable_session_sparks(
    conn: sqlite3.Connection, session_receipt_id: int
) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT * FROM memory_items
        WHERE source = ?
          AND memory_type = 'event'
          AND json_extract(metadata_json, '$.session_receipt_id') = ?
        ORDER BY id ASC
        """,
        (PORTABLE_TERMINAL_SOURCE, session_receipt_id),
    ).fetchall()
    return list(rows)


def _is_test_fixture_portable_session(
    session_row: sqlite3.Row, spark_rows: list[sqlite3.Row]
) -> bool:
    summary = _normalize_writeback_content(str(session_row["content"] or ""))
    for marker in _TEST_FIXTURE_SUMMARY_MARKERS:
        if marker in summary:
            return True
    if not spark_rows:
        return False
    unique = {
        _normalize_writeback_content(str(row["content"] or "")) for row in spark_rows
    }
    return len(spark_rows) > 5 and len(unique) <= 3


def _find_active_memory_by_content(
    conn: sqlite3.Connection,
    *,
    content: str,
    project_id: int | None,
    exclude_memory_id: int | None = None,
) -> int | None:
    normalized = _normalize_writeback_content(content)
    if not normalized:
        return None
    rows = conn.execute(
        """
        SELECT id, content FROM memory_items
        WHERE status = 'active' AND (project_id = ? OR (? IS NULL AND project_id IS NULL))
        """,
        (project_id, project_id),
    ).fetchall()
    for row in rows:
        row_id = int(row["id"])
        if exclude_memory_id is not None and row_id == int(exclude_memory_id):
            continue
        if _normalize_writeback_content(str(row["content"] or "")) == normalized:
            return row_id
    return None


def _evaluate_portable_spark_acceptance(
    *,
    session_row: sqlite3.Row,
    spark_row: sqlite3.Row,
    spark_rows: list[sqlite3.Row],
    is_test_fixture: bool,
    canonical_ids: set[int],
    conn: sqlite3.Connection,
) -> dict[str, object]:
    meta = _memory_item_metadata(spark_row)
    surface = str(meta.get("surface") or "").strip().lower()
    sensitivity = str(meta.get("sensitivity") or "normal").strip().lower()
    why_keep = str(meta.get("why_keep") or spark_row["summary"] or "").strip()
    content = str(spark_row["content"] or "").strip()
    criteria: dict[str, bool] = {
        "chatgpt_surface": surface.startswith("chatgpt"),
        "not_test_fixture": not is_test_fixture,
        "spark_staged": str(spark_row["status"] or "") in {
            PORTABLE_SPARK_STATUS,
            "active",
        },
        "content_present": bool(content),
        "why_keep_present": len(why_keep) >= MEMORY_GATE_WHY_MIN_LEN,
        "dedup_canonical": int(spark_row["id"]) in canonical_ids,
        "no_active_duplicate": _find_active_memory_by_content(
            conn,
            content=content,
            project_id=int(spark_row["project_id"])
            if spark_row["project_id"] is not None
            else None,
            exclude_memory_id=int(spark_row["id"]),
        )
        is None,
        "never_auto_pinned": int(spark_row["pinned"] or 0) == 0,
        "not_sensitive": sensitivity not in {"sensitive", "high"},
    }
    accepted = all(bool(criteria.get(key)) for key in WRITEBACK_ACCEPTANCE_REQUIRED_CRITERIA)
    reason = "accepted" if accepted else next(
        key for key in WRITEBACK_ACCEPTANCE_REQUIRED_CRITERIA if not criteria.get(key)
    )
    return {
        "memory_item_id": int(spark_row["id"]),
        "session_receipt_id": int(session_row["id"]),
        "content": content,
        "summary": why_keep or None,
        "lane": meta.get("lane"),
        "sensitivity": meta.get("sensitivity"),
        "surface": surface or None,
        "status_before": str(spark_row["status"] or ""),
        "accepted": accepted,
        "rejection_reason": None if accepted else reason,
        "criteria": criteria,
        "duplicate_of": None,
    }


def _canonical_staged_spark_ids(spark_rows: list[sqlite3.Row]) -> tuple[set[int], dict[int, list[int]]]:
    canonical: dict[str, int] = {}
    duplicates: dict[int, list[int]] = {}
    for row in spark_rows:
        key = _normalize_writeback_content(str(row["content"] or ""))
        row_id = int(row["id"])
        if not key:
            continue
        if key not in canonical:
            canonical[key] = row_id
            continue
        master = canonical[key]
        duplicates.setdefault(master, []).append(row_id)
    return set(canonical.values()), duplicates


def list_portable_writeback_sessions(
    *, conn: sqlite3.Connection | None = None
) -> list[dict[str, object]]:
    own_conn = conn is None
    if own_conn:
        conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE source = ? AND memory_type = 'summary'
            ORDER BY datetime(created_at) ASC, id ASC
            """,
            (PORTABLE_TERMINAL_SOURCE,),
        ).fetchall()
        sessions: list[dict[str, object]] = []
        for row in rows:
            meta = _memory_item_metadata(row)
            surface = str(meta.get("surface") or "").strip().lower()
            sparks = _portable_session_sparks(conn, int(row["id"]))
            is_fixture = _is_test_fixture_portable_session(row, sparks)
            sessions.append(
                {
                    "session_receipt_id": int(row["id"]),
                    "created_at": str(row["created_at"]),
                    "surface": surface,
                    "model": meta.get("model"),
                    "summary": str(row["content"] or ""),
                    "classification": "test_fixture" if is_fixture else "user_session",
                    "spark_rows_total": len(sparks),
                    "spark_rows_unique": len(
                        {
                            _normalize_writeback_content(str(s["content"] or ""))
                            for s in sparks
                        }
                    ),
                    "metadata": meta,
                }
            )
        sessions.sort(
            key=lambda item: (
                0 if item["classification"] == "user_session" else 1,
                str(item["created_at"]),
            ),
        )
        user_sessions = [s for s in sessions if s["classification"] == "user_session"]
        fixtures = [s for s in sessions if s["classification"] == "test_fixture"]
        user_sessions.sort(key=lambda item: str(item["created_at"]), reverse=True)
        fixtures.sort(key=lambda item: str(item["created_at"]), reverse=True)
        return user_sessions + fixtures
    finally:
        if own_conn and conn is not None:
            conn.close()


def build_portable_writeback_acceptance_report(*args, **kwargs) -> dict[str, object]:
    return portable_context.build_portable_writeback_acceptance_report(sys.modules[__name__], *args, **kwargs)



def auto_promote_portable_writeback_session(
    session_receipt_id: int,
    *,
    reviewer: str = "crowley",
) -> dict[str, object]:
    """Promote accepted staged sparks for one portable writeback session."""
    return build_portable_writeback_acceptance_report(
        apply=True,
        reviewer=reviewer,
        session_receipt_id=session_receipt_id,
    )


def write_portable_writeback_acceptance_report(*args, **kwargs) -> Path:
    return portable_context.write_portable_writeback_acceptance_report(sys.modules[__name__], *args, **kwargs)



def load_portable_writeback_acceptance_report(*args, **kwargs) -> dict[str, object] | None:
    return portable_context.load_portable_writeback_acceptance_report(sys.modules[__name__], *args, **kwargs)



def _agent_permissions_payload(agent: str) -> dict[str, object]:
    import agent_identity

    return agent_identity.permissions_for_agent(agent)


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
            f"You do not architect in Codex's lane unless {USER_NAME} explicitly asks for planning here.\n"
            "Read Codex only through Crowley's events_from_other_agents — never their chat history."
        ),
        "chatgpt": (
            "You are an external agent on the Crowley memory bus.\n"
            "Crowley is the hub. Read via /api/context or /api/agent/sync; write via handoff ingest."
        ),
    }
    return roles.get(normalized, roles["chatgpt"])


def build_agent_sync_bundle(*args, **kwargs) -> dict[str, object]:
    return agent_sync_bundle.build_agent_sync_bundle(sys.modules[__name__], *args, **kwargs)



def finalize_agent_sync_bundle(*args, **kwargs) -> dict[str, object]:
    return agent_sync_bundle.finalize_agent_sync_bundle(sys.modules[__name__], *args, **kwargs)



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
    "## constraints",
    "## lessons",
    "## next action",
    "## open loops",
    "## qa",
    "next action:",
    "what changed:",
    "open loops:",
)
HANDOFF_TYPED_SECTIONS: tuple[tuple[str, str], ...] = (
    ("Decisions", "decision"),
    ("Decision", "decision"),
    ("Constraints", "constraint"),
    ("Constraint", "constraint"),
    ("Lessons", "lesson"),
    ("Lesson", "lesson"),
    ("State Changed", "project_update"),
    ("Do Not Build", "constraint"),
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


def _extract_handoff_typed_memories(content: str) -> list[tuple[str, str, str]]:
    """Parse handoff ## sections into (memory_type, content, why_it_matters) tuples."""
    seen_keys: set[str] = set()
    results: list[tuple[str, str, str]] = []
    for heading, memory_type in HANDOFF_TYPED_SECTIONS:
        for bullet in _parse_handoff_section_bullets(content, heading):
            norm = _normalize_dedupe_key(bullet)
            if norm in seen_keys:
                continue
            if len(_normalize_text(bullet)) < MEMORY_GATE_WHY_MIN_LEN:
                continue
            seen_keys.add(norm)
            why = _truncate(bullet, 240)
            results.append((memory_type, bullet, why))
    return results


def _handoff_anchor_memory_type(handoff_type: str) -> str:
    mapped = HANDOFF_TYPE_TO_MEMORY.get(handoff_type, "project_update")
    if mapped == "event":
        return "lesson"
    return mapped


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
    ingest_metadata: dict[str, object] = dict(metadata or {})
    ingest_metadata.setdefault("handoff_type", handoff_type)
    ingest_metadata.setdefault("ingest_source", source)

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

    typed_memories = _extract_handoff_typed_memories(trimmed_content)
    memory_items_promoted: dict[str, int] = {
        "decision": 0,
        "constraint": 0,
        "lesson": 0,
    }
    memory_items_rejected: list[str] = []
    promoted_ids: list[int] = []

    handoff_write_action = f"handoff.{handoff_type}"
    handoff_save_kwargs = {
        "agent_id": source,
        "write_action": handoff_write_action,
        "metadata": ingest_metadata,
    }

    for promoted_type, bullet_content, why in typed_memories:
        item_id = save_memory_item(
            promoted_type,
            bullet_content,
            summary=why,
            source=source,
            project_id=project_id,
            importance=4 if promoted_type == "decision" else 3,
            confidence=0.9,
            pinned=False,
            write_action=f"{handoff_write_action}.{promoted_type}",
            agent_id=source,
            metadata=ingest_metadata,
        )
        if item_id is not None:
            promoted_ids.append(int(item_id))
            memory_items_promoted[promoted_type] = (
                int(memory_items_promoted.get(promoted_type, 0)) + 1
            )
        else:
            memory_items_rejected.append(
                f"{promoted_type}: {_truncate(bullet_content, 48)}"
            )

    attempted_memory_type: str | None = None
    attempted_content: str | None = None
    attempted_summary: str | None = None
    if typed_memories:
        summary_line = _memory_gate_section_text(trimmed_content, "Summary")
        anchor_content = summary_line or typed_memories[0][1]
        anchor_summary = summary_line or typed_memories[0][2]
        attempted_memory_type = _handoff_anchor_memory_type(handoff_type)
        attempted_content = anchor_content
        attempted_summary = anchor_summary
        memory_item_id = save_memory_item(
            attempted_memory_type,
            anchor_content,
            summary=anchor_summary,
            source=source,
            project_id=project_id,
            importance=importance,
            confidence=0.9,
            pinned=False,
            **handoff_save_kwargs,
        )
        if memory_item_id is None and promoted_ids:
            memory_item_id = promoted_ids[0]
    else:
        attempted_memory_type = memory_type
        attempted_content = trimmed_content
        attempted_summary = None
        memory_item_id = save_memory_item(
            memory_type,
            trimmed_content,
            source=source,
            project_id=project_id,
            importance=importance,
            confidence=0.9,
            pinned=False,
            **handoff_save_kwargs,
        )

    if memory_item_id is None:
        record_system_metric("ingest_error", label=source)
        gate_reason = "unknown"
        if attempted_memory_type and attempted_content is not None:
            gate = evaluate_memory_quality_gate(
                attempted_memory_type,
                attempted_content,
                summary=attempted_summary,
                source=source,
                importance=importance,
                confidence=0.9,
                project_id=project_id,
            )
            gate_reason = gate.reason
        return {
            "status": "error",
            "error": "failed to save memory_item",
            "gate_reason": gate_reason,
            "memory_item_id": None,
            "applied": {
                "memory_items_promoted": memory_items_promoted,
            },
            "skipped": memory_items_rejected,
        }

    attach_memory_item_metadata(int(memory_item_id), ingest_metadata)

    applied: dict[str, object] = {
        "decisions_added": 0,
        "loops_added": 0,
        "state_fields_updated": [],
        "memory_items_promoted": memory_items_promoted,
        "memory_item_ids": promoted_ids,
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
            applied["decisions_added"] = extract_result.get("decisions_added", 0)
            applied["loops_added"] = extract_result.get("loops_added", 0)
            applied["state_fields_updated"] = list(
                extract_result.get("state_fields_updated") or []
            )
            skipped.extend(list(extract_result.get("skipped") or []))
        else:
            skipped.append("extraction returned no proposals")
    else:
        skipped.append("insufficient signal for extraction")

    if memory_items_rejected:
        skipped.extend(memory_items_rejected)

    record_system_metric("ingest_ok", label=source)
    result: dict[str, object] = {
        "status": "ok",
        "memory_item_id": memory_item_id,
        "applied": applied,
        "skipped": skipped,
    }

    if handoff_type in {"builder_handoff", "architect_handoff"}:
        import handoff_ticket_bridge

        closed_ticket = ingest_metadata.get("closed_work_ticket_id")
        if closed_ticket is None:
            closed_ticket = ingest_metadata.get("ticket_id")
        if closed_ticket is not None:
            try:
                closed_ticket = int(closed_ticket)
            except (TypeError, ValueError):
                closed_ticket = None

        closed_ticket, extraction_source = handoff_ticket_bridge.resolve_work_ticket_link(
            trimmed_content,
            ingest_metadata,
            closed_work_ticket_id=closed_ticket,
        )
        if extraction_source == "content_reference":
            ingest_metadata["ticket_extraction_source"] = extraction_source
        bridge = handoff_ticket_bridge.ensure_handoff_ticket_link(
            int(memory_item_id),
            trimmed_content,
            source=source,
            handoff_type=handoff_type,
            project_id=project_id,
            closed_work_ticket_id=closed_ticket,
            metadata=ingest_metadata,
        )
        handoff_ticket_bridge.require_handoff_memory_parity(int(memory_item_id), bridge)
        bridge["ticket_extraction_source"] = extraction_source
        result["handoff_ticket"] = bridge
        try:
            import memory_ticket_linkage

            bridge_ticket_ids: list[int] = []
            ticket_payload = bridge.get("ticket")
            if isinstance(ticket_payload, dict) and ticket_payload.get("id") is not None:
                bridge_ticket_ids.append(int(ticket_payload["id"]))
            work_ticket_id = bridge.get("work_ticket_id")
            if work_ticket_id is not None:
                bridge_ticket_ids.append(int(work_ticket_id))
            memory_ticket_linkage.sync_handoff_memory_links(
                int(memory_item_id),
                trimmed_content,
                metadata=ingest_metadata,
                ticket_ids=bridge_ticket_ids,
            )
        except Exception:
            pass

    return result


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


def _debug_bus(*args, **kwargs):
    return cli_shell._debug_bus(sys.modules[__name__], *args, **kwargs)


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


def _personality_prompt(*args, **kwargs):
    return conversation_runtime._personality_prompt(sys.modules[__name__], *args, **kwargs)


def _ground_truth_prompt(*args, **kwargs):
    return conversation_runtime._ground_truth_prompt(sys.modules[__name__], *args, **kwargs)


def _greeting_behavior_prompt(*args, **kwargs):
    return conversation_runtime._greeting_behavior_prompt(sys.modules[__name__], *args, **kwargs)


def build_prompt(*args, **kwargs):
    return conversation_runtime.build_prompt(sys.modules[__name__], *args, **kwargs)


def chat_turn(*args, **kwargs):
    return conversation_runtime.chat_turn(sys.modules[__name__], *args, **kwargs)


def ask_crowley(*args, **kwargs):
    return conversation_runtime.ask_crowley(sys.modules[__name__], *args, **kwargs)


# --- CLI helpers --------------------------------------------------------------


def _parse_pipe_pair(*args, **kwargs):
    return cli_shell._parse_pipe_pair(sys.modules[__name__], *args, **kwargs)


def _parse_state_set(*args, **kwargs):
    return cli_shell._parse_state_set(sys.modules[__name__], *args, **kwargs)


def _print_state(*args, **kwargs):
    return cli_shell._print_state(sys.modules[__name__], *args, **kwargs)


def _print_decisions(*args, **kwargs):
    return cli_shell._print_decisions(sys.modules[__name__], *args, **kwargs)


def _print_loops(*args, **kwargs):
    return cli_shell._print_loops(sys.modules[__name__], *args, **kwargs)


def _parse_remember(*args, **kwargs):
    return cli_shell._parse_remember(sys.modules[__name__], *args, **kwargs)


def _parse_task_add(*args, **kwargs):
    return cli_shell._parse_task_add(sys.modules[__name__], *args, **kwargs)


def _print_tasks(*args, **kwargs):
    return cli_shell._print_tasks(sys.modules[__name__], *args, **kwargs)


def _print_world(*args, **kwargs):
    return cli_shell._print_world(sys.modules[__name__], *args, **kwargs)


def _debug_extract(*args, **kwargs):
    return cli_shell._debug_extract(sys.modules[__name__], *args, **kwargs)


def _debug_memories(*args, **kwargs):
    return cli_shell._debug_memories(sys.modules[__name__], *args, **kwargs)


def _debug_sparks(*args, **kwargs):
    return cli_shell._debug_sparks(sys.modules[__name__], *args, **kwargs)


def _debug_tasks(*args, **kwargs):
    return cli_shell._debug_tasks(sys.modules[__name__], *args, **kwargs)


def _debug_brain(*args, **kwargs):
    return cli_shell._debug_brain(sys.modules[__name__], *args, **kwargs)


def _debug_memory_items(*args, **kwargs):
    return cli_shell._debug_memory_items(sys.modules[__name__], *args, **kwargs)


def _debug_retrieve(*args, **kwargs):
    return cli_shell._debug_retrieve(sys.modules[__name__], *args, **kwargs)


def _debug_knowledge(*args, **kwargs):
    return cli_shell._debug_knowledge(sys.modules[__name__], *args, **kwargs)


def _debug_consolidate(*args, **kwargs):
    return cli_shell._debug_consolidate(sys.modules[__name__], *args, **kwargs)


def _debug_prompt(*args, **kwargs):
    return cli_shell._debug_prompt(sys.modules[__name__], *args, **kwargs)


def _handle_command(*args, **kwargs):
    return cli_shell._handle_command(sys.modules[__name__], *args, **kwargs)


def _run_cli_consolidate(*args, **kwargs):
    return cli_shell._run_cli_consolidate(sys.modules[__name__], *args, **kwargs)


def _run_cli_hygiene(*args, **kwargs):
    return cli_shell._run_cli_hygiene(sys.modules[__name__], *args, **kwargs)


def main(*args, **kwargs):
    return cli_shell.main(sys.modules[__name__], *args, **kwargs)


if __name__ == "__main__":
    if _run_cli_consolidate():
        raise SystemExit(0)
    if _run_cli_hygiene():
        raise SystemExit(0)
    main()
