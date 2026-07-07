"""V4 T11/T12 — deterministic spark pattern creation and safety gates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

PATTERN_MIN_SPARKS = 3
PATTERN_MAX_CANDIDATES = 50
PATTERN_MIN_AVG_CONFIDENCE = 0.6
PATTERN_MIN_SEMANTIC_SIM = 0.85
PATTERN_TRUST_STATE_CANDIDATE = "candidate"
PATTERN_ACTIVE_TRUST_STATE = "active"
PATTERN_FORBIDDEN_TRUST_STATES = frozenset({"canon", "canonical"})
PATTERN_RATE_LIMIT_PER_HOUR = 5
PATTERN_RATE_LIMIT_WINDOW_HOURS = 1
PATTERN_LIFECYCLE_BOOST = 0.05


@dataclass(frozen=True)
class PatternCreationResult:
    ok: bool
    action: Literal["created", "existing", "promoted", "rejected"] = "rejected"
    pattern_id: int | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _PatternCandidate:
    rows: list[sqlite3.Row]
    lane: str
    source_spark_ids_json: str
    avg_conf: float
    confidence: float
    min_sim: float


class _PatternSafetyRollback(Exception):
    def __init__(self, result: PatternCreationResult) -> None:
        super().__init__("pattern safety rollback")
        self.result = result


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _canonical_source_json(spark_ids: list[int]) -> str:
    return json.dumps(spark_ids, separators=(",", ":"), sort_keys=False)


def _load_candidate_sparks(
    conn: sqlite3.Connection,
    spark_ids: list[int],
) -> list[sqlite3.Row]:
    if not spark_ids:
        return []
    placeholders = ", ".join("?" for _ in spark_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM sparks
        WHERE id IN ({placeholders})
          AND trust_state != 'rejected'
        """,
        spark_ids,
    ).fetchall()
    by_id = {int(row["id"]): row for row in rows}
    return [by_id[spark_id] for spark_id in spark_ids if spark_id in by_id]


def _same_lane(rows: list[sqlite3.Row]) -> str | None:
    lanes = {str(row["lane"]) for row in rows}
    if len(lanes) != 1:
        return None
    return next(iter(lanes))


def _pairwise_similarities(rows: list[sqlite3.Row]) -> list[float] | None:
    import crowley

    vectors: list[list[float]] = []
    for row in rows:
        vector = crowley._unpack_embedding(row["embedding_blob"])
        if not vector:
            return None
        vectors.append(vector)

    sims: list[float] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            sims.append(_clamp01(crowley._cosine_similarity(vectors[i], vectors[j])))
    return sims


def _pattern_content(lane: str, rows: list[sqlite3.Row]) -> str:
    snippets = sorted(str(row["content"])[:60] for row in rows)[:3]
    return f"{lane}: " + "; ".join(snippets)


