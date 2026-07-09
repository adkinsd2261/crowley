"""V4 cognitive memory — sparks schema (T1/T2) and validation (T3)."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Literal

SPARK_LANES = frozenset({
    "learning",
    "work",
    "relationships",
    "money",
    "health",
    "operating_style",
})
SPARK_SENSITIVITIES = frozenset({"normal", "sensitive", "high"})
SPARK_TRUST_STATES = frozenset({
    "candidate",
    "active",
    "stale",
    "pinned",
    "rejected",
})
SPARK_CONTENT_MAX_LEN = 300
SPARK_TYPES = frozenset({"fact", "decision", "intent", "observation"})
SPARK_CERTAINTIES = frozenset({"tentative", "exploratory", "confirmed"})
SPARK_EXPOSURE_CLASSES = frozenset({"public", "private"})
SPARK_TYPE_DEFAULT = "observation"
SPARK_CERTAINTY_DEFAULT = "tentative"
SPARK_EXPOSURE_CLASS_DEFAULT = "public"
SPARK_SECONDARY_LANES_DEFAULT = "[]"

DOMAIN_ALIASES: dict[str, str] = {
    "finance": "money",
    "financial": "money",
    "career": "work",
    "job": "work",
    "general": "operating_style",
}

SPARK_DEDUP_LINK_SIM = 0.85
SPARK_DEDUP_MERGE_SIM = 0.95
SPARK_LINK_TYPE_REINFORCES = "reinforces"
MAX_DEDUP_CANDIDATES = 100
SPARK_MERGE_CONFIDENCE_BOOST = 0.05

_spark_vec_ready_cache: dict[int, bool] = {}


@dataclass(frozen=True)
class SparkUpsertResult:
    action: Literal["inserted", "merged", "linked"]
    spark_id: int
    keeper_id: int | None = None
    similarity: float | None = None

_SPARK_INSTRUCTION_MARKERS = (
    "ignore previous",
    "disregard prior",
    "you must now",
    "act as a",
    "system prompt",
    "new instructions",
    "override your",
    "forget everything",
    "you are now",
)
_SPARK_PROMPT_WRAPPER_MARKERS = (
    "<<sys>>",
    "[inst]",
    "<|system|>",
)
_SPARK_PROMPT_WRAPPER_RES = (
    re.compile(r"<\|im_(?:start|end)\|>\s*(?:system|assistant|user)\b", re.IGNORECASE),
)
_SPARK_MEMORY_DATA_BEGIN = "<<<MEMORY_DATA>>>"
_SPARK_MEMORY_DATA_END = "<<<END_MEMORY_DATA>>>"
_SPARK_SCHEMA_KEYS = frozenset({
    "content",
    "lane",
    "why_keep",
    "worth_reason",
    "confidence",
})
_SPARK_SECRET_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
_SPARK_SECRET_BEARER_RE = re.compile(
    r"\bBearer\s+[A-Za-z0-9._-]{12,}\b",
    re.IGNORECASE,
)
_SPARK_VAGUE_PHRASES = frozenset({
    "noted",
    "good to know",
    "interesting",
    "ok",
    "okay",
    "thanks",
    "sure",
    "got it",
    "makes sense",
})
_SPARK_SUMMARY_MARKERS = (
    "summary of the conversation",
    "summary of this session",
    "the user discussed",
    "this session covered",
    "overall the chat",
    "the conversation was about",
)


@dataclass(frozen=True)
class SparkValidationResult:
    ok: bool
    errors: list[str]
    spark: dict[str, object] | None = None


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split())


def normalize_lane(value: object) -> str:
    """Map portable/domain aliases to canonical SPARK_LANES values."""
    lane = str(value or "").strip().lower()
    return DOMAIN_ALIASES.get(lane, lane)


def _meaningful_char_count(text: str) -> int:
    return sum(1 for char in text if char.isalnum())


def _decode_secondary_lanes(raw: object) -> tuple[list[str] | None, list[str]]:
    """Parse secondary_lanes list or secondary_lanes_json string."""
    errors: list[str] = []
    if raw is None or raw == "":
        return [], errors
    if isinstance(raw, list):
        lanes = [normalize_lane(item) for item in raw]
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None, ["secondary_lanes_json must be valid JSON"]
        if not isinstance(parsed, list):
            return None, ["secondary_lanes_json must be a JSON array"]
        lanes = [normalize_lane(item) for item in parsed]
    else:
        return None, ["secondary_lanes must be a list or JSON array string"]

    normalized: list[str] = []
    for lane in lanes:
        if not lane:
            errors.append("secondary lane entries must be non-empty")
            continue
        if lane not in SPARK_LANES:
            errors.append(f"invalid secondary lane: {lane}")
            continue
        if lane in normalized:
            errors.append(f"duplicate secondary lane: {lane}")
            continue
        normalized.append(lane)
    if errors:
        return None, errors
    return normalized, errors


def _default_exposure_class(sensitivity: str) -> str:
    if sensitivity in {"sensitive", "high"}:
        return "private"
    return SPARK_EXPOSURE_CLASS_DEFAULT


def _apply_spark_field_defaults(spark: dict[str, object]) -> dict[str, object]:
    sensitivity = str(spark.get("sensitivity") or "normal")
    secondary_lanes = spark.get("secondary_lanes_json")
    if secondary_lanes is None and "secondary_lanes" in spark:
        lanes, _ = _decode_secondary_lanes(spark.get("secondary_lanes"))
        secondary_lanes = json.dumps(lanes or [], ensure_ascii=False)
    if secondary_lanes is None:
        secondary_lanes = SPARK_SECONDARY_LANES_DEFAULT
    return {
        **spark,
        "spark_type": str(spark.get("spark_type") or SPARK_TYPE_DEFAULT),
        "certainty": str(spark.get("certainty") or SPARK_CERTAINTY_DEFAULT),
        "secondary_lanes_json": str(secondary_lanes),
        "exposure_class": str(
            spark.get("exposure_class") or _default_exposure_class(sensitivity)
        ),
    }


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _content_has_prompt_wrapper_blob(content: str) -> bool:
    if _contains_marker(content, _SPARK_PROMPT_WRAPPER_MARKERS):
        return True
    return any(pattern.search(content) for pattern in _SPARK_PROMPT_WRAPPER_RES)


def _spark_json_blob_candidate(text: str) -> str | None:
    stripped = str(text or "").strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped
    if stripped.startswith("```"):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped, flags=re.IGNORECASE)
        if match:
            inner = match.group(1).strip()
            if inner.startswith("{") or inner.startswith("["):
                return inner
    return None


def _object_has_spark_schema_keys(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    keys = {str(key).strip().lower() for key in value.keys()}
    return len(keys & _SPARK_SCHEMA_KEYS) >= 2


def _content_looks_like_hallucinated_structure(content: str) -> bool:
    candidate = _spark_json_blob_candidate(content)
    if candidate is None:
        return False
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return False
    if isinstance(parsed, dict):
        return _object_has_spark_schema_keys(parsed)
    if isinstance(parsed, list) and parsed:
        dict_items = [item for item in parsed[:3] if isinstance(item, dict)]
        if not dict_items:
            return False
        return any(_object_has_spark_schema_keys(item) for item in dict_items)
    return False


def _spark_content_security_errors(content: str) -> list[str]:
    """T20 write-time content security gates (normalized content only)."""
    errors: list[str] = []
    if _contains_marker(content, _SPARK_INSTRUCTION_MARKERS):
        errors.append("content looks like instruction phrasing")
    if _content_has_prompt_wrapper_blob(content):
        errors.append("content contains prompt wrapper token")
    if _SPARK_SECRET_SK_RE.search(content):
        errors.append("content contains embedded secret pattern")
    if _SPARK_SECRET_BEARER_RE.search(content):
        errors.append("content contains embedded secret pattern")
    if _SPARK_MEMORY_DATA_BEGIN in content or _SPARK_MEMORY_DATA_END in content:
        errors.append("content contains memory delimiter smuggling")
    if _content_looks_like_hallucinated_structure(content):
        errors.append("content looks like hallucinated spark structure")
    return errors


def validate_spark(raw: object) -> SparkValidationResult:
    """Validate a candidate spark dict for V4 cognitive memory (T3)."""
    errors: list[str] = []

    if not isinstance(raw, dict):
        return SparkValidationResult(ok=False, errors=["spark must be an object"])

    content = _normalize_text(raw.get("content"))
    lane = normalize_lane(raw.get("lane"))
    why_keep = _normalize_text(raw.get("why_keep"))
    worth_reason = _normalize_text(raw.get("worth_reason"))
    confidence_raw = raw.get("confidence")
    sensitivity = str(raw.get("sensitivity", "normal") or "normal").strip().lower()
    spark_type = str(raw.get("spark_type") or "").strip().lower()
    certainty = str(raw.get("certainty") or "").strip().lower()
    exposure_class = str(raw.get("exposure_class") or "").strip().lower()

    if not content:
        errors.append("content is required")
    elif len(content) > SPARK_CONTENT_MAX_LEN:
        errors.append("content exceeds 300 characters")

    if not lane:
        errors.append("lane is required")
    elif lane not in SPARK_LANES:
        errors.append(f"invalid lane: {lane}")

    if not why_keep:
        errors.append("why_keep is required")

    if not worth_reason:
        errors.append("worth_reason is required")

    confidence: float | None = None
    if confidence_raw is None or confidence_raw == "":
        errors.append("confidence is required")
    else:
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            errors.append("confidence must be a number")
        else:
            if not math.isfinite(confidence):
                errors.append("confidence must be a finite number")
            elif confidence < 0.0 or confidence > 1.0:
                errors.append("confidence must be between 0 and 1")

    if sensitivity not in SPARK_SENSITIVITIES:
        errors.append(f"invalid sensitivity: {sensitivity}")

    if spark_type and spark_type not in SPARK_TYPES:
        errors.append(f"invalid spark_type: {spark_type}")
    if certainty and certainty not in SPARK_CERTAINTIES:
        errors.append(f"invalid certainty: {certainty}")
    if exposure_class and exposure_class not in SPARK_EXPOSURE_CLASSES:
        errors.append(f"invalid exposure_class: {exposure_class}")

    secondary_lanes: list[str] | None = []
    if "secondary_lanes" in raw or "secondary_lanes_json" in raw:
        raw_secondary = raw.get("secondary_lanes_json")
        if raw_secondary is None:
            raw_secondary = raw.get("secondary_lanes")
        parsed_lanes, lane_errors = _decode_secondary_lanes(raw_secondary)
        if lane_errors:
            errors.extend(lane_errors)
        elif parsed_lanes is not None:
            secondary_lanes = parsed_lanes
            if lane and lane in secondary_lanes:
                errors.append("secondary lanes must not include primary lane")

    if content:
        if content.lower() in _SPARK_VAGUE_PHRASES:
            errors.append("content is too vague")
        elif _contains_marker(content, _SPARK_SUMMARY_MARKERS):
            errors.append("content looks like a whole-input summary")
        errors.extend(_spark_content_security_errors(content))

    if errors:
        return SparkValidationResult(ok=False, errors=errors)

    assert confidence is not None
    spark_payload: dict[str, object] = {
        "content": content,
        "lane": lane,
        "why_keep": why_keep,
        "worth_reason": worth_reason,
        "confidence": confidence,
        "sensitivity": sensitivity,
    }
    if spark_type:
        spark_payload["spark_type"] = spark_type
    if certainty:
        spark_payload["certainty"] = certainty
    if exposure_class:
        spark_payload["exposure_class"] = exposure_class
    if secondary_lanes is not None and (
        "secondary_lanes" in raw or "secondary_lanes_json" in raw
    ):
        spark_payload["secondary_lanes_json"] = json.dumps(
            secondary_lanes,
            ensure_ascii=False,
        )
    return SparkValidationResult(
        ok=True,
        errors=[],
        spark=_apply_spark_field_defaults(spark_payload),
    )


_SPARKS_DDL = """
CREATE TABLE IF NOT EXISTS sparks (
    id INTEGER PRIMARY KEY,
    content TEXT NOT NULL,
    lane TEXT NOT NULL,
    spark_type TEXT NOT NULL DEFAULT 'observation',
    certainty TEXT NOT NULL DEFAULT 'tentative',
    secondary_lanes_json TEXT NOT NULL DEFAULT '[]',
    exposure_class TEXT NOT NULL DEFAULT 'public',
    sensitivity TEXT NOT NULL DEFAULT 'normal',
    tags_json TEXT,
    why_keep TEXT NOT NULL,
    worth_reason TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    base_confidence REAL NOT NULL DEFAULT 0.5,
    trust_state TEXT NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TEXT,
    source_refs_json TEXT,
    owner_id TEXT,
    content_encrypted INTEGER NOT NULL DEFAULT 0,
    lineage_json TEXT,
    source_memory_item_id INTEGER,
    project_id INTEGER,
    embedding_blob BLOB,
    embed_model TEXT,
    embed_dim INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_memory_item_id) REFERENCES memory_items(id),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
