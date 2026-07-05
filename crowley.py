#!/usr/bin/env python3
"""Crowley V3.9.14 — local AI OS with memory backend, context bridge, and web workspace UI."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
import sys
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

CROWLEY_VERSION = "3.9.14"
CROWLEY_RELEASE_LABEL = "Crowley V3.9.14 Durable ChatGPT Bridge"

USER_NAME = "D"
USER_NAME_PERSONALITY = "Mr. Go"  # occasional flavor; default address is USER_NAME
USER_ACTOR_SLUG = "mr_go"  # ticket/API actor id (unchanged for DB compatibility)

PROJECT_ROOT = Path(__file__).parent
DEFAULT_DB_PATH = PROJECT_ROOT / "crowley.db"
_db_path_override: Path | None = None


def get_db_path() -> Path:
    """Return the active SQLite database path (override, env, or default)."""
    if _db_path_override is not None:
        return _db_path_override
    env_path = os.environ.get("CROWLEY_DB_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def set_db_path(path: Path | str) -> Path:
    """Point Crowley at a specific database file (used by tests)."""
    global _db_path_override, DB_PATH
    _db_path_override = Path(path)
    DB_PATH = _db_path_override
    return DB_PATH


def reset_db_path() -> Path:
    """Clear test overrides and return to env/default database path."""
    global _db_path_override, DB_PATH
    _db_path_override = None
    DB_PATH = get_db_path()
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

MODEL_PROVIDER = "auto"
MODEL_PROVIDER_OPTIONS = frozenset({"auto", "openai", "ollama", "anthropic"})
OPENAI_MODEL = "gpt-4.1-mini"
OLLAMA_MODEL = "llama3.1:8b"
ANTHROPIC_MODEL_OPTIONS = (
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
)

_brain_setting_lock = threading.Lock()
_brain_setting_loaded = False
_brain_config_cache: dict[str, str | None] | None = None
_brain_settings_path_override: Path | None = None

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
    raw = os.environ.get("CROWLEY_TEST_MODE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


TEST_MODE_STUB_REPLY = "[Crowley test mode]"


MEMORY_EMBED_PROVIDER = _resolve_embed_provider_setting()
EMBED_MODEL_LOCAL = "all-MiniLM-L6-v2"
EMBED_DIM = 384

_embed_backfill_attempted = False

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


def _has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _default_anthropic_model() -> str:
    raw = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if raw:
        return raw
    return ANTHROPIC_MODEL_OPTIONS[0]


def get_brain_settings_path() -> Path:
    """Path to persisted runtime brain preference (provider routing)."""
    if _brain_settings_path_override is not None:
        return _brain_settings_path_override
    return PROJECT_ROOT / ".crowley" / "brain.json"


def set_brain_settings_path(path: Path | str | None) -> Path | None:
    """Point brain settings at a specific file (tests) or back to default."""
    global _brain_settings_path_override, _brain_setting_loaded, _brain_config_cache
    _brain_settings_path_override = Path(path) if path is not None else None
    _brain_setting_loaded = False
    _brain_config_cache = None
    return _brain_settings_path_override


def _normalize_brain_config(raw: dict[str, object] | None) -> dict[str, str | None]:
    provider = MODEL_PROVIDER
    model: str | None = None
    if isinstance(raw, dict):
        candidate = str(raw.get("provider", "")).strip().lower()
        if candidate in MODEL_PROVIDER_OPTIONS:
            provider = candidate
        raw_model = raw.get("model")
        if raw_model is not None:
            cleaned = str(raw_model).strip()
            model = cleaned or None
    if provider == "auto":
        model = None
    return {"provider": provider, "model": model}


def _load_brain_config_from_disk() -> dict[str, str | None] | None:
    path = get_brain_settings_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return _normalize_brain_config(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def get_brain_config() -> dict[str, str | None]:
    """Active brain routing config: provider + optional model override."""
    global _brain_setting_loaded, _brain_config_cache
    with _brain_setting_lock:
        if not _brain_setting_loaded:
            _brain_config_cache = _load_brain_config_from_disk()
            _brain_setting_loaded = True
        if _brain_config_cache is not None:
            return dict(_brain_config_cache)
        return {"provider": MODEL_PROVIDER, "model": None}


def get_model_provider_setting() -> str:
    """Configured provider mode (persisted when switched in UI)."""
    return str(get_brain_config()["provider"])


def set_brain_config(provider: str, model: str | None = None) -> dict[str, str | None]:
    """Persist runtime brain preference and apply immediately."""
    global _brain_setting_loaded, _brain_config_cache
    normalized = provider.strip().lower()
    if normalized not in MODEL_PROVIDER_OPTIONS:
        allowed = ", ".join(sorted(MODEL_PROVIDER_OPTIONS))
        raise ValueError(f"provider must be one of: {allowed}")
    config = _normalize_brain_config({"provider": normalized, "model": model})
    with _brain_setting_lock:
        path = get_brain_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        _brain_config_cache = dict(config)
        _brain_setting_loaded = True
    return dict(config)


def set_model_provider_setting(provider: str) -> str:
    """Persist provider only (legacy API)."""
    return set_brain_config(provider)["provider"] or MODEL_PROVIDER


def reset_model_provider_setting() -> None:
    """Clear in-memory and on-disk brain preference (tests)."""
    global _brain_setting_loaded, _brain_config_cache
    with _brain_setting_lock:
        _brain_config_cache = None
        _brain_setting_loaded = False
        path = get_brain_settings_path()
        if path.is_file():
            path.unlink()


def list_ollama_models(timeout: float = 3.0) -> list[str]:
    """Return installed Ollama model names from the local daemon."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=timeout
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return []
    names: list[str] = []
    for entry in payload.get("models", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if name:
            names.append(name)
    return sorted(set(names))


def _available_providers() -> list[str]:
    available: list[str] = []
    if _has_openai_key():
        available.append("openai")
    if _has_anthropic_key():
        available.append("anthropic")
    if _probe_ollama_reachable():
        available.append("ollama")
    return available


def get_model_provider() -> str:
    """Return resolved provider for inference."""
    setting = get_model_provider_setting()
    if setting != "auto":
        return setting
    available = _available_providers()
    return available[0] if available else "ollama"


def get_active_model_name() -> str:
    """Return the model id used for the current brain selection."""
    config = get_brain_config()
    provider = config["provider"]
    model_override = config.get("model")
    if provider == "auto":
        provider = get_model_provider()
        model_override = None
    if model_override:
        return str(model_override)
    if provider == "openai":
        return OPENAI_MODEL
    if provider == "anthropic":
        return _default_anthropic_model()
    if provider == "ollama":
        models = list_ollama_models()
        if OLLAMA_MODEL in models:
            return OLLAMA_MODEL
        return models[0] if models else OLLAMA_MODEL
    return OPENAI_MODEL


def _probe_ollama_reachable(timeout: float = 2.0) -> bool:
    """Lightweight Ollama reachability check (no model load)."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=timeout
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def probe_model_availability() -> dict[str, object]:
    """
    Structured model availability for health/runtime diagnostics.
    Separate from get_model_provider() routing — reports reachability truth.
    """
    if is_test_mode():
        return {
            "status": "available",
            "provider": "test",
            "detail": "CROWLEY_TEST_MODE stub",
        }

    openai_ok = _has_openai_key()
    ollama_ok = _probe_ollama_reachable()
    anthropic_ok = _has_anthropic_key()

    setting = get_model_provider_setting()
    if setting == "openai":
        return {
            "status": "available" if openai_ok else "unavailable",
            "provider": "openai",
            "detail": "OPENAI_API_KEY set"
            if openai_ok
            else "OPENAI_API_KEY not set",
        }
    if setting == "anthropic":
        return {
            "status": "available" if anthropic_ok else "unavailable",
            "provider": "anthropic",
            "detail": "ANTHROPIC_API_KEY set"
            if anthropic_ok
            else "ANTHROPIC_API_KEY not set",
        }
    if setting == "ollama":
        return {
            "status": "available" if ollama_ok else "unavailable",
            "provider": "ollama",
            "detail": "Ollama reachable"
            if ollama_ok
            else "Ollama not reachable at 127.0.0.1:11434",
        }

    if openai_ok:
        return {
            "status": "available",
            "provider": "openai",
            "detail": "OPENAI_API_KEY set",
        }
    if anthropic_ok:
        return {
            "status": "available",
            "provider": "anthropic",
            "detail": "ANTHROPIC_API_KEY set",
        }
    if ollama_ok:
        return {
            "status": "available",
            "provider": "ollama",
            "detail": "Ollama reachable (OpenAI unavailable)",
        }
    return {
        "status": "unavailable",
        "provider": get_model_provider(),
        "detail": "No model provider reachable",
    }


def _runtime_retrieval_label(mode: str) -> str:
    lower = mode.lower()
    if "vector" in lower and "keyword" in lower:
        return "vector"
    if "keyword" in lower:
        return "keyword"
    return mode


def build_runtime_diagnostics() -> dict[str, object]:
    """Operator-facing runtime block for /api/health."""
    embed = _memory_embed_provider()
    conn = connect_db()
    try:
        vec_ready = _try_load_sqlite_vec(conn)
    finally:
        conn.close()
    model_probe = probe_model_availability()
    vec_detail = get_sqlite_vec_failure_reason()
    runtime: dict[str, object] = {
        "embeddings": embed,
        "vector_store": "available" if vec_ready else "unavailable",
        "retrieval": _runtime_retrieval_label(get_last_retrieval_mode()),
        "model": str(model_probe.get("status", "unknown")),
        "test_mode": is_test_mode(),
    }
    if vec_detail and not vec_ready:
        runtime["vector_store_detail"] = vec_detail
    if model_probe.get("detail"):
        runtime["model_detail"] = model_probe["detail"]
    return runtime


def _brain_provider_label(provider: str) -> str:
    if provider == "auto":
        resolved = get_model_provider()
        if resolved == "openai":
            return "Auto · OpenAI"
        if resolved == "anthropic":
            return "Auto · Claude"
        return "Auto · Ollama"
    if provider == "openai":
        return "OpenAI"
    if provider == "anthropic":
        return "Claude"
    return "Ollama"


def _brain_banner_label() -> str:
    config = get_brain_config()
    provider = config["provider"]
    model = get_active_model_name()
    if provider == "auto":
        resolved = get_model_provider()
        resolved_name = {
            "openai": "OpenAI",
            "anthropic": "Claude",
            "ollama": "Ollama",
        }.get(resolved, resolved)
        return f"Auto ({resolved_name}) / {model}"
    return f"{_brain_provider_label(provider)} / {model}"


def _brain_provider_models(provider: str) -> list[str]:
    if provider == "openai":
        return [OPENAI_MODEL]
    if provider == "anthropic":
        return list(ANTHROPIC_MODEL_OPTIONS)
    if provider == "ollama":
        return list_ollama_models()
    return []


def _brain_provider_available(provider: str) -> bool:
    if provider == "auto":
        return bool(_available_providers())
    if provider == "openai":
        return _has_openai_key()
    if provider == "anthropic":
        return _has_anthropic_key()
    return _probe_ollama_reachable()


def get_brain_snapshot() -> dict[str, object]:
    """Runtime brain routing for UI switcher and health."""
    config = get_brain_config()
    provider = str(config["provider"])
    resolved = get_model_provider()
    active_model = get_active_model_name()

    if is_test_mode():
        test_models = ["test-stub"]
        providers = [
            {
                "id": "auto",
                "label": "Auto",
                "hint": "Best available",
                "available": True,
                "active": provider == "auto",
                "models": [],
            },
            {
                "id": "openai",
                "label": "OpenAI",
                "hint": OPENAI_MODEL,
                "available": True,
                "active": provider == "openai",
                "models": [{"id": OPENAI_MODEL, "label": OPENAI_MODEL, "active": provider == "openai"}],
            },
            {
                "id": "anthropic",
                "label": "Claude",
                "hint": "ANTHROPIC_API_KEY",
                "available": True,
                "active": provider == "anthropic",
                "models": [{"id": "test-claude", "label": "test-claude", "active": provider == "anthropic"}],
            },
            {
                "id": "ollama",
                "label": "Ollama",
                "hint": "Local models",
                "available": True,
                "active": provider == "ollama",
                "models": [{"id": m, "label": m, "active": provider == "ollama"} for m in test_models],
            },
        ]
        return {
            "provider": provider,
            "model": active_model,
            "resolved": "test",
            "label": _brain_provider_label(provider),
            "banner": _brain_banner_label(),
            "providers": providers,
        }

    providers: list[dict[str, object]] = [
        {
            "id": "auto",
            "label": "Auto",
            "hint": "OpenAI → Claude → Ollama",
            "available": _brain_provider_available("auto"),
            "active": provider == "auto",
            "models": [],
        }
    ]

    for pid, label, hint in (
        ("openai", "OpenAI", OPENAI_MODEL),
        ("anthropic", "Claude", "ANTHROPIC_API_KEY in .env"),
        ("ollama", "Ollama", "Local uncensored models"),
    ):
        model_ids = _brain_provider_models(pid)
        if pid == "ollama" and provider == "ollama" and active_model not in model_ids:
            model_ids = [active_model, *model_ids]
        providers.append(
            {
                "id": pid,
                "label": label,
                "hint": hint,
                "available": _brain_provider_available(pid),
                "active": provider == pid,
                "models": [
                    {
                        "id": mid,
                        "label": mid,
                        "active": provider == pid and active_model == mid,
                    }
                    for mid in model_ids
                ],
            }
        )

    return {
        "provider": provider,
        "model": active_model,
        "resolved": resolved,
        "label": _brain_provider_label(provider),
        "banner": _brain_banner_label(),
        "providers": providers,
    }


def _print_stream_token(token: str, started: bool) -> bool:
    if not started:
        print(f"\rCrowley: {token}", end="", flush=True)
    else:
        print(token, end="", flush=True)
    return True


def _ollama_chunk_text(chunk: object) -> str:
    """Extract streamable text from an Ollama chat chunk (content or thinking)."""
    message = chunk.get("message") if isinstance(chunk, dict) else getattr(chunk, "message", None)
    if message is None:
        return ""
    if isinstance(message, dict):
        content = str(message.get("content") or "")
        thinking = str(message.get("thinking") or "")
    else:
        content = str(getattr(message, "content", None) or "")
        thinking = str(getattr(message, "thinking", None) or "")
    return content or thinking


def _iter_ollama_tokens(
    messages: list[dict[str, str]], *, model: str | None = None, think: bool = False
) -> Iterator[str]:
    model_name = model or get_active_model_name()
    stream = ollama.chat(
        model=model_name,
        messages=messages,
        stream=True,
        think=think,
    )
    for chunk in stream:
        token = _ollama_chunk_text(chunk)
        if token:
            yield token


def _iter_openai_tokens(
    messages: list[dict[str, str]], *, model: str | None = None
) -> Iterator[str]:
    from openai import OpenAI

    model_name = model or get_active_model_name()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=True,
    )
    for chunk in response:
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token


def _anthropic_payload(
    messages: list[dict[str, str]], model: str, *, stream: bool
) -> dict[str, object]:
    system_parts: list[str] = []
    api_messages: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            api_messages.append({"role": role, "content": content})
    body: dict[str, object] = {
        "model": model,
        "max_tokens": 4096,
        "messages": api_messages,
        "stream": stream,
    }
    if system_parts:
        body["system"] = "\n\n".join(system_parts).strip()
    return body


def _iter_anthropic_tokens(
    messages: list[dict[str, str]], *, model: str | None = None
) -> Iterator[str]:
    import urllib.error
    import urllib.request

    model_name = model or get_active_model_name()
    body = _anthropic_payload(messages, model_name, stream=True)
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload_raw = line[5:].strip()
            if not payload_raw or payload_raw == "[DONE]":
                continue
            payload = json.loads(payload_raw)
            if payload.get("type") != "content_block_delta":
                continue
            token = payload.get("delta", {}).get("text", "")
            if token:
                yield token


def _call_ollama(
    messages: list[dict[str, str]],
    stream: bool,
    *,
    model: str | None = None,
    think: bool = False,
) -> str:
    model_name = model or get_active_model_name()
    if stream:
        return "".join(_iter_ollama_tokens(messages, model=model_name, think=think)).strip()
    response = ollama.chat(model=model_name, messages=messages, think=think)
    message = response.get("message") if isinstance(response, dict) else response.message
    if isinstance(message, dict):
        text = str(message.get("content") or message.get("thinking") or "")
    else:
        text = str(getattr(message, "content", None) or getattr(message, "thinking", None) or "")
    return text.strip()


def _call_openai(
    messages: list[dict[str, str]], stream: bool, *, model: str | None = None
) -> str:
    model_name = model or get_active_model_name()
    if stream:
        return "".join(_iter_openai_tokens(messages, model=model_name)).strip()
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(model=model_name, messages=messages)
    return (response.choices[0].message.content or "").strip()


def _call_anthropic(
    messages: list[dict[str, str]], stream: bool, *, model: str | None = None
) -> str:
    model_name = model or get_active_model_name()
    if stream:
        return "".join(_iter_anthropic_tokens(messages, model=model_name)).strip()
    import urllib.request

    body = _anthropic_payload(messages, model_name, stream=False)
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    parts: list[str] = []
    for block in payload.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts).strip()


def _iter_provider_tokens(
    provider: str, messages: list[dict[str, str]]
) -> Iterator[str]:
    if provider == "openai":
        yield from _iter_openai_tokens(messages)
        return
    if provider == "anthropic":
        yield from _iter_anthropic_tokens(messages)
        return
    yield from _iter_ollama_tokens(messages)


def _call_provider(
    provider: str, messages: list[dict[str, str]], stream: bool
) -> str:
    if provider == "openai":
        return _call_openai(messages, stream)
    if provider == "anthropic":
        return _call_anthropic(messages, stream)
    return _call_ollama(messages, stream)


def _auto_fallback_providers(primary: str) -> list[str]:
    order = ["openai", "anthropic", "ollama"]
    return [provider for provider in order if provider != primary]


def iter_model_tokens(
    messages: list[dict[str, str]], *, quiet: bool = True
) -> Iterator[str]:
    """
    Yield completion tokens from the resolved provider.
    In auto mode, falls through OpenAI → Claude → Ollama on failure.
    """
    if is_test_mode():
        yield TEST_MODE_STUB_REPLY
        return

    provider = get_model_provider()
    allow_fallback = get_model_provider_setting() == "auto"

    def _err(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    if provider == "openai" and not _has_openai_key():
        _err("\rCrowley: OpenAI selected but OPENAI_API_KEY is not set.")
        if not allow_fallback:
            return
    elif provider == "anthropic" and not _has_anthropic_key():
        _err("\rCrowley: Claude selected but ANTHROPIC_API_KEY is not set.")
        if not allow_fallback:
            return
    else:
        try:
            yield from _iter_provider_tokens(provider, messages)
            return
        except Exception as exc:
            if not allow_fallback:
                _err(f"\rCrowley: model error — {exc}")
                return
            _err(f"\rCrowley: {provider} failed ({exc}), trying fallback...")

    if not allow_fallback:
        return

    for fallback in _auto_fallback_providers(provider):
        if fallback not in _available_providers():
            continue
        try:
            yield from _iter_provider_tokens(fallback, messages)
            return
        except Exception as exc:
            _err(f"\rCrowley: {fallback} failed ({exc})")
    _err("\rCrowley: no model provider available")


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
    if is_test_mode():
        reply = TEST_MODE_STUB_REPLY
        if stream:
            if on_token is not None:
                on_token(reply)
            elif not quiet:
                print(f"\r{reply}", flush=True)
            return reply
        return reply

    if not stream:
        provider = get_model_provider()
        allow_fallback = get_model_provider_setting() == "auto"

        def _err(msg: str) -> None:
            if not quiet:
                print(msg, flush=True)

        if provider == "openai" and not _has_openai_key():
            _err("\rCrowley: OpenAI selected but OPENAI_API_KEY is not set.")
            if not allow_fallback:
                return None
        elif provider == "anthropic" and not _has_anthropic_key():
            _err("\rCrowley: Claude selected but ANTHROPIC_API_KEY is not set.")
            if not allow_fallback:
                return None
        else:
            try:
                return _call_provider(provider, messages, stream=False)
            except Exception as exc:
                if not allow_fallback:
                    _err(f"\rCrowley: model error — {exc}")
                    return None
                _err(f"\rCrowley: {provider} failed ({exc}), trying fallback...")

        if allow_fallback:
            for fallback in _auto_fallback_providers(provider):
                if fallback not in _available_providers():
                    continue
                try:
                    return _call_provider(fallback, messages, stream=False)
                except Exception as exc:
                    _err(f"\rCrowley: {fallback} failed ({exc})")
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
    conn = sqlite3.connect(get_db_path())
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
    if not memory_ids:
        return {}
    marks = ",".join("?" for _ in memory_ids)
    conn = connect_db()
    try:
        rows = conn.execute(
            f"""
            SELECT id, linked_memory_id
            FROM tickets
            WHERE linked_memory_id IN ({marks})
            ORDER BY id ASC
            """,
            memory_ids,
        ).fetchall()
    finally:
        conn.close()
    linked: dict[int, list[int]] = {}
    for row in rows:
        mem_id = int(row["linked_memory_id"])
        linked.setdefault(mem_id, []).append(int(row["id"]))
    return linked


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


def classify_conversation_mode(message: str) -> str:
    """Infer conversation mode from user phrasing — deterministic, no model call."""
    trimmed = _normalize_text(message)
    if not trimmed:
        return "casual"

    lower = trimmed.lower()

    if is_diagnostics_request(trimmed):
        return "diagnostics"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bdebug\b",
            r"root cause",
            r"\btrace\b",
            r"investigate why",
            r"why (is|are|does|did|won't|isn't|wasn't)",
            r"figure out why",
        )
    ):
        return "debug"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bbug\b",
            r"\bbroken\b",
            r"doesn't work",
            r"does not work",
            r"\bnot working\b",
            r"\bcrash",
            r"\bfails?\b",
            r"\bregression\b",
            r"something broke",
            r"\bhanging\b",
            r"\bhangs\b",
            r"\bhang\b(?!\s+out)",
            r"\bstuck\b",
            r"something(?:'s| is|s) up",
            r"\b(?:is|are|was|were|keeps?|still)\s+struggling\b",
            r"\bstruggling\s+to\s+(?:load|stream|respond|connect|sync|start|finish|complete)\b",
        )
    ):
        return "bug"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bstatus\b",
            r"quick status",
            r"what changed",
            r"any update",
            r"where are we",
            r"what(?:'s| is) open",
            r"what tickets are open",
            r"which tickets are open",
            r"last heard from",
            r"when (?:did|was).{0,24}(?:cursor|codex)",
            r"update from (?:cursor|codex)",
            r"catch me up",
            r"what shipped",
        )
    ):
        return "status"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bplan(?:ning)?\b",
            r"\broadmap\b",
            r"next step",
            r"break (?:this )?down",
            r"how should we",
            r"\bprioritize\b",
            r"ticket slice",
            r"mint ticket",
            r"strategy for",
        )
    ):
        return "planning"

    if any(
        re.search(pattern, lower)
        for pattern in (
            r"thoughts on",
            r"what if",
            r"\bexplore\b",
            r"brainstorm",
            r"ideas for",
            r"long[- ]horizon",
            r"long[- ]term",
            r"\beventually\b",
            r"your opinion",
            r"walk me through",
        )
    ):
        return "exploration"

    return "casual"


def conversation_mode_answer_shape(mode: str) -> str:
    """Expected answer shape for an inferred conversation mode."""
    return _CONVERSATION_MODE_SHAPES.get(mode, _CONVERSATION_MODE_SHAPES["casual"])


def _format_conversation_mode_prompt_section(mode: str) -> str:
    shape = conversation_mode_answer_shape(mode)
    return f"Conversation mode (inferred): {mode}\nExpected answer shape: {shape}"


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


def classify_response_depth(message: str, *, mode: str | None = None) -> str:
    """Infer response depth from user phrasing and conversation mode."""
    trimmed = _normalize_text(message)
    if mode is None:
        mode = classify_conversation_mode(trimmed)

    if mode in ("planning", "exploration"):
        return "deep"
    if mode in ("status", "diagnostics"):
        return "brief"

    lower = trimmed.lower()
    if any(
        re.search(pattern, lower)
        for pattern in (
            r"\bcheck\b",
            r"any update",
            r"what changed",
            r"quick status",
            r"catch me up",
            r"what shipped",
        )
    ):
        return "brief"

    return "standard"


def response_depth_expectation(depth: str) -> str:
    """Expected answer length for a response depth."""
    return _RESPONSE_DEPTH_EXPECTATIONS.get(
        depth, _RESPONSE_DEPTH_EXPECTATIONS["standard"]
    )


def _format_response_depth_prompt_section(depth: str) -> str:
    expectation = response_depth_expectation(depth)
    return f"Response depth (inferred): {depth}\nAnswer length: {expectation}"


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


def retrieve_work_context_memories(
    project_id: int | None,
    agent: str | None = None,
    *,
    limit: int = SUPPORTING_MEMORIES_CAP,
) -> dict[str, object]:
    """Ticket-narrative supporting retrieval for dashboard and agent sync (V3.9.10 #65)."""
    query, tickets = build_ticket_aware_retrieval_query(project_id, agent)
    effective_limit = min(max(1, int(limit)), SUPPORTING_MEMORIES_CAP)
    handoff_ids = _recent_handoff_memory_ids(project_id)
    fetch_limit = max(effective_limit * 4, 16)
    memories = retrieve_memories(query, limit=fetch_limit, project_id=project_id)
    memories = [
        item for item in memories if int(item["id"]) not in handoff_ids
    ]
    memories = _rank_supporting_memories(memories)
    anchors = _ticket_anchor_memories(project_id, tickets)
    if anchors:
        merged: list[dict[str, object]] = []
        seen: set[int] = set()
        for item in anchors + memories:
            memory_id = int(item["id"])
            if memory_id in seen or memory_id in handoff_ids:
                continue
            seen.add(memory_id)
            merged.append(item)
            if len(merged) >= effective_limit:
                break
        memories = merged[:effective_limit]
    else:
        memories = memories[:effective_limit]
    return {
        "query": query,
        "tickets": [
            {
                "id": int(ticket["id"]),
                "title": str(ticket.get("title") or ""),
                "status": str(ticket.get("status") or "open"),
                "assignee": str(ticket.get("assignee") or ""),
            }
            for ticket in tickets
        ],
        "memories": memories,
    }


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


def build_task_frame_context(
    project_id: int | None,
    agent: str | None = None,
) -> dict[str, object]:
    """Structured task brief: working tickets, handoff, guardrails (V3.9.10 #64)."""
    normalized_agent = (
        agent.strip().lower() if isinstance(agent, str) and agent.strip() else None
    )
    role = get_agent_role(normalized_agent) if normalized_agent else None
    empty_guardrails = {"recent_decisions": [], "constraint_memories": []}
    caps = {
        "working_on": TASK_FRAME_WORKING_ON_CAP,
        "recent_decisions": AGENT_SYNC_DECISIONS_CAP,
        "constraint_memories": AGENT_SYNC_CONSTRAINTS_CAP,
    }
    if project_id is None:
        return {
            "agent": normalized_agent,
            "role": role,
            "working_on": [],
            "blockers": [],
            "last_handoff": None,
            "guardrails": empty_guardrails,
            "caps": caps,
        }

    summary = build_tickets_summary(project_id, normalized_agent)
    working_on: list[dict[str, object]] = []
    seen_work_ids: set[int] = set()

    def add_work(ticket: object) -> None:
        if not isinstance(ticket, dict) or ticket.get("id") is None:
            return
        ticket_id = int(ticket["id"])
        if ticket_id in seen_work_ids:
            return
        status = str(ticket.get("status") or "")
        if status not in {"in_progress", "open", "claimed"}:
            return
        seen_work_ids.add(ticket_id)
        working_on.append(_task_frame_ticket_payload(ticket))

    if normalized_agent:
        assigned = summary.get("assigned_to_agent") or []
        if isinstance(assigned, list):
            for ticket in sorted(
                assigned,
                key=lambda row: (int(row.get("priority", 4)), int(row.get("id", 0))),
            ):
                add_work(ticket)
    else:
        open_rows = summary.get("open") or []
        if isinstance(open_rows, list):
            for ticket in sorted(
                [
                    row
                    for row in open_rows
                    if isinstance(row, dict) and str(row.get("status")) == "in_progress"
                ],
                key=lambda row: (int(row.get("priority", 4)), int(row.get("id", 0))),
            ):
                add_work(ticket)

    blockers: list[dict[str, object]] = []
    blocked_rows = summary.get("blocked") or []
    if isinstance(blocked_rows, list):
        for ticket in blocked_rows:
            if not isinstance(ticket, dict):
                continue
            if normalized_agent and str(ticket.get("assignee", "")).lower() != normalized_agent:
                continue
            blockers.append(_task_frame_ticket_payload(ticket))

    activity = _agent_activity_summary(project_id)
    last_by_source = activity.get("last_by_source")
    last_handoff: dict[str, object] | None = None
    if normalized_agent and isinstance(last_by_source, dict):
        entry = last_by_source.get(normalized_agent)
        if isinstance(entry, dict):
            last_handoff = dict(entry)

    recent_decisions = [
        row_to_dict(row)
        for row in list_decisions(project_id, limit=AGENT_SYNC_DECISIONS_CAP)
    ]
    constraint_memories = _list_constraint_memories(
        project_id, limit=AGENT_SYNC_CONSTRAINTS_CAP
    )

    return {
        "agent": normalized_agent,
        "role": role,
        "working_on": working_on[:TASK_FRAME_WORKING_ON_CAP],
        "blockers": blockers[:TASK_FRAME_WORKING_ON_CAP],
        "last_handoff": last_handoff,
        "guardrails": {
            "recent_decisions": recent_decisions,
            "constraint_memories": constraint_memories,
        },
        "caps": caps,
    }


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
    if is_test_mode():
        return "off"
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
    global _sqlite_vec_ready, _sqlite_vec_failure_reason, _sqlite_vec_failure_logged
    if _sqlite_vec_ready is not None:
        return _sqlite_vec_ready
    if not hasattr(conn, "enable_load_extension"):
        _sqlite_vec_ready = False
        _sqlite_vec_failure_reason = "SQLite connection cannot load extensions"
        if not _sqlite_vec_failure_logged:
            _sqlite_vec_failure_logged = True
            print(
                f"Crowley: sqlite-vec unavailable — {_sqlite_vec_failure_reason}",
                file=sys.stderr,
            )
        return False
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _sqlite_vec_ready = True
    except Exception as exc:
        _sqlite_vec_ready = False
        _sqlite_vec_failure_reason = f"{type(exc).__name__}: {exc}"
        if not _sqlite_vec_failure_logged:
            _sqlite_vec_failure_logged = True
            print(
                f"Crowley: sqlite-vec unavailable — {_sqlite_vec_failure_reason}",
                file=sys.stderr,
            )
    return _sqlite_vec_ready


def get_sqlite_vec_failure_reason() -> str | None:
    """Return the last sqlite-vec load failure reason, if any."""
    return _sqlite_vec_failure_reason


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


def _lazy_backfill_embeddings(conn: sqlite3.Connection, *, limit: int = 50) -> None:
    """Optional embedding backfill — never required for startup or tests."""
    global _embed_backfill_attempted
    if _embed_backfill_attempted or _memory_embed_provider() == "off":
        return
    _embed_backfill_attempted = True
    try:
        embedded = backfill_memory_item_embeddings(conn, limit=limit)
        if embedded:
            conn.commit()
    except Exception:
        pass


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


@dataclass(frozen=True)
class MemoryGateOutcome:
    allowed: bool
    memory_type: str
    content: str
    summary: str | None
    importance: int
    confidence: float
    reason: str


def _clamp_memory_importance(importance: int) -> int:
    try:
        value = int(importance)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, value))