def _existing_pattern_id(
    conn: sqlite3.Connection,
    source_spark_ids_json: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT id
        FROM patterns
        WHERE source_spark_ids_json = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (source_spark_ids_json,),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"])


def _build_pattern_candidate(
    conn: sqlite3.Connection,
    candidate_spark_ids: list[int],
) -> _PatternCandidate | PatternCreationResult:
    candidate_ids = sorted({int(spark_id) for spark_id in candidate_spark_ids})[
        :PATTERN_MAX_CANDIDATES
    ]
    rows = _load_candidate_sparks(conn, candidate_ids)
    if len(rows) < PATTERN_MIN_SPARKS:
        return PatternCreationResult(ok=False, errors=["not enough valid sparks"])

    lane = _same_lane(rows)
    if lane is None:
        return PatternCreationResult(ok=False, errors=["sparks must share one lane"])

    confidences = [_clamp01(float(row["confidence"])) for row in rows]
    avg_conf = round(sum(confidences) / len(confidences), 6)
    confidence = _clamp01(avg_conf)
    if confidence < PATTERN_MIN_AVG_CONFIDENCE:
        return PatternCreationResult(
            ok=False,
            errors=["average confidence below threshold"],
        )

    pairwise_sims = _pairwise_similarities(rows)
    if pairwise_sims is None:
        return PatternCreationResult(ok=False, errors=["spark embeddings required"])
    min_sim = min(pairwise_sims) if pairwise_sims else 0.0
    if min_sim < PATTERN_MIN_SEMANTIC_SIM:
        return PatternCreationResult(
            ok=False,
            errors=["semantic similarity below threshold"],
        )

    source_ids = [int(row["id"]) for row in rows]
    return _PatternCandidate(
        rows=rows,
        lane=lane,
        source_spark_ids_json=_canonical_source_json(source_ids),
        avg_conf=avg_conf,
        confidence=confidence,
        min_sim=min_sim,
    )


def _insert_pattern_candidate(
    conn: sqlite3.Connection,
    candidate: _PatternCandidate,
) -> int:
    import crowley

    now = crowley._now_iso()
    reasoning = (
        f"{len(candidate.rows)} sparks, "
        f"avg_conf={candidate.avg_conf:.2f}, "
        f"min_sim={candidate.min_sim:.2f}"
    )
    cur = conn.execute(
        """
        INSERT INTO patterns (
            content, lane, source_spark_ids_json, reasoning,
            confidence, trust_state, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _pattern_content(candidate.lane, candidate.rows),
            candidate.lane,
            candidate.source_spark_ids_json,
            reasoning,
            candidate.confidence,
            PATTERN_TRUST_STATE_CANDIDATE,
            now,
            now,
        ),
    )
    return int(cur.lastrowid)


def create_pattern_from_sparks(
    conn: sqlite3.Connection,
    candidate_spark_ids: list[int],
) -> PatternCreationResult:
    """Create one pattern from a bounded explicit spark candidate set."""
    candidate = _build_pattern_candidate(conn, candidate_spark_ids)
    if isinstance(candidate, PatternCreationResult):
        return candidate

    existing_id = _existing_pattern_id(conn, candidate.source_spark_ids_json)
    if existing_id is not None:
        return PatternCreationResult(ok=True, action="existing", pattern_id=existing_id)

    pattern_id = _insert_pattern_candidate(conn, candidate)
    return PatternCreationResult(
        ok=True,
        action="created",
        pattern_id=pattern_id,
    )


def _recent_pattern_count(conn: sqlite3.Connection) -> int:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=PATTERN_RATE_LIMIT_WINDOW_HOURS)
    ).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM patterns
        WHERE datetime(created_at) >= datetime(?)
        """,
        (cutoff,),
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def promote_pattern_if_safe(
    conn: sqlite3.Connection,
    pattern_id: int,
    *,
    target_state: str = PATTERN_ACTIVE_TRUST_STATE,
) -> PatternCreationResult:
    """Promote a pattern only to active; canon/canonical are never allowed."""
    import crowley

    if target_state in PATTERN_FORBIDDEN_TRUST_STATES:
        return PatternCreationResult(ok=False, errors=["canon promotion blocked"])
    if target_state != PATTERN_ACTIVE_TRUST_STATE:
        return PatternCreationResult(ok=False, errors=["target_state must be active"])
    row = conn.execute(
        "SELECT id, trust_state FROM patterns WHERE id = ?",
        (pattern_id,),
    ).fetchone()
    if row is None:
        return PatternCreationResult(ok=False, errors=["pattern not found"])

    trust_state = str(row["trust_state"])
    if trust_state == PATTERN_ACTIVE_TRUST_STATE:
        return PatternCreationResult(
            ok=True,
            action="existing",
            pattern_id=pattern_id,
        )
    if trust_state != PATTERN_TRUST_STATE_CANDIDATE:
        return PatternCreationResult(ok=False, errors=["pattern state cannot be promoted"])

    conn.execute(
        """
        UPDATE patterns
        SET trust_state = ?, updated_at = ?
        WHERE id = ?
        """,
        (PATTERN_ACTIVE_TRUST_STATE, crowley._now_iso(), pattern_id),
    )
    return PatternCreationResult(ok=True, action="promoted", pattern_id=pattern_id)


def _create_pattern_with_safety_locked(
    conn: sqlite3.Connection,
    candidate_spark_ids: list[int],
) -> PatternCreationResult:
    candidate = _build_pattern_candidate(conn, candidate_spark_ids)
    if isinstance(candidate, PatternCreationResult):
        return candidate

    existing_id = _existing_pattern_id(conn, candidate.source_spark_ids_json)
    if existing_id is not None:
        return promote_pattern_if_safe(conn, existing_id)

    if _recent_pattern_count(conn) >= PATTERN_RATE_LIMIT_PER_HOUR:
        return PatternCreationResult(ok=False, errors=["pattern rate limit reached"])

    pattern_id = _insert_pattern_candidate(conn, candidate)
    promoted = promote_pattern_if_safe(conn, pattern_id)
    if not promoted.ok:
        raise _PatternSafetyRollback(promoted)
    return PatternCreationResult(ok=True, action="created", pattern_id=pattern_id)


def create_pattern_with_safety(
    conn: sqlite3.Connection,
    candidate_spark_ids: list[int],
) -> PatternCreationResult:
    """Atomically create a pattern and promote only to active."""
    if conn.in_transaction:
        savepoint = f"pattern_safety_{id(conn)}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            result = _create_pattern_with_safety_locked(conn, candidate_spark_ids)
        except _PatternSafetyRollback as exc:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            return exc.result
        except Exception:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            raise
        conn.execute(f"RELEASE {savepoint}")
        return result

    conn.execute("BEGIN IMMEDIATE")
    try:
        result = _create_pattern_with_safety_locked(conn, candidate_spark_ids)
    except _PatternSafetyRollback as exc:
        conn.rollback()
        return exc.result
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return result


def pattern_lifecycle_boost() -> float:
    return PATTERN_LIFECYCLE_BOOST
