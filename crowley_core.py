"""Core runtime utilities for the Crowley facade."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

PROJECT_ROOT = Path(__file__).parent
DEFAULT_DB_PATH = PROJECT_ROOT / "crowley.db"
DEFAULT_TRUNCATE_LEN = 200

_db_path_override: Path | None = None


def load_local_env() -> None:
    """Load KEY=VALUE lines from .env into os.environ if not already set."""
    env_path = PROJECT_ROOT / ".env"
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


def get_db_path() -> Path:
    """Return the active SQLite database path (override, env, or default)."""
    if _db_path_override is not None:
        return _db_path_override
    env_path = os.environ.get("CROWLEY_DB_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def set_db_path(path: Path | str) -> Path:
    """Point Crowley at a specific database file."""
    global _db_path_override
    _db_path_override = Path(path)
    return _db_path_override


def reset_db_path() -> Path:
    """Clear test overrides and return to env/default database path."""
    global _db_path_override
    _db_path_override = None
    return get_db_path()


def connect_db() -> sqlite3.Connection:
    """Open crowley.db with WAL mode and row factory."""
    conn = sqlite3.connect(get_db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def truncate(text: str, max_len: int = DEFAULT_TRUNCATE_LEN) -> str:
    text = normalize_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def tokenize(text: str) -> list[str]:
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return [token for token in tokens if len(token) >= 3]


def row_to_dict(row: sqlite3.Row) -> dict[str, object]:
    """Serialize a sqlite3.Row for JSON APIs."""
    return {key: row[key] for key in row.keys()}


def is_test_mode() -> bool:
    """True when CROWLEY_TEST_MODE is enabled."""
    raw = os.environ.get("CROWLEY_TEST_MODE", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


load_local_env()
