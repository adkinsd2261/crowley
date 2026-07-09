"""V4 T13/T14 — deterministic cognitive context orchestration."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import context_resolution
import spark_graph
import spark_retrieval
import spark_sanitize
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


def _parse_json_object(raw: object) -> dict[str, Any]:
    try:
        decoded = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _parse_json_list(raw: object) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


def _spark_lineage_trace(
    conn: sqlite3.Connection,
    spark_ids: list[int],
) -> list[dict[str, Any]]:
    if not spark_ids:
        return []
    placeholders = ", ".join("?" for _ in spark_ids)
    rows = conn.execute(
        f"""
        SELECT id, source_memory_item_id, lineage_json, source_refs_json
        FROM sparks
        WHERE id IN ({placeholders})
        """,
        spark_ids,
    ).fetchall()
    by_id = {int(row["id"]): row for row in rows}
    lineage: list[dict[str, Any]] = []
    for spark_id in spark_ids:
        row = by_id.get(int(spark_id))
        if row is None:
            continue
        lineage.append(
            {
                "spark_id": int(row["id"]),
                "source_memory_item_id": (
                    int(row["source_memory_item_id"])
                    if row["source_memory_item_id"] is not None
                    else None
                ),
                "lineage": _parse_json_object(row["lineage_json"]),
                "source_refs": _parse_json_list(row["source_refs_json"]),
            }
        )
    return lineage


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


def _memory_fallback_items(
    query: str,
    *,
    project_id: int | None,
    limit: int,
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    import crowley

    memories = crowley.retrieve_memories(
        str(query or ""),
        limit=limit,
        project_id=project_id,
        conn=conn,
    )
    fallback: list[dict[str, Any]] = []
    for memory in memories:
        fallback.append(
            {
                "memory_id": int(memory["id"]),
                "content": str(memory.get("content") or ""),
                "memory_type": str(memory.get("memory_type") or "event"),
                "score": float(memory.get("score") or 0.0),
                "source": "memory_items_fallback",
            }
        )
    return fallback


def build_cognitive_context(
    query: str,
    *,
    lanes: object | None = None,
    limit: int = COGNITIVE_CONTEXT_DEFAULT_LIMIT,
    supporting_limit: int = COGNITIVE_CONTEXT_SUPPORTING_LIMIT,
    project: str | None = None,
    project_id: int | None = None,
    conn: sqlite3.Connection | None = None,
    depth: str = "medium",
    debug: bool = False,
) -> dict[str, Any]:
    """Build read-only cognitive context from ranked sparks and active patterns."""
    import crowley

    resolved_depth = context_resolution.normalize_depth(depth, default="medium")
    assert resolved_depth is not None
    depth_limits = context_resolution.COGNITIVE_DEPTH_LIMITS[resolved_depth]
    core_limit = min(_clamp_limit(limit), int(depth_limits["core"]))
    support_limit = min(
        max(0, int(supporting_limit)),
        int(depth_limits["supporting"]),
    )
    pattern_limit = int(depth_limits["patterns"])
    lane_filter = _normalize_lanes(lanes)
    owns_conn = conn is None
    db = conn or crowley.connect_db()
    try:
        resolved_project_id = project_id
        if resolved_project_id is None:
            resolved_project_id = _resolve_project_id(db, project)
        active_spark_count = context_resolution.count_active_sparks(
            db,
            project_id=resolved_project_id,
        )
        ranked = spark_retrieval.retrieve_sparks(
            str(query or ""),
            limit=core_limit + support_limit,
            project_id=resolved_project_id,
            lanes=lane_filter,
            conn=db,
            bump_access=True,
            expand_hops=spark_graph.SPARK_EXPANSION_HOPS_MEDIUM,
            depth=resolved_depth,
        )
        core = ranked[:core_limit]
        supporting = ranked[core_limit : core_limit + support_limit]
        fallback_used = active_spark_count < context_resolution.COLD_START_ACTIVE_SPARK_THRESHOLD
        memory_fallback: list[dict[str, Any]] = []
        if fallback_used and support_limit > 0:
            memory_fallback = _memory_fallback_items(
                query,
                project_id=resolved_project_id,
                limit=support_limit,
                conn=db,
            )
        context_ids = {int(item.spark_id) for item in [*core, *supporting]}
        context_id_order = [int(item.spark_id) for item in [*core, *supporting]]
        attached_patterns = _active_patterns_for_context(db, context_ids)
        attached_patterns = attached_patterns[:pattern_limit]
        trace: dict[str, Any] = {
            "depth": resolved_depth,
            "lanes_used": sorted(lane_filter) if lane_filter else [],
            "retrieved_count": len(ranked),
            "core_count": len(core),
            "supporting_count": len(supporting),
            "pattern_count": len(attached_patterns),
            "expand_hops": spark_graph.SPARK_EXPANSION_HOPS_MEDIUM,
            "selection_reason": "ranked retrieval split into core and supporting sparks",
            "score_basis": COGNITIVE_CONTEXT_SCORE_BASIS,
            "lineage": _spark_lineage_trace(db, context_id_order),
            "fallback_used": fallback_used,
            "active_spark_count": active_spark_count,
        }
        if fallback_used:
            trace["selection_reason"] = (
                f"{trace['selection_reason']}; memory_items fallback "
                f"(active sparks < {context_resolution.COLD_START_ACTIVE_SPARK_THRESHOLD})"
            )
        payload: dict[str, Any] = {
            "core_sparks": [_spark_payload(item) for item in core],
            "supporting_sparks": [_spark_payload(item) for item in supporting],
            "patterns": attached_patterns,
            "confidence": _context_confidence(core),
            "depth": resolved_depth,
            "trace": trace,
        }
        if memory_fallback:
            payload["memory_fallback"] = memory_fallback
        if debug:
            payload["debug"] = {"spark_ranked_count": len(ranked)}
        return spark_sanitize.sanitize_cognitive_context_payload(payload)
    finally:
        if owns_conn:
            db.close()
