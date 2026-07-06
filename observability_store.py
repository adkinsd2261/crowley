"""#171/#173 — durable observability logs and session state."""

from __future__ import annotations

import json
from typing import Any

_SESSION_FIELDS = frozenset(
    {
        "synced",
        "sync_count",
        "handoffs_loaded",
        "domain_retrieved",
        "tools_called",
        "chain_depth",
        "intents_seen",
        "pending_query",
        "complex_query",
        "execution_plan",
        "domain_plan",
        "planner_query_key",
        "planner_called_before_gates",
        "planner_attempts",
        "current_dispatch_id",
    }
)


def ensure_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observability_logs (
            id INTEGER PRIMARY KEY,
            session_key TEXT NOT NULL,
            dispatch_id INTEGER,
            tool_called TEXT NOT NULL,
            chain_depth INTEGER NOT NULL DEFAULT 0,
            reason_for_call TEXT,
            triggering_rule TEXT,
            http_status INTEGER,
            bound_to_dispatch INTEGER NOT NULL DEFAULT 0,
            entry_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_observability_logs_session
        ON observability_logs(session_key, id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_state (
            session_key TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _serialize_entry(entry: dict[str, object]) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False)


def append_observability_log(session_key: str, entry: dict[str, object]) -> int | None:
    """Persist one observability log entry (#171)."""
    import crowley

    now = crowley._now_iso()
    conn = crowley.connect_db()
    try:
        ensure_tables(conn)
        cur = conn.execute(
            """
            INSERT INTO observability_logs (
                session_key, dispatch_id, tool_called, chain_depth,
                reason_for_call, triggering_rule, http_status,
                bound_to_dispatch, entry_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_key[:128],
                entry.get("dispatch_id"),
                str(entry.get("tool_called") or entry.get("tool") or ""),
                int(entry.get("chain_depth", 0)),
                str(entry.get("reason_for_call") or entry.get("reason") or ""),
                str(entry.get("triggering_rule") or ""),
                entry.get("http_status"),
                1 if entry.get("bound_to_dispatch") else 0,
                _serialize_entry(entry),
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_observability_logs(session_key: str, *, limit: int = 20) -> list[dict[str, object]]:
    """Return last N persisted observability entries for a session (#171)."""
    import crowley

    limit = max(1, min(int(limit), 200))
    conn = crowley.connect_db()
    try:
        ensure_tables(conn)
        rows = conn.execute(
            """
            SELECT entry_json FROM observability_logs
            WHERE session_key = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_key[:128], limit),
        ).fetchall()
    finally:
        conn.close()
    entries: list[dict[str, object]] = []
    for row in reversed(rows):
        try:
            parsed = json.loads(str(row["entry_json"]))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
    return entries


def update_observability_log_dispatch(
    session_key: str,
    dispatch_id: int,
    entry: dict[str, object],
) -> None:
    """Patch the latest log row for a dispatch (#171)."""
    import crowley

    conn = crowley.connect_db()
    try:
        ensure_tables(conn)
        row = conn.execute(
            """
            SELECT id FROM observability_logs
            WHERE session_key = ? AND dispatch_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (session_key[:128], int(dispatch_id)),
        ).fetchone()
        if row is None:
            append_observability_log(session_key, entry)
            return
        conn.execute(
            """
            UPDATE observability_logs
            SET entry_json = ?, http_status = ?, bound_to_dispatch = ?
            WHERE id = ?
            """,
            (
                _serialize_entry(entry),
                entry.get("http_status"),
                1 if entry.get("bound_to_dispatch") else 0,
                int(row["id"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _state_for_storage(state: dict[str, object]) -> dict[str, object]:
    stored: dict[str, object] = {}
    for key in _SESSION_FIELDS:
        if key in state:
            stored[key] = state[key]
    return stored


def save_session_state(session_key: str, state: dict[str, object]) -> None:
    """Persist session execution state (#173)."""
    import crowley

    payload = _state_for_storage(state)
    now = crowley._now_iso()
    conn = crowley.connect_db()
    try:
        ensure_tables(conn)
        conn.execute(
            """
            INSERT INTO session_state (session_key, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (
                session_key[:128],
                json.dumps(payload, sort_keys=True, ensure_ascii=False),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_session_state(session_key: str) -> dict[str, object] | None:
    """Load persisted session state (#173)."""
    import crowley

    conn = crowley.connect_db()
    try:
        ensure_tables(conn)
        row = conn.execute(
            "SELECT state_json FROM session_state WHERE session_key = ?",
            (session_key[:128],),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        parsed: Any = json.loads(str(row["state_json"]))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def delete_session_state(session_key: str) -> None:
    conn = __import__("crowley").connect_db()
    try:
        ensure_tables(conn)
        conn.execute("DELETE FROM session_state WHERE session_key = ?", (session_key[:128],))
        conn.commit()
    finally:
        conn.close()