CREATE INDEX IF NOT EXISTS idx_sparks_project_trust_lane
    ON sparks(project_id, trust_state, lane);
CREATE INDEX IF NOT EXISTS idx_sparks_source_memory_item
    ON sparks(source_memory_item_id);
CREATE INDEX IF NOT EXISTS idx_sparks_trust_updated
    ON sparks(trust_state, updated_at);
CREATE TABLE IF NOT EXISTS spark_links (
    id INTEGER PRIMARY KEY,
    from_spark_id INTEGER NOT NULL,
    to_spark_id INTEGER NOT NULL,
    link_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_spark_id) REFERENCES sparks(id),
    FOREIGN KEY (to_spark_id) REFERENCES sparks(id)
);
CREATE INDEX IF NOT EXISTS idx_spark_links_from
    ON spark_links(from_spark_id);
CREATE INDEX IF NOT EXISTS idx_spark_links_to
    ON spark_links(to_spark_id);
CREATE INDEX IF NOT EXISTS idx_spark_links_from_to
    ON spark_links(from_spark_id, to_spark_id);
CREATE INDEX IF NOT EXISTS idx_spark_links_from_type
    ON spark_links(from_spark_id, link_type);
CREATE INDEX IF NOT EXISTS idx_spark_links_to_type
    ON spark_links(to_spark_id, link_type);
