"""#171/#173 — durable observability logs and session state.

#201 — observability logs are tamper-evident via a per-session hash chain.
Each row stores entry_hash = sha256(prev_hash + immutable identity), where the
identity is (session_key, dispatch_id, tool_called, created_at). Deleting,
reordering, inserting, or altering any hashed field breaks the chain and is
detectable by verify_observability_chain(). Mutable fields (http_status,
bound_to_dispatch, entry_json) are intentionally excluded so the legitimate
dispatch-binding patch does not invalidate the chain.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

# Serializes chain appends so concurrent writers cannot fork the per-session
# chain by reading the same predecessor hash. Bus is single-process, so a
# module lock is sufficient; appends are fast (one indexed read + insert).
_append_lock = threading.Lock()

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
    _ensure_chain_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_state (
            session_key TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _ensure_chain_columns(conn) -> None:
    """#201 — add hash-chain columns to pre-existing observability_logs tables."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(observability_logs)").fetchall()}
    if "prev_hash" not in cols:
        conn.execute("ALTER TABLE observability_logs ADD COLUMN prev_hash TEXT")
    if "entry_hash" not in cols:
        conn.execute("ALTER TABLE observability_logs ADD COLUMN entry_hash TEXT")


def _serialize_entry(entry: dict[str, object]) -> str:
    return json.dumps(entry, sort_keys=True, ensure_ascii=False)


def _chain_hash(prev_hash: str, session_key: str, dispatch_id: object, tool_called: str, created_at: str) -> str:
    """Hash of the immutable identity linked to its predecessor (#201)."""
    identity = "|".join(
        [
            prev_hash or "",
            session_key,
            "" if dispatch_id is None else str(dispatch_id),
            tool_called,
            created_at,
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def append_observability_log(session_key: str, entry: dict[str, object]) -> int | None:
    """Persist one observability log entry with a chained hash (#171/#201)."""
    import crowley

    now = crowley._now_iso()
    key = session_key[:128]
    tool_called = str(entry.get("tool_called") or entry.get("tool") or "")
    dispatch_id = entry.get("dispatch_id")
    with _append_lock:
        conn = crowley.connect_db()
        try:
            ensure_tables(conn)
            last = conn.execute(
                """
                SELECT entry_hash FROM observability_logs
                WHERE session_key = ?
                ORDER BY id DESC LIMIT 1
                """,
                (key,),
            ).fetchone()
            prev_hash = str(last["entry_hash"]) if last and last["entry_hash"] else ""
            entry_hash = _chain_hash(prev_hash, key, dispatch_id, tool_called, now)
            cur = conn.execute(
                """
                INSERT INTO observability_logs (
                    session_key, dispatch_id, tool_called, chain_depth,
                    reason_for_call, triggering_rule, http_status,
                    bound_to_dispatch, entry_json, created_at,
                    prev_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    dispatch_id,
                    tool_called,
                    int(entry.get("chain_depth", 0)),
                    str(entry.get("reason_for_call") or entry.get("reason") or ""),
                    str(entry.get("triggering_rule") or ""),
                    entry.get("http_status"),
                    1 if entry.get("bound_to_dispatch") else 0,
                    _serialize_entry(entry),
                    now,
                    prev_hash,
                    entry_hash,
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


def verify_observability_chain(session_key: str, *, limit: int = 500) -> dict[str, object]:
    """#201 — recompute the per-session hash chain and report any tampering.

    Detects deleted, reordered, inserted, or field-altered rows. Legacy rows
    written before the chain existed (NULL entry_hash) are skipped; verification
    begins at the first chained row. Also flags entry_json whose recorded tool
    diverges from the hashed tool_called column.
    """
    import crowley

    limit = max(1, min(int(limit), 2000))
    conn = crowley.connect_db()
    try:
        ensure_tables(conn)
        rows = conn.execute(
            """
            SELECT id, session_key, dispatch_id, tool_called, created_at,
                   prev_hash, entry_hash, entry_json
            FROM observability_logs
            WHERE session_key = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_key[:128], limit),
        ).fetchall()
    finally:
        conn.close()

    checked = 0
    legacy_skipped = 0
    prev_hash = ""
    chain_started = False
    for row in rows:
        stored_hash = row["entry_hash"]
        if not stored_hash:
            if chain_started:
                return {
                    "ok": False,
                    "checked": checked,
                    "legacy_skipped": legacy_skipped,
                    "break_at_id": int(row["id"]),
                    "reason": "missing_hash_after_chain_started",
                }
            legacy_skipped += 1
            continue

        # First chained row anchors the chain from its recorded predecessor.
        if not chain_started:
            chain_started = True
            prev_hash = str(row["prev_hash"] or "")

        if str(row["prev_hash"] or "") != prev_hash:
            return {
                "ok": False,
                "checked": checked,
                "legacy_skipped": legacy_skipped,
                "break_at_id": int(row["id"]),
                "reason": "prev_hash_mismatch",
            }

        expected = _chain_hash(
            prev_hash,
            str(row["session_key"]),
            row["dispatch_id"],
            str(row["tool_called"]),
            str(row["created_at"]),
        )
        if expected != str(stored_hash):
            return {
                "ok": False,
                "checked": checked,
                "legacy_skipped": legacy_skipped,
                "break_at_id": int(row["id"]),
                "reason": "hash_mismatch",
            }

        # entry_json tool must match the hashed column (catches JSON-only edits).
        try:
            parsed = json.loads(str(row["entry_json"]))
            json_tool = str(parsed.get("tool_called") or parsed.get("tool") or "")
        except (json.JSONDecodeError, AttributeError):
            json_tool = ""
        if json_tool and json_tool != str(row["tool_called"]):
            return {
                "ok": False,
                "checked": checked,
                "legacy_skipped": legacy_skipped,
                "break_at_id": int(row["id"]),
                "reason": "entry_json_tool_mismatch",
            }

        prev_hash = str(stored_hash)
        checked += 1

    return {
        "ok": True,
        "checked": checked,
        "legacy_skipped": legacy_skipped,
        "break_at_id": None,
        "reason": None,
    }


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