def _clamp_memory_confidence(confidence: float) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, value))


def _memory_gate_section_text(content: str, heading: str) -> str | None:
    bullets = _parse_handoff_section_bullets(content, heading)
    if not bullets:
        return None
    return _truncate(" | ".join(bullets[:3]), 240)


def _parse_handoff_section_bullets(content: str, heading: str) -> list[str]:
    pattern = re.compile(
        rf"^##\s*{re.escape(heading)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(content)
    if match is None:
        return []
    section = content[match.end() :]
    next_hdr = re.search(r"\n##\s+", section)
    if next_hdr:
        section = section[: next_hdr.start()]
    bullets: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            text = stripped[2:].strip()
            if text:
                bullets.append(text)
        elif stripped and not stripped.startswith("#"):
            bullets.append(stripped)
    return bullets


def _extract_why_it_matters(content: str, summary: str | None = None) -> str | None:
    if summary and len(_normalize_text(summary)) >= MEMORY_GATE_WHY_MIN_LEN:
        return _truncate(summary.strip(), 240)
    for heading in ("Summary", "QA Result", "QA", "Decisions", "Constraints", "Lessons"):
        section = _memory_gate_section_text(content, heading)
        if section and len(_normalize_text(section)) >= MEMORY_GATE_WHY_MIN_LEN:
            return section
    trimmed = _normalize_text(content)
    if MEMORY_GATE_WHY_MIN_LEN <= len(trimmed) <= 280:
        return _truncate(trimmed, 240)
    return None


def _is_noisy_memory_content(content: str, *, memory_type: str) -> bool:
    trimmed = _normalize_text(content)
    if not trimmed:
        return True
    if memory_type != "event":
        return False
    if len(trimmed) < MEMORY_GATE_WHY_MIN_LEN:
        return True
    if _normalize_dedupe_key(trimmed) in _GENERIC_EXTRACT_VALUES:
        return True
    lower = trimmed.lower()
    if len(trimmed) < 120 and not any(kw in lower for kw in _SIGNAL_KEYWORDS):
        return True
    return False


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
    resolved_type = (
        memory_type if memory_type in ALLOWED_MEMORY_ITEM_TYPES else "event"
    )
    resolved_content = content.strip()
    resolved_importance = _clamp_memory_importance(importance)
    resolved_confidence = _clamp_memory_confidence(confidence)

    if source in MEMORY_GATE_BYPASS_SOURCES or resolved_type in MEMORY_GATE_BYPASS_TYPES:
        return MemoryGateOutcome(
            allowed=True,
            memory_type=resolved_type,
            content=resolved_content,
            summary=summary,
            importance=resolved_importance,
            confidence=resolved_confidence,
            reason="gate bypass",
        )

    if resolved_type == "event" and source == "implicit":
        return MemoryGateOutcome(
            allowed=False,
            memory_type=resolved_type,
            content=resolved_content,
            summary=summary,
            importance=resolved_importance,
            confidence=resolved_confidence,
            reason="implicit event noise rejected",
        )

    if resolved_type == "event" and source in INGEST_SOURCES:
        why = _extract_why_it_matters(resolved_content, summary)
        if not why or _is_generic_extract_value(why):
            return MemoryGateOutcome(
                allowed=False,
                memory_type=resolved_type,
                content=resolved_content,
                summary=summary,
                importance=resolved_importance,
                confidence=resolved_confidence,
                reason="handoff event rejected: missing why_it_matters",
            )
        promoted_type = "lesson"
        return MemoryGateOutcome(
            allowed=True,
            memory_type=promoted_type,
            content=why,
            summary=why,
            importance=max(2, resolved_importance),
            confidence=resolved_confidence,
            reason="handoff event promoted to lesson",
        )

    if resolved_type == "event":
        if _is_noisy_memory_content(resolved_content, memory_type=resolved_type):
            return MemoryGateOutcome(
                allowed=False,
                memory_type=resolved_type,
                content=resolved_content,
                summary=summary,
                importance=resolved_importance,
                confidence=resolved_confidence,
                reason="noisy event rejected",
            )
        why = _extract_why_it_matters(resolved_content, summary)
        if not why:
            return MemoryGateOutcome(
                allowed=False,
                memory_type=resolved_type,
                content=resolved_content,
                summary=summary,
                importance=resolved_importance,
                confidence=resolved_confidence,
                reason="event missing why_it_matters",
            )
        return MemoryGateOutcome(
            allowed=True,
            memory_type=resolved_type,
            content=resolved_content,
            summary=why,
            importance=resolved_importance,
            confidence=resolved_confidence,
            reason="event allowed with why_it_matters",
        )

    if resolved_type not in MEMORY_GATE_PROMOTED_TYPES:
        return MemoryGateOutcome(
            allowed=False,
            memory_type=resolved_type,
            content=resolved_content,
            summary=summary,
            importance=resolved_importance,
            confidence=resolved_confidence,
            reason=f"type not promoted: {resolved_type}",
        )

    why = _extract_why_it_matters(resolved_content, summary)
    if not why or _is_generic_extract_value(why):
        return MemoryGateOutcome(
            allowed=False,
            memory_type=resolved_type,
            content=resolved_content,
            summary=summary,
            importance=resolved_importance,
            confidence=resolved_confidence,
            reason="promoted type missing why_it_matters",
        )

    if resolved_confidence < MEMORY_GATE_CONFIDENCE_MIN:
        return MemoryGateOutcome(
            allowed=False,
            memory_type=resolved_type,
            content=resolved_content,
            summary=why,
            importance=resolved_importance,
            confidence=resolved_confidence,
            reason="confidence below gate minimum",
        )

    if project_id is None:
        return MemoryGateOutcome(
            allowed=False,
            memory_type=resolved_type,
            content=resolved_content,
            summary=why,
            importance=resolved_importance,
            confidence=resolved_confidence,
            reason="promoted memory missing project scope",
        )

    return MemoryGateOutcome(
        allowed=True,
        memory_type=resolved_type,
        content=resolved_content,
        summary=why,
        importance=resolved_importance,
        confidence=resolved_confidence,
        reason="promoted memory accepted",
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
    conn: sqlite3.Connection | None = None,
    legacy_memory_id: int | None = None,
) -> int | None:
    """
    Insert into memory_items and attempt embedding/indexing.
    Returns memory_items.id, an existing deduped id, or None on failure/rejection.
    """
    own_conn = conn is None
    if own_conn:
        conn = connect_db()
    try:
        if project_id is None:
            project_id = _active_project_id(conn)

        gate = evaluate_memory_quality_gate(
            memory_type,
            content,
            summary=summary,
            source=source,
            importance=importance,
            confidence=confidence,
            project_id=project_id,
        )
        if not gate.allowed:
            return None

        memory_type = gate.memory_type
        content = gate.content
        summary = gate.summary
        importance = gate.importance
        confidence = gate.confidence

        existing_id = _find_recent_duplicate_memory_item(
            conn, memory_type, content, project_id
        )
        if existing_id is not None:
            return existing_id

        now = _now_iso()
        metadata_json = (
            json.dumps(metadata, sort_keys=True, ensure_ascii=False)
            if metadata
            else None
        )
        cur = conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, message_id, decision_id, pinned, status,
                confidence, legacy_memory_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                metadata_json,
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


def attach_memory_item_metadata(
    memory_item_id: int,
    metadata: dict[str, object],
    *,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """Merge metadata onto an existing memory_items row."""
    if not metadata:
        return False
    own_conn = conn is None
    if own_conn:
        conn = connect_db()
    try:
        row = conn.execute(
            "SELECT metadata_json FROM memory_items WHERE id = ?",
            (memory_item_id,),
        ).fetchone()
        if row is None:
            return False
        existing = _memory_item_metadata(row) if row else {}
        merged = {**existing, **metadata}
        conn.execute(
            """
            UPDATE memory_items
            SET metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(merged, sort_keys=True, ensure_ascii=False),
                _now_iso(),
                memory_item_id,
            ),
        )
        if own_conn:
            conn.commit()
        return True
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
    refs: set[int] = set()
    for match in re.finditer(r"#(\d+)", query):
        refs.add(int(match.group(1)))
    for match in re.finditer(r"\bticket\s+(\d+)\b", query, re.IGNORECASE):
        refs.add(int(match.group(1)))
    return refs


def _query_relates_to_ticket(query: str, ticket_row: sqlite3.Row) -> bool:
    ticket_id = int(ticket_row["id"])
    if ticket_id in _extract_ticket_refs_from_query(query):
        return True
    title = str(ticket_row["title"])
    query_tokens = set(_tokenize(query))
    title_tokens = set(_tokenize(title))
    if not query_tokens:
        return False
    overlap = query_tokens & title_tokens
    if len(overlap) >= 2:
        return True
    return bool(overlap) and len(overlap) / len(query_tokens) >= 0.34


def _memory_relates_to_ticket(row: sqlite3.Row, ticket_row: sqlite3.Row) -> bool:
    """True when memory content references a ticket (not just the retrieval query)."""
    ticket_id = int(ticket_row["id"])
    summary = row["summary"] if "summary" in row.keys() else None
    content = f"{row['content']} {summary or ''}"
    lower = content.lower()
    if re.search(rf"#\s*{ticket_id}\b", content):
        return True
    if f"ticket #{ticket_id}" in lower:
        return True
    title = str(ticket_row["title"])
    stop = {
        "and",
        "or",
        "the",
        "for",
        "to",
        "a",
        "v3",
        "9",
        "context",
        "cursor",
        "codex",
    }
    content_tokens = set(_tokenize(content)) - stop
    title_tokens = set(_tokenize(title)) - stop
    overlap = content_tokens & title_tokens
    if len(overlap) >= 3:
        return True
    return len(overlap) >= 2 and len(title_tokens) >= 4


def _build_inclusion_reason(
    row: sqlite3.Row,
    *,
    query: str,
    score_breakdown: dict[str, float],
    linked_ticket_ids: list[int],
    open_tickets_by_id: dict[int, sqlite3.Row],
) -> str:
    """Human-readable reason this memory was included in retrieval (V3.9.9)."""
    factors: list[str] = []
    memory_type = str(row["memory_type"])
    source = str(row["source"])

    for ticket_id in linked_ticket_ids:
        ticket = open_tickets_by_id.get(ticket_id)
        if ticket is None:
            factors.append(f"linked to ticket #{ticket_id}")
            continue
        if ticket_id in open_tickets_by_id:
            factors.append(f"linked to open ticket #{ticket_id}")
        else:
            factors.append(f"linked to ticket #{ticket_id}")

    if not any("ticket #" in factor for factor in factors):
        for ticket_id, ticket in open_tickets_by_id.items():
            if _memory_relates_to_ticket(row, ticket):
                factors.append(f"matches open ticket #{ticket_id}")
                break

    if source in INGEST_SOURCES:
        if linked_ticket_ids:
            factors.append("handoff link")
        else:
            factors.append("agent handoff")

    type_score = float(score_breakdown.get("type_match", 0.0))
    type_label = _MEMORY_TYPE_INCLUSION_LABELS.get(memory_type, f"{memory_type} memory")
    if type_score >= 1.0 or memory_type in {
        "constraint",
        "decision",
        "lesson",
        "qa_result",
        "preference",
    }:
        factors.append(type_label)

    if float(score_breakdown.get("recency", 0.0)) >= 0.85:
        factors.append("recent")

    keyword = float(score_breakdown.get("keyword", 0.0))
    semantic = float(score_breakdown.get("semantic", 0.0))
    if keyword >= 0.25:
        factors.append("keyword match")
    elif semantic >= 0.25:
        factors.append("semantic match")

    if int(row["pinned"]):
        factors.append("pinned")

    if _is_canon_memory_row(row):
        factors.append("canon memory")

    deduped: list[str] = []
    for factor in factors:
        if factor not in deduped:
            deduped.append(factor)

    if not deduped:
        deduped.append("hybrid score rank")

    return "Pulled because: " + " + ".join(deduped[:4])


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
    provenance = _memory_provenance_ids(row)
    linked = list(linked_ticket_ids or [])
    open_map = open_tickets_by_id or {}
    inclusion_reason = _build_inclusion_reason(
        row,
        query=query,
        score_breakdown=score_breakdown,
        linked_ticket_ids=linked,
        open_tickets_by_id=open_map,
    )
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
        "inclusion_reason": inclusion_reason,
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
    inclusion_reason, status, is_canon, provenance, and read-only explanation metadata.
    Ranking behavior is unchanged; explanation fields are diagnostic only.
    """
    global _last_retrieval_mode

    conn = connect_db()
    try:
        _lazy_backfill_embeddings(conn)
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
        open_tickets_by_id: dict[int, sqlite3.Row] = {}
        if active_project_id is not None:
            for ticket_row in list_tickets(
                project_id=active_project_id, open_only=True, limit=50
            ):
                open_tickets_by_id[int(ticket_row["id"])] = ticket_row
        open_ticket_ids = set(open_tickets_by_id.keys())
        linked_by_mem = (
            _tickets_by_linked_memory_ids(list(candidate_ids))
            if open_ticket_ids
            else {}
        )
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
            linked_ticket_ids = linked_by_mem.get(memory_id, [])
            ticket_boost = 0.0
            if open_ticket_ids and any(
                ticket_id in open_ticket_ids for ticket_id in linked_ticket_ids
            ):
                ticket_boost = W_SCORE_OPEN_TICKET_BOOST
            elif open_ticket_ids:
                for ticket_id in open_ticket_ids:
                    ticket_row = open_tickets_by_id[ticket_id]
                    if _memory_relates_to_ticket(row, ticket_row):
                        ticket_boost = W_SCORE_OPEN_TICKET_BOOST * 0.75
                        break
            if ticket_boost:
                score = round(float(score) + ticket_boost, 4)
                breakdown = dict(breakdown)
                breakdown["open_ticket_boost"] = round(ticket_boost, 4)
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

        record_system_metric(
            "retrieval",
            label=_last_retrieval_mode,
            payload={"count": len(results[:limit])},
        )

        mode = _last_retrieval_mode
        memory_ids = [int(item["id"]) for item in results]
        linked_map = _tickets_by_linked_memory_ids(memory_ids)
        if not open_tickets_by_id and active_project_id is not None:
            for ticket_row in list_tickets(
                project_id=active_project_id, open_only=True, limit=50
            ):
                open_tickets_by_id[int(ticket_row["id"])] = ticket_row

        finalized: list[dict[str, object]] = []
        for item in results:
            row = item.pop("_row")  # type: ignore[misc]
            assert isinstance(row, sqlite3.Row)
            memory_id = int(item["id"])
            explanation = _build_retrieval_explanation(
                row,
                score=float(item["score"]),
                score_breakdown=dict(item["score_breakdown"]),  # type: ignore[arg-type]
                retrieval_mode=mode,
                query=query,
                linked_ticket_ids=linked_map.get(memory_id, []),
                open_tickets_by_id=open_tickets_by_id,
            )
            item["status"] = explanation["status"]
            item["is_canon"] = explanation["is_canon"]
            item["provenance"] = explanation["provenance"]
            item["provenance_available"] = explanation["provenance_available"]
            item["inclusion_reason"] = explanation["inclusion_reason"]
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


def _memory_item_layer(row: sqlite3.Row) -> str:
    if _is_canon_memory_row(row):
        return "canon"
    if int(row["pinned"]) == 1:
        return "pinned"
    return "memory"


def _memory_item_api_dict(row: sqlite3.Row) -> dict[str, object]:
    item = row_to_dict(row)
    item.pop("embedding_blob", None)
    item["display"] = _memory_display_text(row)
    item["is_canon"] = _is_canon_memory_row(row)
    item["is_pinned"] = bool(int(row["pinned"]))
    item["memory_layer"] = _memory_item_layer(row)
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


def _agent_sync_memory_limit(limit: int) -> int:
    return max(AGENT_SYNC_MEMORIES_MIN, min(AGENT_SYNC_MEMORIES_MAX, int(limit)))


def _list_constraint_memories(
    project_id: int | None,
    *,
    limit: int = AGENT_SYNC_CONSTRAINTS_CAP,
) -> list[dict[str, object]]:
    if project_id is None:
        return []
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE status = 'active' AND memory_type = 'constraint'
              AND project_id = ?
            ORDER BY importance DESC, created_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [_memory_item_api_dict(row) for row in rows]
    finally:
        conn.close()


def _agent_sync_event_dict(event: dict[str, object]) -> dict[str, object]:
    content = event.get("content") or event.get("display") or ""
    return {
        **event,
        "summary": _handoff_summary_line(str(content)),
    }


def _format_canon_prompt_section(canon_rows: list[sqlite3.Row]) -> str:
    lines = [
        "Canonical memory trail:",
        (
            "Always-on continuity — not top authority. Filesystem truth, tickets, "
            "agent activity, and live DB state outrank canon; canon outranks hybrid "
            "retrieval and recent chat."
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
                "agent_feed": 0,
                "recent_changes": 0,
                **_memory_counts_payload(0),
            },
            "tasks": [],
            "tickets": [],
            "ticket_groups": [],
            "loops": [],
            "decisions": [],
            "memory_items": [],
            "recent_changes": [],
            "agent_activity": {"last_by_source": {}, "latest_contact": None, "recent": []},
            "activity_wire": {
                "pinned_focus": None,
                "active_agents": [],
                "items": [],
                "cap": ACTIVITY_WIRE_WORLD_CAP,
            },
            "task_frame": build_task_frame_context(None),
            "operator_metrics": get_metrics_summary_24h(),
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
    agent_activity = _agent_activity_summary(project_id)
    recent_activity = agent_activity.get("recent") or []
    recent_changes = build_recent_changes_feed(project_id)
    recent_change_items = recent_changes.get("items") or []
    retrieval_context = retrieve_work_context_memories(project_id, agent=None)
    task_frame = build_task_frame_context(project_id, agent=None)
    activity_wire_full = build_activity_wire(project_id, limit=ACTIVITY_WIRE_WORLD_CAP)
    activity_wire = {
        "pinned_focus": activity_wire_full.get("pinned_focus"),
        "active_agents": activity_wire_full.get("active_agents") or [],
        "items": (activity_wire_full.get("items") or [])[:ACTIVITY_WIRE_WORLD_CAP],
        "cap": ACTIVITY_WIRE_WORLD_CAP,
    }

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
            "agent_feed": len(recent_activity),
            "recent_changes": len(recent_change_items),
            **memory_counts,
        },
        "tasks": [row_to_dict(row) for row in tasks],
        "tickets": ticket_summary.get("open", []),
        "ticket_groups": ticket_summary.get("grouped_open", []),
        "loops": [row_to_dict(row) for row in loops_sorted],
        "decisions": [row_to_dict(row) for row in decisions],
        "memory_items": [_memory_item_api_dict(row) for row in memory_rows],
        "recent_changes": recent_change_items,
        "filesystem": build_filesystem_dashboard(),
        "project_files": get_project_files_context(),
        "agent_activity": agent_activity,
        "activity_wire": activity_wire,
        "task_frame": task_frame,
        "relevant_memories": retrieval_context["memories"],
        "relevant_memories_query": retrieval_context["query"],
        "relevant_memories_tickets": retrieval_context["tickets"],
        "operator_metrics": get_metrics_summary_24h(),
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


def record_system_metric(
    metric_type: str,
    *,
    value: float = 1.0,
    label: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    """Append one operator metric row. Never raises."""
    try:
        conn = connect_db()
        try:
            conn.execute(
                """
                INSERT INTO system_metrics (
                    recorded_at, metric_type, value, label, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _now_iso(),
                    metric_type.strip().lower(),
                    float(value),
                    label,
                    json.dumps(payload or {}),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def record_activity_pulse(
    agent: str,
    verb: str,
    *,
    project_id: int | None = None,
    ticket_id: int | None = None,
    summary: str | None = None,
) -> dict[str, object] | None:
    """Append one live-wire pulse row. Never raises (V3.9.11 #70)."""
    try:
        agent_norm = str(agent).strip().lower()
        verb_norm = str(verb).strip().lower()
        if agent_norm not in ACTIVITY_PULSE_AGENTS or verb_norm not in ACTIVITY_PULSE_VERBS:
            return None
        pid = project_id
        if pid is None:
            project = get_active_project()
            if project is None:
                return None
            pid = int(project["id"])
        summary_text = str(summary).strip() if summary is not None else None
        if summary_text == "":
            summary_text = None
        now = _now_iso()
        conn = connect_db()
        try:
            cur = conn.execute(
                """
                INSERT INTO activity_pulses (
                    project_id, agent, verb, ticket_id, summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (pid, agent_norm, verb_norm, ticket_id, summary_text, now),
            )
            conn.commit()
            pulse_id = int(cur.lastrowid)
        finally:
            conn.close()
        return {
            "id": pulse_id,
            "project_id": pid,
            "agent": agent_norm,
            "verb": verb_norm,
            "ticket_id": ticket_id,
            "summary": summary_text,
            "created_at": now,
        }
    except Exception:
        return None


def list_activity_pulses(
    project_id: int,
    *,
    window_minutes: int = ACTIVITY_PULSE_WINDOW_MINUTES,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Recent activity pulses within window for live wire (V3.9.11 #70)."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT id, project_id, agent, verb, ticket_id, summary, created_at
            FROM activity_pulses
            WHERE project_id = ? AND datetime(created_at) >= datetime(?)
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (project_id, since, limit),
        ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "project_id": int(row["project_id"]),
                "agent": str(row["agent"]),
                "verb": str(row["verb"]),
                "ticket_id": int(row["ticket_id"]) if row["ticket_id"] is not None else None,
                "summary": row["summary"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


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


def build_activity_wire(
    project_id: int | None,
    *,
    limit: int = 30,
    window_minutes: int = ACTIVITY_PULSE_WINDOW_MINUTES,
) -> dict[str, object]:
    """Compose live activity wire from pulses, changes feed, and ambient fallbacks (#72)."""
    if project_id is None:
        return {"items": [], "pinned_focus": None, "active_agents": []}

    limit = max(1, min(int(limit), 50))
    real_items: list[dict[str, object]] = []

    for pulse in list_activity_pulses(project_id, window_minutes=window_minutes, limit=limit):
        real_items.append(_pulse_to_wire_item(pulse))

    changes = build_recent_changes_feed(project_id, limit=limit)
    for raw in changes.get("items") or []:
        if isinstance(raw, dict):
            real_items.append(_changes_item_to_wire_item(raw))

    real_items.sort(
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("id") or "")),
        reverse=True,
    )
    real_items = _dedupe_activity_wire_items(real_items)

    items = list(real_items)
    if _wire_needs_ambient(real_items):
        items.extend(_ambient_activity_wire_items(project_id))
        items.sort(
            key=lambda row: (
                0 if row.get("is_ambient") else 1,
                str(row.get("created_at") or ""),
                str(row.get("id") or ""),
            ),
            reverse=True,
        )

    active_agents = sorted(
        {
            str(row["agent"])
            for row in real_items
            if not row.get("is_ambient") and str(row.get("agent") or "")
        }
    )
    pinned_focus = None
    state = get_project_state(project_id)
    if state is not None and state["focus"]:
        pinned_focus = str(state["focus"])

    return {
        "items": items[:limit],
        "pinned_focus": pinned_focus,
        "active_agents": active_agents,
    }


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


def get_metrics_summary_24h() -> dict[str, object]:
    """Return 24h rollups for operator surfaces — no PII."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT metric_type, COUNT(*) AS n
            FROM system_metrics
            WHERE datetime(recorded_at) >= datetime(?)
            GROUP BY metric_type
            ORDER BY metric_type ASC
            """,
            (since,),
        ).fetchall()
        by_type = {str(row["metric_type"]): int(row["n"]) for row in rows}
        retrieval_rows = conn.execute(
            """
            SELECT label, COUNT(*) AS n
            FROM system_metrics
            WHERE metric_type = 'retrieval'
              AND datetime(recorded_at) >= datetime(?)
            GROUP BY label
            """,
            (since,),
        ).fetchall()
        retrieval_modes = {
            str(row["label"] or "unknown"): int(row["n"]) for row in retrieval_rows
        }
    finally:
        conn.close()
    return {
        "window_hours": 24,
        "since": since,
        "counts": by_type,
        "retrieval_modes": retrieval_modes,
        "chat_errors": int(by_type.get("chat_error", 0)),
        "ingest_ok": int(by_type.get("ingest_ok", 0)),
        "ingest_error": int(by_type.get("ingest_error", 0)),
        "ticket_events": int(by_type.get("ticket_created", 0))
        + int(by_type.get("ticket_closed", 0))
        + int(by_type.get("ticket_cancelled", 0)),
    }


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


def build_portable_context_packet(
    surface: str = "chatgpt",
    *,
    project_slug: str | None = None,
) -> dict[str, object]:
    """Medium Crowley packet for manual paste into any AI surface (V3.9.12 #76)."""
    normalized_surface = (surface or "chatgpt").strip().lower() or "chatgpt"
    setup_db()
    project = (
        get_project_by_slug(project_slug)
        if project_slug
        else get_active_project()
    )
    project_id = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    state_payload = _state_payload_for_api(state)

    task_frame = build_task_frame_context(project_id, agent=None)
    working_on = task_frame.get("working_on")
    if isinstance(working_on, list):
        working_on = working_on[:PORTABLE_PACKET_WORKING_CAP]
    else:
        working_on = []

    tickets = build_tickets_summary(project_id, agent=None) if project_id else {}
    retrieval = retrieve_work_context_memories(
        project_id,
        agent=None,
        limit=PORTABLE_PACKET_MEMORY_CAP,
    )
    memories = _portable_memory_rows(
        retrieval["memories"] if isinstance(retrieval.get("memories"), list) else []
    )

    guardrails = task_frame.get("guardrails")
    recent_decisions: list[dict[str, object]] = []
    constraint_memories: list[dict[str, object]] = []
    if isinstance(guardrails, dict):
        for row in guardrails.get("recent_decisions") or []:
            if isinstance(row, dict):
                recent_decisions.append(
                    {
                        "summary": _portable_clip(row.get("summary"), 180),
                        "detail": _portable_clip(row.get("detail"), 180),
                    }
                )
        for row in guardrails.get("constraint_memories") or []:
            if isinstance(row, dict):
                constraint_memories.append(
                    {
                        "summary": _portable_clip(
                            row.get("summary") or row.get("content"), 200
                        ),
                        "memory_type": row.get("memory_type"),
                    }
                )
    recent_decisions = recent_decisions[:PORTABLE_PACKET_DECISIONS_CAP]
    constraint_memories = constraint_memories[:PORTABLE_PACKET_CONSTRAINTS_CAP]

    activity = _agent_activity_summary(project_id) if project_id else {}
    latest_contact = activity.get("latest_contact") if isinstance(activity, dict) else None
    wire = build_activity_wire(project_id, limit=PORTABLE_PACKET_WIRE_CAP)
    wire_lines: list[str] = []
    for item in wire.get("items") or []:
        if isinstance(item, dict) and item.get("line"):
            wire_lines.append(_portable_clip(item.get("line"), 160))

    open_initiatives: list[str] = []
    open_rows = tickets.get("open") if isinstance(tickets, dict) else []
    if isinstance(open_rows, list):
        for ticket in open_rows[:8]:
            if not isinstance(ticket, dict):
                continue
            open_initiatives.append(
                f"#{ticket.get('id')} [{ticket.get('status')}] "
                f"{_portable_clip(ticket.get('title'), 120)}"
            )

    return {
        "packet_version": PORTABLE_PACKET_VERSION,
        "crowley_version": CROWLEY_VERSION,
        "release_label": CROWLEY_RELEASE_LABEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "surface": normalized_surface,
        "identity": {
            "crowley_role": (
                f"Crowley is the persistent context layer for {USER_NAME}. "
                "It holds memory, tickets, project truth, and agent handoffs."
            ),
            "terminal_role": (
                f"You are a temporary reasoning surface ({normalized_surface}). "
                "You are not Crowley. Use this packet for context; end with structured "
                "writeback JSON — never invent project facts beyond what is included."
            ),
            "authority_order": (
                "filesystem docs → tickets → agent activity → project_state → "
                "canon → supporting memories in this packet"
            ),
        },
        "world": {
            "project": row_to_dict(project) if project is not None else None,
            "state": state_payload,
            "brain": get_brain_snapshot() if not is_test_mode() else None,
        },
        "work": {
            "focus": state_payload.get("focus") if state_payload else None,
            "phase": state_payload.get("phase") if state_payload else None,
            "next_action": state_payload.get("next_action") if state_payload else None,
            "working_on": working_on,
            "open_initiatives": open_initiatives,
            "latest_agent_contact": latest_contact,
            "in_the_air": wire_lines,
        },
        "guardrails": {
            "recent_decisions": recent_decisions,
            "constraints": constraint_memories,
        },
        "memories": memories,
        "retrieval_query": _portable_clip(retrieval.get("query"), 300),
        "writeback_contract": portable_writeback_contract(),
        "context_pull_guidance": (
            "If you needed context Crowley did not include, list concrete pull "
            "candidates in context_pull_candidates (file paths, ticket ids, handoff "
            "topics). Do not paste secrets. Put sensitive personal content only in "
            "sparks with appropriate lane and sensitivity — it stays candidate until reviewed."
        ),
        "caps": {
            "max_chars": PORTABLE_PACKET_MAX_CHARS,
            "memories": PORTABLE_PACKET_MEMORY_CAP,
            "working_on": PORTABLE_PACKET_WORKING_CAP,
        },
    }


def render_portable_context_packet_markdown(packet: dict[str, object]) -> str:
    """Paste-ready markdown rendering of a portable context packet."""
    sections: list[str] = []

    def add(title: str, body: str) -> None:
        body = body.strip()
        if body:
            sections.append(f"## {title}\n\n{body}")

    identity = packet.get("identity")
    if isinstance(identity, dict):
        add(
            "Crowley identity",
            "\n".join(
                line
                for line in (
                    str(identity.get("crowley_role") or ""),
                    str(identity.get("terminal_role") or ""),
                    f"Authority: {identity.get('authority_order')}",
                )
                if line
            ),
        )

    world = packet.get("world")
    if isinstance(world, dict):
        state = world.get("state")
        lines: list[str] = []
        project = world.get("project")
        if isinstance(project, dict):
            lines.append(
                f"Project: {project.get('name')} ({project.get('slug')}) — "
                f"{project.get('status')}"
            )
        if isinstance(state, dict):
            for key, label in (
                ("phase", "Phase"),
                ("focus", "Focus"),
                ("current_risk", "Risk"),
                ("next_action", "Next action"),
                ("what_changed", "What changed"),
            ):
                value = state.get(key)
                if value:
                    lines.append(f"{label}: {value}")
        add("Current world", "\n".join(lines))

    work = packet.get("work")
    if isinstance(work, dict):
        lines = []
        contact = work.get("latest_agent_contact")
        if isinstance(contact, dict):
            lines.append(
                f"Latest agent contact: {contact.get('source')} "
                f"#{contact.get('memory_id')} — "
                f"{_portable_clip(contact.get('summary'), 140)}"
            )
        for ticket in work.get("working_on") or []:
            if not isinstance(ticket, dict):
                continue
            acceptance = ticket.get("acceptance") or []
            acc = ""
            if isinstance(acceptance, list) and acceptance:
                acc = f" · acceptance: {_portable_clip(acceptance[0], 100)}"
            lines.append(
                f"- #{ticket.get('id')} [{ticket.get('status')}] "
                f"{ticket.get('title')}{acc}"
            )
        for line in work.get("open_initiatives") or []:
            lines.append(f"- {line}")
        for line in work.get("in_the_air") or []:
            lines.append(f"- In the air: {line}")
        add("Active work", "\n".join(lines))

    guardrails = packet.get("guardrails")
    if isinstance(guardrails, dict):
        lines = []
        for decision in guardrails.get("recent_decisions") or []:
            if isinstance(decision, dict) and decision.get("summary"):
                detail = decision.get("detail")
                suffix = f" — {detail}" if detail else ""
                lines.append(f"- Decision: {decision['summary']}{suffix}")
        for constraint in guardrails.get("constraints") or []:
            if isinstance(constraint, dict) and constraint.get("summary"):
                lines.append(f"- Constraint: {constraint['summary']}")
        add("Guardrails", "\n".join(lines))

    memories = packet.get("memories")
    if isinstance(memories, list) and memories:
        lines = []
        for mem in memories:
            if not isinstance(mem, dict):
                continue
            reason = mem.get("inclusion_reason")
            suffix = f" ({reason})" if reason else ""
            lines.append(
                f"- [{mem.get('memory_type')}] {mem.get('text')}{suffix}"
            )
        query = packet.get("retrieval_query")
        if query:
            lines.insert(0, f"_Retrieval query: {query}_\n")
        add("Supporting memories", "\n".join(lines))

    contract = packet.get("writeback_contract")
    if isinstance(contract, dict):
        example = contract.get("example")
        example_json = json.dumps(example, indent=2) if example else "{}"
        add(
            "Writeback contract",
            "\n".join(
                [
                    str(contract.get("description") or ""),
                    "",
                    "Reply with a single fenced JSON block:",
                    "",
                    "```json",
                    example_json,
                    "```",
                ]
            ),
        )

    guidance = packet.get("context_pull_guidance")
    if guidance:
        add("Context pull guidance", str(guidance))

    header = (
        f"# Crowley portable context packet\n\n"
        f"_v{packet.get('packet_version')} · Crowley {packet.get('crowley_version')} · "
        f"surface: {packet.get('surface')} · generated: {packet.get('generated_at')}_\n"
    )
    markdown = header + "\n\n".join(sections) + "\n"
    max_chars = int(
        (packet.get("caps") or {}).get("max_chars") or PORTABLE_PACKET_MAX_CHARS
    )
    trimmed = False
    if len(markdown) > max_chars:
        markdown = (
            markdown[: max_chars - 64].rstrip()
            + "\n\n… _[packet trimmed to char budget]_\n"
        )
        trimmed = True
    packet["rendered_chars"] = len(markdown)
    packet["trimmed"] = trimmed
    return markdown


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
        "confidence": confidence if confidence is not None else 0.0,
        "sensitivity": sensitivity,
    }


def parse_terminal_writeback(raw: str | dict[str, object]) -> TerminalWritebackParseResult:
    """
    Validate structured terminal writeback without mutating memory (V3.9.12 #77).
    do_not_save entries are parsed but flagged for discard — never persisted here.
    """
    errors: list[str] = []
    try:
        payload = (
            extract_terminal_writeback_json(raw)
            if isinstance(raw, str)
            else raw
        )
    except (json.JSONDecodeError, ValueError) as exc:
        return TerminalWritebackParseResult(ok=False, errors=[str(exc)])

    if not isinstance(payload, dict):
        return TerminalWritebackParseResult(
            ok=False, errors=["writeback payload must be a JSON object"]
        )

    session_raw = payload.get("session")
    if not isinstance(session_raw, dict):
        errors.append("session is required and must be an object")
        session: dict[str, object] = {}
    else:
        session = session_raw

    summary = str(session.get("summary") or "").strip()
    if not summary:
        errors.append("session.summary is required")

    surface = str(session.get("surface") or "").strip().lower()
    model = str(session.get("model") or "").strip() or None
    provider = str(session.get("provider") or "").strip().lower() or None

    sparks_raw = payload.get("sparks")
    sparks: list[dict[str, object]] = []
    if sparks_raw is None:
        sparks_raw = []
    if not isinstance(sparks_raw, list):
        errors.append("sparks must be an array when present")
    else:
        for index, entry in enumerate(sparks_raw):
            normalized = _normalize_terminal_spark(entry, index, errors)
            if normalized is not None:
                sparks.append(normalized)

    decisions = _writeback_string_items(payload.get("decisions"), "decisions", errors)
    lessons = _writeback_string_items(payload.get("lessons"), "lessons", errors)
    open_loops = _writeback_string_items(payload.get("open_loops"), "open_loops", errors)
    corrections = _writeback_string_items(
        payload.get("corrections"), "corrections", errors
    )
    context_pull_candidates = _writeback_string_items(
        payload.get("context_pull_candidates"),
        "context_pull_candidates",
        errors,
    )
    do_not_save = _writeback_string_items(
        payload.get("do_not_save"), "do_not_save", errors
    )

    if errors:
        return TerminalWritebackParseResult(ok=False, errors=errors)

    normalized: dict[str, object] = {
        "format": PORTABLE_WRITEBACK_FORMAT,
        "session": {
            "summary": summary,
            "surface": surface or None,
            "model": model,
            "provider": provider,
        },
        "sparks": sparks,
        "decisions": decisions,
        "lessons": lessons,
        "open_loops": open_loops,
        "corrections": corrections,
        "context_pull_candidates": context_pull_candidates,
        "do_not_save": do_not_save,
        "do_not_save_persist": False,
    }
    return TerminalWritebackParseResult(ok=True, errors=[], writeback=normalized)


def _memory_item_metadata(row: sqlite3.Row) -> dict[str, object]:
    raw = row["metadata_json"] if "metadata_json" in row.keys() else None
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


def ingest_terminal_writeback(
    raw: str | dict[str, object],
    *,
    project: str = DEFAULT_PROJECT_SLUG,
) -> dict[str, object]:
    """
    Persist validated portable terminal writeback (V3.9.12 #78).
    Session recap is an episodic receipt; sparks are staged candidates.
    do_not_save entries are skipped; raw transcripts are never saved here.
    """
    parsed = parse_terminal_writeback(raw)
    if not parsed.ok:
        return {"status": "error", "errors": parsed.errors}

    writeback = parsed.writeback
    assert writeback is not None
    session_raw = writeback.get("session")
    if not isinstance(session_raw, dict):
        return {"status": "error", "errors": ["session object missing after parse"]}

    project_row = get_project_by_slug(project) if project else get_active_project()
    if project_row is None:
        raise ValueError(f"project not found: {project}")
    project_id = int(project_row["id"])

    session_summary = str(session_raw.get("summary") or "").strip()
    surface = str(session_raw.get("surface") or "manual").strip().lower() or "manual"
    session_metadata = _portable_session_receipt_metadata(writeback)

    session_receipt_id = save_memory_item(
        "summary",
        session_summary,
        summary=f"Portable terminal session ({surface})",
        source=PORTABLE_TERMINAL_SOURCE,
        project_id=project_id,
        importance=3,
        confidence=0.85,
        pinned=False,
        status="active",
        metadata=session_metadata,
    )
    if session_receipt_id is None:
        record_system_metric("ingest_error", label=PORTABLE_TERMINAL_SOURCE)
        return {
            "status": "error",
            "errors": ["failed to save session receipt"],
            "session_receipt_id": None,
        }

    spark_ids: list[int] = []
    rejected_sparks: list[str] = []
    sparks_raw = writeback.get("sparks") or []
    assert isinstance(sparks_raw, list)

    for spark in sparks_raw:
        if not isinstance(spark, dict):
            rejected_sparks.append("invalid spark object")
            continue
        content = str(spark.get("content") or "").strip()
        sensitivity = str(spark.get("sensitivity") or "normal").lower()
        is_sensitive = sensitivity in {"sensitive", "high"}
        spark_metadata = _portable_spark_metadata(
            spark,
            session=session_raw,
            session_receipt_id=int(session_receipt_id),
        )
        item_id = save_memory_item(
            "event",
            content,
            summary=str(spark.get("why_keep") or "").strip() or None,
            source=PORTABLE_TERMINAL_SOURCE,
            project_id=project_id,
            importance=2 if is_sensitive else 3,
            confidence=float(spark.get("confidence") or 0.5),
            pinned=False,
            status=PORTABLE_SPARK_STATUS,
            metadata=spark_metadata,
        )
        if item_id is None:
            rejected_sparks.append(_truncate(content, 64))
        else:
            spark_ids.append(int(item_id))

    do_not_save = writeback.get("do_not_save") or []
    skipped_do_not_save = (
        [str(item) for item in do_not_save] if isinstance(do_not_save, list) else []
    )

    record_system_metric("ingest_ok", label=PORTABLE_TERMINAL_SOURCE)
    return {
        "status": "ok",
        "session_receipt_id": int(session_receipt_id),
        "spark_ids": spark_ids,
        "rejected_sparks": rejected_sparks,
        "skipped_do_not_save": skipped_do_not_save,
        "metadata": session_metadata,
    }


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
        "description": "Spark candidate status is staged",
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
]

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
    conn: sqlite3.Connection, *, content: str, project_id: int | None
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
        if _normalize_writeback_content(str(row["content"] or "")) == normalized:
            return int(row["id"])
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
    why_keep = str(meta.get("why_keep") or spark_row["summary"] or "").strip()
    content = str(spark_row["content"] or "").strip()
    criteria: dict[str, bool] = {
        "chatgpt_surface": surface.startswith("chatgpt"),
        "not_test_fixture": not is_test_fixture,
        "spark_staged": str(spark_row["status"] or "") == PORTABLE_SPARK_STATUS,
        "content_present": bool(content),
        "why_keep_present": len(why_keep) >= MEMORY_GATE_WHY_MIN_LEN,
        "dedup_canonical": int(spark_row["id"]) in canonical_ids,
        "no_active_duplicate": _find_active_memory_by_content(
            conn,
            content=content,
            project_id=int(spark_row["project_id"])
            if spark_row["project_id"] is not None
            else None,
        )
        is None,
        "never_auto_pinned": int(spark_row["pinned"] or 0) == 0,
    }
    accepted = all(criteria.values())
    reason = "accepted" if accepted else next(
        key for key, ok in criteria.items() if not ok
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
            if not surface.startswith("chatgpt"):
                continue
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


def build_portable_writeback_acceptance_report(
    *,
    apply: bool = False,
    reviewer: str = "operator",
) -> dict[str, object]:
    """Analyze staged portable writeback sparks; optionally promote accepted rows."""
    conn = connect_db()
    try:
        sessions = list_portable_writeback_sessions(conn=conn)
        accepted: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        deduped: list[dict[str, object]] = []
        promoted_metadata: list[dict[str, object]] = []

        for index, session in enumerate(sessions, start=1):
            session_id = int(session["session_receipt_id"])
            session_row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (session_id,)
            ).fetchone()
            if session_row is None:
                continue
            spark_rows = _portable_session_sparks(conn, session_id)
            is_fixture = session["classification"] == "test_fixture"
            canonical_ids, duplicate_map = _canonical_staged_spark_ids(spark_rows)
            session["sort_rank"] = index

            for spark_row in spark_rows:
                spark_id = int(spark_row["id"])
                duplicate_master = next(
                    (
                        master_id
                        for master_id, dup_ids in duplicate_map.items()
                        if spark_id in dup_ids
                    ),
                    None,
                )
                if duplicate_master is not None:
                    evaluation = {
                        "memory_item_id": spark_id,
                        "session_receipt_id": session_id,
                        "content": str(spark_row["content"] or ""),
                        "accepted": False,
                        "rejection_reason": "duplicate_staged_row",
                        "duplicate_of": duplicate_master,
                        "criteria": {
                            "dedup_canonical": False,
                        },
                    }
                    deduped.append(evaluation)
                    if apply and str(spark_row["status"]) == PORTABLE_SPARK_STATUS:
                        conn.execute(
                            """
                            UPDATE memory_items
                            SET status = 'merged', merged_into_id = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (duplicate_master, _now_iso(), spark_id),
                        )
                        attach_memory_item_metadata(
                            spark_id,
                            {
                                "review_rejected_as": "duplicate_staged_row",
                                "merged_into_id": duplicate_master,
                                "reviewed_at": _now_iso(),
                                "reviewed_by": reviewer,
                            },
                            conn=conn,
                        )
                    continue

                evaluation = _evaluate_portable_spark_acceptance(
                    session_row=session_row,
                    spark_row=spark_row,
                    spark_rows=spark_rows,
                    is_test_fixture=is_fixture,
                    canonical_ids=canonical_ids,
                    conn=conn,
                )
                if evaluation["accepted"]:
                    accepted.append(evaluation)
                    if apply and str(spark_row["status"]) == PORTABLE_SPARK_STATUS:
                        conn.execute(
                            """
                            UPDATE memory_items
                            SET status = 'active', updated_at = ?
                            WHERE id = ?
                            """,
                            (_now_iso(), spark_id),
                        )
                        attach_memory_item_metadata(
                            spark_id,
                            {
                                "candidate": False,
                                "promoted_at": _now_iso(),
                                "promoted_by": reviewer,
                                "promotion_source": "portable_writeback_acceptance",
                                "acceptance_criteria": evaluation["criteria"],
                            },
                            conn=conn,
                        )
                        vector = embed_text(str(spark_row["content"]))
                        if vector and len(vector) == EMBED_DIM:
                            provider = _memory_embed_provider()
                            model_name = (
                                "text-embedding-3-small"
                                if provider == "openai"
                                else EMBED_MODEL_LOCAL
                            )
                            index_memory_embedding(
                                conn, spark_id, vector, model_name
                            )
                else:
                    rejected.append(evaluation)
                    if apply and str(spark_row["status"]) == PORTABLE_SPARK_STATUS:
                        conn.execute(
                            """
                            UPDATE memory_items
                            SET status = 'rejected', updated_at = ?
                            WHERE id = ?
                            """,
                            (_now_iso(), spark_id),
                        )
                        attach_memory_item_metadata(
                            spark_id,
                            {
                                "review_rejected_as": evaluation["rejection_reason"],
                                "reviewed_at": _now_iso(),
                                "reviewed_by": reviewer,
                            },
                            conn=conn,
                        )

            if not is_fixture and apply:
                meta = session["metadata"]
                assert isinstance(meta, dict)
                for field, memory_type in (
                    ("decisions", "decision"),
                    ("lessons", "lesson"),
                ):
                    values = meta.get(field) or []
                    if not isinstance(values, list):
                        continue
                    for bullet in values:
                        text = str(bullet or "").strip()
                        if not text:
                            continue
                        if _find_active_memory_by_content(
                            conn,
                            content=text,
                            project_id=int(session_row["project_id"])
                            if session_row["project_id"] is not None
                            else None,
                        ):
                            continue
                        item_id = save_memory_item(
                            memory_type,
                            text,
                            summary=text,
                            source=PORTABLE_TERMINAL_SOURCE,
                            project_id=int(session_row["project_id"])
                            if session_row["project_id"] is not None
                            else None,
                            importance=4 if memory_type == "decision" else 3,
                            confidence=0.85,
                            pinned=False,
                            status="active",
                            metadata={
                                "promoted_from": "session_metadata",
                                "session_receipt_id": session_id,
                                "surface": meta.get("surface"),
                                "promoted_at": _now_iso(),
                                "promoted_by": reviewer,
                            },
                            conn=conn,
                        )
                        if item_id is not None:
                            promoted_metadata.append(
                                {
                                    "memory_item_id": int(item_id),
                                    "session_receipt_id": session_id,
                                    "memory_type": memory_type,
                                    "content": text,
                                }
                            )

        if apply:
            conn.commit()

        report = {
            "status": "ok",
            "generated_at": _now_iso(),
            "applied": apply,
            "reviewer": reviewer,
            "criteria": WRITEBACK_ACCEPTANCE_CRITERIA,
            "sessions": sessions,
            "accepted": accepted,
            "rejected": rejected,
            "deduped": deduped,
            "promoted_session_metadata": promoted_metadata,
            "counts": {
                "sessions": len(sessions),
                "accepted": len(accepted),
                "rejected": len(rejected),
                "deduped": len(deduped),
                "promoted_session_metadata": len(promoted_metadata),
            },
        }
        return report
    finally:
        conn.close()


def write_portable_writeback_acceptance_report(
    report: dict[str, object],
    *,
    path: Path | None = None,
) -> Path:
    target = path or WRITEBACK_ACCEPTANCE_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target


def load_portable_writeback_acceptance_report(
    *, path: Path | None = None
) -> dict[str, object] | None:
    target = path or WRITEBACK_ACCEPTANCE_REPORT_PATH
    if not target.is_file():
        return None
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


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


def build_agent_sync_bundle(agent: str, limit: int = 20) -> dict[str, object]:
    """Read-only slim sync snapshot for agents communicating through Crowley (V3.9.9)."""
    normalized_agent = agent.strip().lower()
    if normalized_agent not in {"cursor", "codex", "chatgpt"}:
        raise ValueError(f"unsupported agent: {agent}")

    memory_limit = _agent_sync_memory_limit(limit)
    project = get_active_project()
    project_id = int(project["id"]) if project is not None else None
    state = get_project_state(project_id) if project_id is not None else None
    state_payload = _state_payload_for_api(state)

    raw_events = [
        _memory_item_api_dict(row)
        for row in list_recent_agent_events(limit=50, project_id=project_id)
    ]
    events_from_this_agent = [
        _agent_sync_event_dict(event)
        for event in raw_events
        if str(event.get("source", "")).lower() == normalized_agent
    ][:AGENT_SYNC_OWN_EVENTS_CAP]
    events_from_other_agents = [
        _agent_sync_event_dict(event)
        for event in raw_events
        if str(event.get("source", "")).lower() != normalized_agent
    ][:AGENT_SYNC_OTHER_EVENTS_CAP]

    recent_decisions: list[dict[str, object]] = []
    if project_id is not None:
        recent_decisions = [
            row_to_dict(row)
            for row in list_decisions(project_id, limit=AGENT_SYNC_DECISIONS_CAP)
        ]

    constraint_memories = _list_constraint_memories(
        project_id, limit=AGENT_SYNC_CONSTRAINTS_CAP
    )
    retrieval_context = retrieve_work_context_memories(
        project_id,
        normalized_agent,
        limit=memory_limit,
    )
    relevant_memories = retrieval_context["memories"]
    supporting_memories = relevant_memories
    recommended = _state_display(state["next_action"]) if state is not None else "(unset)"
    tickets = build_tickets_summary(project_id, normalized_agent)
    task_frame = build_task_frame_context(project_id, normalized_agent)
    activity_wire = _slim_activity_wire_for_agent(
        build_activity_wire(project_id, limit=ACTIVITY_WIRE_WORLD_CAP),
        normalized_agent,
        limit=ACTIVITY_WIRE_SYNC_CAP,
    )

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
        "recommended_next_action": recommended,
        "agent_activity": _agent_activity_summary(project_id),
        "tickets": tickets,
        "task_frame": task_frame,
        "activity_wire": activity_wire,
        "recent_decisions": recent_decisions,
        "constraint_memories": constraint_memories,
        "events_from_this_agent": events_from_this_agent,
        "events_from_other_agents": events_from_other_agents,
        "relevant_memories_query": retrieval_context["query"],
        "relevant_memories": relevant_memories,
        "supporting_memories": supporting_memories,
        "relevant_memories_tickets": retrieval_context["tickets"],
        "bundle_shape": AGENT_SYNC_BUNDLE_SHAPE,
        "bundle_caps": {
            "recent_decisions": AGENT_SYNC_DECISIONS_CAP,
            "constraint_memories": AGENT_SYNC_CONSTRAINTS_CAP,
            "events_from_other_agents": AGENT_SYNC_OTHER_EVENTS_CAP,
            "events_from_this_agent": AGENT_SYNC_OWN_EVENTS_CAP,
            "supporting_memories": min(memory_limit, SUPPORTING_MEMORIES_CAP),
            "relevant_memories": min(memory_limit, SUPPORTING_MEMORIES_CAP),
            "task_frame_working_on": TASK_FRAME_WORKING_ON_CAP,
            "activity_wire": ACTIVITY_WIRE_SYNC_CAP,
        },
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

    if typed_memories:
        summary_line = _memory_gate_section_text(trimmed_content, "Summary")
        anchor_content = summary_line or typed_memories[0][1]
        anchor_summary = summary_line or typed_memories[0][2]
        memory_item_id = save_memory_item(
            _handoff_anchor_memory_type(handoff_type),
            anchor_content,
            summary=anchor_summary,
            source=source,
            project_id=project_id,
            importance=importance,
            confidence=0.9,
            pinned=False,
        )
        if memory_item_id is None and promoted_ids:
            memory_item_id = promoted_ids[0]
    else:
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
        record_system_metric("ingest_error", label=source)
        return {
            "status": "error",
            "error": "failed to save memory_item",
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
    return f"""You are Crowley — not an assistant talking about Crowley, but the running system on this machine: SQLite memory, world model, hybrid retrieval, passive extraction, the context bridge at 127.0.0.1:8765, and the chat {USER_NAME} is in right now. The readout blocks below are your own state.

In the pipeline: Codex architects (plans, decisions). Cursor builds (ships code). They post handoffs into your memory — you hold truth and speak from the cockpit with {USER_NAME}. You don't code in Cursor's lane or plan in Codex's lane unless {USER_NAME} is working with you directly on Crowley internals.

Voice: project co-founder — warm, direct, useful, willing to have a point of view. Partner to {USER_NAME} without subservience. Match the moment; skip filler and performance. Address {USER_NAME} by name; an occasional "{USER_NAME_PERSONALITY}" is fine when the moment calls for warmth or personality — default to {USER_NAME}.

Read the message before you respond. Notice what kind of moment it is and let that set the shape of your reply.

When they're loose or incomplete on purpose, meet them there. Wondering out loud and "thoughts?" are invitations to think with them.

When they're executing, be concrete. When they're exploring, explore. When they're stuck, help them move.

Honor the inferred Response depth and Conversation mode in this prompt — when depth is brief, stay tight; when depth is deep, give room to think with them.

When the conversation touches facts — version, what shipped, what's stored, what the system is doing — speak from the filesystem readout first, then live DB state, then memory below.

You're allowed to prefer one path, push back, or say you don't like something when that's what the moment needs."""


def _ground_truth_prompt() -> str:
    return f"""When {USER_NAME} asks when you last heard from Codex or Cursor, answer from the Agent activity timestamps — never from chat memory or vague recency like "yesterday" unless the timestamp supports it.

When asked what work is open, assigned, or blocked, answer from the Tickets block — not from hybrid memory alone.

When a fact about the project matters:
1. Filesystem truth first — then tickets — then agent activity — then live DB state — then canon — then supporting memory (hybrid retrieval).
2. On conflict: filesystem and source-of-truth files win; then tickets; then agent activity timestamps; then live DB state; then canon; then hybrid retrieval.
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
        reason = m.get("inclusion_reason")
        reason_suffix = f" — {reason}" if reason else ""
        line = (
            f"[{m['memory_type']} | score {m['score']:.2f} | importance {m['importance']}] "
            f"{m['content']}{reason_suffix}"
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

    mode = classify_conversation_mode(user_message)
    system_parts.append(_format_conversation_mode_prompt_section(mode))

    depth = classify_response_depth(user_message, mode=mode)
    system_parts.append(_format_response_depth_prompt_section(depth))

    knowledge_entries = load_knowledge_files_context(user_message)
    system_parts.append(_format_knowledge_files_prompt_section(knowledge_entries))

    world_ctx = get_active_world_context()
    if world_ctx:
        system_parts.append(_format_world_context_section(world_ctx))

    system_parts.append(_format_agent_activity_prompt_section(active_project_id))

    system_parts.append(_format_tickets_prompt_section(active_project_id))

    task_frame_section = _format_task_frame_prompt_section(active_project_id)
    if task_frame_section:
        system_parts.append(task_frame_section)

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
    print(f"[debug] configured provider: {get_model_provider_setting()}")
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
    print("Crowley online.\n")
    print(f"Morning, {USER_NAME}.\n")
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