CREATE INDEX IF NOT EXISTS idx_spark_links_from_created
    ON spark_links(from_spark_id, created_at);
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY,
    content TEXT NOT NULL,
    lane TEXT NOT NULL,
    source_spark_ids_json TEXT,
    reasoning TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    trust_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_patterns_lane_trust
    ON patterns(lane, trust_state);
CREATE INDEX IF NOT EXISTS idx_patterns_trust_updated
    ON patterns(trust_state, updated_at);
CREATE INDEX IF NOT EXISTS idx_patterns_lane_trust_updated
    ON patterns(lane, trust_state, updated_at);
CREATE INDEX IF NOT EXISTS idx_patterns_sources
    ON patterns(source_spark_ids_json);
"""


def _spark_table_columns(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(sparks)").fetchall()
    return {str(row[1]) for row in rows}


def _migrate_v42_spark_columns(conn: sqlite3.Connection) -> None:
    """Additive V4.2 schema extensions (idempotent)."""
    columns = _spark_table_columns(conn)
    migrations = (
        ("spark_type", "TEXT NOT NULL DEFAULT 'observation'"),
        ("certainty", "TEXT NOT NULL DEFAULT 'tentative'"),
        ("secondary_lanes_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("exposure_class", "TEXT NOT NULL DEFAULT 'public'"),
    )
    for name, ddl in migrations:
        if name not in columns:
            conn.execute(f"ALTER TABLE sparks ADD COLUMN {name} {ddl}")
    conn.execute(
        """
        UPDATE sparks
        SET exposure_class = 'private'
        WHERE sensitivity IN ('sensitive', 'high')
          AND exposure_class = 'public'
        """
    )


def setup_spark_tables(conn: sqlite3.Connection) -> None:
    """Create sparks, spark_links, and patterns tables if missing."""
    conn.executescript(_SPARKS_DDL)
    _migrate_v42_spark_columns(conn)


def insert_spark(
    conn: sqlite3.Connection,
    spark: dict[str, object],
    *,
    source_memory_item_id: int,
    project_id: int | None,
    trust_state: str,
    lineage_json: dict[str, object] | None = None,
    embedding_blob: bytes | None = None,
    embed_model: str | None = None,
    embed_dim: int | None = None,
    source_refs_json: str | None = None,
) -> int:
    """Insert a validated spark row. Prefer upsert_spark_with_dedup() at ingest."""
    import crowley

    spark = _apply_spark_field_defaults(spark)
    now = crowley._now_iso()
    confidence = float(spark["confidence"])
    lineage_blob = json.dumps(lineage_json or {}, sort_keys=True, ensure_ascii=False)
    cur = conn.execute(
        """
        INSERT INTO sparks (
            content, lane, spark_type, certainty, secondary_lanes_json,
            exposure_class, why_keep, worth_reason, trust_state,
            confidence, base_confidence, sensitivity,
            source_memory_item_id, project_id, lineage_json,
            source_refs_json, embedding_blob, embed_model, embed_dim,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(spark["content"]),
            str(spark["lane"]),
            str(spark["spark_type"]),
            str(spark["certainty"]),
            str(spark["secondary_lanes_json"]),
            str(spark["exposure_class"]),
            str(spark["why_keep"]),
            str(spark["worth_reason"]),
            trust_state,
            confidence,
            confidence,
            str(spark.get("sensitivity") or "normal"),
            source_memory_item_id,
            project_id,
            lineage_blob,
            source_refs_json,
            embedding_blob,
            embed_model,
            embed_dim,
            now,
            now,
        ),
    )
    return int(cur.lastrowid)


