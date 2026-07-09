"""Memory embedding and optional sqlite-vec backend helpers."""

from __future__ import annotations

import os
import struct
import sys
from typing import Any


def memory_embed_provider(rt: Any) -> str:
    if rt.is_test_mode():
        return "off"
    if rt.MEMORY_EMBED_PROVIDER == "off":
        return "off"
    if rt.MEMORY_EMBED_PROVIDER == "local":
        return "local"
    if rt.MEMORY_EMBED_PROVIDER == "openai":
        return "openai" if rt._has_openai_key() else "off"
    if rt._has_openai_key():
        return "openai"
    return "local"


def try_load_sqlite_vec(rt: Any, conn: Any) -> bool:
    conn_id = id(conn)
    if conn_id in rt._sqlite_vec_loaded_conns:
        return True
    if rt._sqlite_vec_ready is False:
        return False
    if not hasattr(conn, "enable_load_extension"):
        rt._sqlite_vec_ready = False
        rt._sqlite_vec_failure_reason = "SQLite connection cannot load extensions"
        if not rt._sqlite_vec_failure_logged:
            rt._sqlite_vec_failure_logged = True
            print(
                f"Crowley: sqlite-vec unavailable — {rt._sqlite_vec_failure_reason}",
                file=sys.stderr,
            )
        return False
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        rt._sqlite_vec_loaded_conns.add(conn_id)
        rt._sqlite_vec_ready = True
    except Exception as exc:
        rt._sqlite_vec_ready = False
        rt._sqlite_vec_failure_reason = f"{type(exc).__name__}: {exc}"
        if not rt._sqlite_vec_failure_logged:
            rt._sqlite_vec_failure_logged = True
            print(
                f"Crowley: sqlite-vec unavailable — {rt._sqlite_vec_failure_reason}",
                file=sys.stderr,
            )
    return rt._sqlite_vec_ready


def get_sqlite_vec_failure_reason(rt: Any) -> str | None:
    """Return the last sqlite-vec load failure reason, if any."""
    return rt._sqlite_vec_failure_reason


def pack_embedding(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def vec_bind(vector: list[float]) -> bytes:
    """Packed float bytes for sqlite-vec INSERT and MATCH bindings."""
    return pack_embedding(vector)


def ensure_memory_vec_table(rt: Any, conn: Any) -> bool:
    if not try_load_sqlite_vec(rt, conn):
        return False
    row = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name = 'memory_vec'
        """
    ).fetchone()
    if row:
        try:
            conn.execute("SELECT 1 FROM memory_vec LIMIT 0")
        except Exception:
            return False
        return True
    try:
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE memory_vec USING vec0(
                memory_id INTEGER PRIMARY KEY,
                embedding float[{rt.EMBED_DIM}]
            )
            """
        )
    except Exception:
        return False
    return True


def get_local_embed_model(rt: Any) -> Any:
    if rt._embed_model is not None:
        return rt._embed_model
    with rt._embed_model_lock:
        if rt._embed_model is None:
            from sentence_transformers import SentenceTransformer

            rt._embed_model = SentenceTransformer(rt.EMBED_MODEL_LOCAL)
    return rt._embed_model


def embed_text(rt: Any, text: str) -> list[float] | None:
    """Return an embedding vector for memory_items content, or None if unavailable."""
    content = rt._normalize_text(text)
    if not content:
        return None
    provider = memory_embed_provider(rt)
    if provider == "off":
        return None
    try:
        if provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=content,
                dimensions=rt.EMBED_DIM,
            )
            return list(response.data[0].embedding)
        model = get_local_embed_model(rt)
        vector = model.encode(content, normalize_embeddings=True)
        return [float(x) for x in vector.tolist()]
    except Exception:
        return None


def index_memory_embedding(
    rt: Any,
    conn: Any,
    memory_id: int,
    embedding: list[float],
    model_name: str,
) -> None:
    blob = pack_embedding(embedding)
    conn.execute(
        """
        UPDATE memory_items
        SET embed_model = ?, embed_dim = ?, embedding_blob = ?, updated_at = ?
        WHERE id = ?
        """,
        (model_name, rt.EMBED_DIM, blob, rt._now_iso(), memory_id),
    )
    if not ensure_memory_vec_table(rt, conn):
        return
    try:
        conn.execute(
            "DELETE FROM memory_vec WHERE memory_id = ?",
            (memory_id,),
        )
        conn.execute(
            "INSERT INTO memory_vec(memory_id, embedding) VALUES (?, ?)",
            (memory_id, vec_bind(embedding)),
        )
    except Exception:
        return


def backfill_memory_item_embeddings(rt: Any, conn: Any, limit: int = 200) -> int:
    """Embed memory_items that lack an embedding. Returns count embedded."""
    provider = memory_embed_provider(rt)
    if provider == "off":
        return 0
    ensure_memory_vec_table(rt, conn)
    model_name = (
        "text-embedding-3-small" if provider == "openai" else rt.EMBED_MODEL_LOCAL
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
        vector = embed_text(rt, str(row["content"]))
        if not vector or len(vector) != rt.EMBED_DIM:
            continue
        index_memory_embedding(rt, conn, int(row["id"]), vector, model_name)
        embedded += 1
    return embedded


def lazy_backfill_embeddings(rt: Any, conn: Any, *, limit: int = 50) -> None:
    """Optional embedding backfill — never required for startup or tests."""
    if rt._embed_backfill_attempted or memory_embed_provider(rt) == "off":
        return
    rt._embed_backfill_attempted = True
    try:
        embedded = backfill_memory_item_embeddings(rt, conn, limit=limit)
        if embedded:
            conn.commit()
    except Exception:
        pass
