"""V4 T13 — deterministic cognitive context orchestration."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import spark_graph
import spark_retrieval
import sparks

COGNITIVE_CONTEXT_DEFAULT_LIMIT = 12
COGNITIVE_CONTEXT_SUPPORTING_LIMIT = 20
COGNITIVE_CONTEXT_PATTERN_LIMIT = 5
COGNITIVE_CONTEXT_SCORE_BASIS = (
    "0.40 semantic + 0.25 confidence + 0.15 recency + 0.20 graph_reinforcement"
)


def _clamp_limit(value: int, *, default: int = COGNITIVE_CONTEXT_DEFAULT_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 50))


def _normalize_lanes(lanes: object | None) -> frozenset[str] | None:
    if lanes is None:
        return None
    if isinstance(lanes, str):
        raw = [part.strip() for part in lanes.split(",")]
    else:
        raw = [str(part).strip() for part in lanes]  # type: ignore[operator]
    normalized = frozenset(part for part in raw if part)
    invalid = sorted(lane for lane in normalized if lane not in sparks.SPARK_LANES)
    if invalid:
        raise ValueError(f"invalid lane: {invalid[0]}")
    return normalized or None


def _resolve_project_id(conn: sqlite3.Connection, project: str | None) -> int | None:
    if project is None or not str(project).strip():
        row = conn.execute(
            "SELECT id FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row is not None else None
    row = conn.execute(
        "SELECT id FROM projects WHERE LOWER(slug) = LOWER(?) LIMIT 1",
        (str(project).strip(),),
    ).fetchone()
    if row is None:
        raise ValueError(f"project not found: {project}")
    return int(row["id"])


def _spark_payload(result: spark_retrieval.SparkRetrievalResult) -> dict[str, Any]:
    return {
        "spark_id": result.spark_id,
        "content": result.content,
        "lane": result.lane,
        "trust_state": result.trust_state,
        "confidence": result.confidence,
        "score": result.score,
        "score_breakdown": dict(result.score_breakdown),
    }


def _parse_pattern_source_ids(raw: object) -> set[int]:
    try:
        decoded = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(decoded, list):
        return set()
    ids: set[int] = set()
    for item in decoded:
        try:
            ids.add(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _active_patterns_for_context(
    conn: sqlite3.Connection,
    context_spark_ids: set[int],
) -> list[dict[str, Any]]:
    if not context_spark_ids:
        return []
    rows = conn.execute(
        """
        SELECT id, content, lane, source_spark_ids_json, reasoning,
               confidence, trust_state, created_at, updated_at
        FROM patterns
        WHERE trust_state = 'active'
        ORDER BY id ASC
        """
    ).fetchall()
    attached: list[dict[str, Any]] = []
    for row in rows:
        source_ids = _parse_pattern_source_ids(row["source_spark_ids_json"])
        if not source_ids.intersection(context_spark_ids):
            continue
        attached.append(
            {
                "pattern_id": int(row["id"]),
                "content": str(row["content"]),
                "lane": str(row["lane"]),
                "source_spark_ids": sorted(source_ids),
                "reasoning": str(row["reasoning"]),
                "confidence": float(row["confidence"]),
                "trust_state": str(row["trust_state"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
            }
        )
        if len(attached) >= COGNITIVE_CONTEXT_PATTERN_LIMIT:
            break
    return attached


def _context_confidence(core: list[spark_retrieval.SparkRetrievalResult]) -> float:
    if not core:
        return 0.0
    return round(sum(item.score for item in core) / len(core), 4)


def build_cognitive_context(
    query: str,
    *,
    lanes: object | None = None,
    limit: int = COGNITIVE_CONTEXT_DEFAULT_LIMIT,
    supporting_limit: int = COGNITIVE_CONTEXT_SUPPORTING_LIMIT,
    project: str | None = None,
    project_id: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Build read-only cognitive context from ranked sparks and active patterns."""
    import crowley

    core_limit = _clamp_limit(limit)
    support_limit = max(0, min(int(supporting_limit), COGNITIVE_CONTEXT_SUPPORTING_LIMIT))
    lane_filter = _normalize_lanes(lanes)
    owns_conn = conn is None
    db = conn or crowley.connect_db()
    try:
        resolved_project_id = project_id
        if resolved_project_id is None:
            resolved_project_id = _resolve_project_id(db, project)
        ranked = spark_retrieval.retrieve_sparks(
            str(query or ""),
            limit=core_limit + support_limit,
            project_id=resolved_project_id,
            lanes=lane_filter,
            conn=db,
            bump_access=True,
            expand_hops=spark_graph.SPARK_EXPANSION_HOPS_MEDIUM,
        )
        core = ranked[:core_limit]
        supporting = ranked[core_limit : core_limit + support_limit]
        context_ids = {int(item.spark_id) for item in [*core, *supporting]}
        attached_patterns = _active_patterns_for_context(db, context_ids)
        return {
            "core_sparks": [_spark_payload(item) for item in core],
            "supporting_sparks": [_spark_payload(item) for item in supporting],
            "patterns": attached_patterns,
            "confidence": _context_confidence(core),
            "trace": {
                "lanes_used": sorted(lane_filter) if lane_filter else [],
                "retrieved_count": len(ranked),
                "core_count": len(core),
                "supporting_count": len(supporting),
                "pattern_count": len(attached_patterns),
                "expand_hops": spark_graph.SPARK_EXPANSION_HOPS_MEDIUM,
                "selection_reason": "ranked retrieval split into core and supporting sparks",
                "score_basis": COGNITIVE_CONTEXT_SCORE_BASIS,
            },
        }
    finally:
        if owns_conn:
            db.close()