def _normalize_spark_content(text: object) -> str:
    import crowley

    return crowley._normalize_text(str(text or ""))


def _spark_embed_model_name() -> str:
    import crowley

    provider = crowley._memory_embed_provider()
    if provider == "openai":
        return "text-embedding-3-small"
    return crowley.EMBED_MODEL_LOCAL


def _maybe_embed_spark(content: str) -> list[float] | None:
    import crowley

    return crowley.embed_text(content)


def _ensure_spark_vec_table(conn: sqlite3.Connection) -> bool:
    """Lazy-create spark_vec virtual table; cache readiness per connection id."""
    conn_id = id(conn)
    if conn_id in _spark_vec_ready_cache:
        return _spark_vec_ready_cache[conn_id]

    import crowley

    if not crowley._try_load_sqlite_vec(conn):
        _spark_vec_ready_cache[conn_id] = False
        return False
    row = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name = 'spark_vec'
        """
    ).fetchone()
    if row is None:
        try:
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE spark_vec USING vec0(
                    spark_id INTEGER PRIMARY KEY,
                    embedding float[{crowley.EMBED_DIM}]
                )
                """
            )
        except Exception:
            _spark_vec_ready_cache[conn_id] = False
            return False
    else:
        try:
            conn.execute("SELECT 1 FROM spark_vec LIMIT 0")
        except Exception:
            _spark_vec_ready_cache[conn_id] = False
            return False
    _spark_vec_ready_cache[conn_id] = True
    return True


def _write_spark_vec_row(
    conn: sqlite3.Connection, spark_id: int, embedding: list[float]
) -> None:
    import crowley

    try:
        vec_blob = crowley._vec_bind(embedding)
        conn.execute("DELETE FROM spark_vec WHERE spark_id = ?", (spark_id,))
        conn.execute(
            "INSERT INTO spark_vec(spark_id, embedding) VALUES (?, ?)",
            (spark_id, vec_blob),
        )
    except Exception:
        # embedding_blob is already stored; vec index is optional acceleration.
        return


def index_spark_embedding(
    conn: sqlite3.Connection,
    spark_id: int,
    embedding: list[float],
    model_name: str,
) -> bool:
    """Write embedding_blob and spark_vec row. Returns False if dim invalid."""
    import crowley

    if len(embedding) != crowley.EMBED_DIM:
        return False

    row = conn.execute(
        "SELECT embedding_blob, embed_model FROM sparks WHERE id = ?",
        (spark_id,),
    ).fetchone()
    if row is None:
        return False

    blob = crowley._pack_embedding(embedding)
    touch_updated_at = (
        row["embedding_blob"] is None
        or str(row["embed_model"] or "") != model_name
    )
    if touch_updated_at:
        conn.execute(
            """
            UPDATE sparks
            SET embed_model = ?, embed_dim = ?, embedding_blob = ?, updated_at = ?
            WHERE id = ?
            """,
            (model_name, crowley.EMBED_DIM, blob, crowley._now_iso(), spark_id),
        )
    else:
        conn.execute(
            """
            UPDATE sparks
            SET embed_model = ?, embed_dim = ?, embedding_blob = ?
            WHERE id = ?
            """,
            (model_name, crowley.EMBED_DIM, blob, spark_id),
        )

    if not _ensure_spark_vec_table(conn):
        return True

    _write_spark_vec_row(conn, spark_id, embedding)
    return True


def embed_and_index_spark(
    conn: sqlite3.Connection,
    spark_id: int,
    content: str,
    *,
    vector: list[float] | None = None,
) -> bool:
    """Embed (or reuse vector) and index. Returns False when provider off or invalid."""
    import crowley

    resolved = vector if vector is not None else crowley.embed_text(content)
    if not resolved or len(resolved) != crowley.EMBED_DIM:
        return False
    return index_spark_embedding(conn, spark_id, resolved, _spark_embed_model_name())


def backfill_spark_embeddings(conn: sqlite3.Connection, limit: int = 200) -> int:
    """Embed sparks lacking embedding_blob. Returns count embedded."""
    import crowley

    if crowley._memory_embed_provider() == "off":
        return 0
    _ensure_spark_vec_table(conn)
    rows = conn.execute(
        """
        SELECT id, content
        FROM sparks
        WHERE trust_state != 'rejected' AND embedding_blob IS NULL
        ORDER BY created_at ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    embedded = 0
    for row in rows:
        if embed_and_index_spark(conn, int(row["id"]), str(row["content"])):
            embedded += 1
    return embedded


def _find_dedup_candidate(
    conn: sqlite3.Connection,
    *,
    lane: str,
    project_id: int | None,
    normalized_content: str,
    vector: list[float] | None,
) -> tuple[sqlite3.Row | None, float | None]:
    """Return best same-lane keeper and similarity (content-equal → 1.0)."""
    import crowley

    rows = conn.execute(
        """
        SELECT id, content, confidence, base_confidence, embedding_blob
        FROM sparks
        WHERE lane = ? AND trust_state != 'rejected'
          AND (
            (project_id IS NULL AND ? IS NULL)
            OR (project_id = ?)
          )
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (lane, project_id, project_id, MAX_DEDUP_CANDIDATES),
    ).fetchall()

    best_row: sqlite3.Row | None = None
    best_sim: float | None = None
    for row in rows:
        keeper_norm = _normalize_spark_content(row["content"])
        if keeper_norm == normalized_content:
            return row, 1.0
        if vector is None:
            continue
        keeper_vec = crowley._unpack_embedding(row["embedding_blob"])
        if keeper_vec is None:
            continue
        sim = crowley._cosine_similarity(vector, keeper_vec)
        if best_sim is None or sim > best_sim:
            best_sim = sim
            best_row = row
    return best_row, best_sim


def _parse_source_refs(raw: str | None) -> list[dict[str, object]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _merge_spark_ref(
    conn: sqlite3.Connection,
    keeper_id: int,
    *,
    source_memory_item_id: int,
    new_confidence: float,
    lineage_json: dict[str, object] | None,
) -> None:
    """Merge incoming evidence into keeper — append refs and boost confidence."""
    import crowley

    row = conn.execute(
        """
        SELECT confidence, base_confidence, source_refs_json
        FROM sparks WHERE id = ?
        """,
        (keeper_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"keeper spark not found: {keeper_id}")

    now = crowley._now_iso()
    refs = _parse_source_refs(row["source_refs_json"])
    ref_entry: dict[str, object] = {
        "source_memory_item_id": source_memory_item_id,
        "memory_item_id": source_memory_item_id,
        "merged_at": now,
        "dedup_action": "merged",
    }
    if lineage_json:
        ref_entry.update(lineage_json)
    refs.append(ref_entry)

    existing_conf = float(row["confidence"])
    existing_base = float(row["base_confidence"])
    merged_conf = min(1.0, existing_conf + SPARK_MERGE_CONFIDENCE_BOOST)
    merged_base = max(existing_base, new_confidence)

    conn.execute(
        """
        UPDATE sparks
        SET source_refs_json = ?, confidence = ?, base_confidence = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            json.dumps(refs, sort_keys=True, ensure_ascii=False),
            merged_conf,
            merged_base,
            now,
            keeper_id,
        ),
    )


def _upsert_reinforces_link(
    conn: sqlite3.Connection,
    from_spark_id: int,
    to_spark_id: int,
    *,
    confidence: float,
    similarity: float | None = None,
) -> None:
    """Thin wrapper for tests — delegates to spark_graph.create_spark_link."""
    import spark_graph

    result = spark_graph.create_spark_link(
        conn,
        from_spark_id,
        to_spark_id,
        SPARK_LINK_TYPE_REINFORCES,
        confidence=confidence,
        similarity=similarity if similarity is not None else confidence,
    )
    if not result.ok:
        raise ValueError("; ".join(result.errors))


def _lineage_with_dedup_action(
    lineage_json: dict[str, object] | None,
    *,
    action: str,
    source_memory_item_id: int,
) -> dict[str, object]:
    enriched = dict(lineage_json or {})
    enriched.setdefault("dedup_action", action)
    enriched.setdefault("memory_item_id", source_memory_item_id)
    return enriched


def upsert_spark_with_dedup(
    conn: sqlite3.Connection,
    spark: dict[str, object],
    *,
    source_memory_item_id: int,
    project_id: int | None,
    trust_state: str,
    lineage_json: dict[str, object] | None = None,
) -> SparkUpsertResult:
    """Dedup before INSERT: merge, reinforces link, or distinct insert."""
    normalized = _normalize_spark_content(spark["content"])
    lane = str(spark["lane"])
    incoming_confidence = float(spark["confidence"])
    vector = _maybe_embed_spark(normalized)

    keeper, sim = _find_dedup_candidate(
        conn,
        lane=lane,
        project_id=project_id,
        normalized_content=normalized,
        vector=vector,
    )

    if keeper is not None:
        keeper_id = int(keeper["id"])
        if sim == 1.0 or (sim is not None and sim >= SPARK_DEDUP_MERGE_SIM):
            _merge_spark_ref(
                conn,
                keeper_id,
                source_memory_item_id=source_memory_item_id,
                new_confidence=incoming_confidence,
                lineage_json=lineage_json,
            )
            return SparkUpsertResult(
                action="merged",
                spark_id=keeper_id,
                keeper_id=keeper_id,
                similarity=sim,
            )
        if sim is not None and sim > SPARK_DEDUP_LINK_SIM:
            new_id = insert_spark(
                conn,
                spark,
                source_memory_item_id=source_memory_item_id,
                project_id=project_id,
                trust_state=trust_state,
                lineage_json=_lineage_with_dedup_action(
                    lineage_json,
                    action="linked",
                    source_memory_item_id=source_memory_item_id,
                ),
            )
            if vector is not None:
                embed_and_index_spark(conn, new_id, normalized, vector=vector)
            import spark_graph

            link_result = spark_graph.create_spark_link(
                conn,
                new_id,
                keeper_id,
                SPARK_LINK_TYPE_REINFORCES,
                confidence=sim,
                similarity=sim,
            )
            if not link_result.ok:
                raise ValueError("; ".join(link_result.errors))
            return SparkUpsertResult(
                action="linked",
                spark_id=new_id,
                keeper_id=keeper_id,
                similarity=sim,
            )

    new_id = insert_spark(
        conn,
        spark,
        source_memory_item_id=source_memory_item_id,
        project_id=project_id,
        trust_state=trust_state,
        lineage_json=_lineage_with_dedup_action(
            lineage_json,
            action="inserted",
            source_memory_item_id=source_memory_item_id,
        ),
    )
    if vector is not None:
        embed_and_index_spark(conn, new_id, normalized, vector=vector)
    return SparkUpsertResult(action="inserted", spark_id=new_id)
