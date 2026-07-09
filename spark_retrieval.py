"""V4 T8 — spark retrieval and canonical scoring."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import spark_graph
import spark_lifecycle
import spark_security
import sparks

W_SPARK_SEMANTIC = 0.40
W_SPARK_CONFIDENCE = 0.25
W_SPARK_RECENCY = 0.15
W_SPARK_GRAPH = 0.20

CERTAINTY_SCORE_MULTIPLIERS = {
    "confirmed": 1.00,
    "exploratory": 0.92,
    "tentative": 0.85,
}

SPARK_RETRIEVE_VECTOR_CANDIDATES = 50
SPARK_RETRIEVE_KEYWORD_CANDIDATES = 50
SPARK_DEFAULT_LIMIT = 12
SPARK_KEYWORD_SEMANTIC_FLOOR = 0.05


@dataclass(frozen=True)
class SparkRetrievalResult:
    spark_id: int
    content: str
    lane: str
    trust_state: str
    confidence: float
    score: float
    score_breakdown: dict[str, float]
    sensitivity: str = "normal"


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _project_clause(project_id: int | None) -> tuple[str, list[object]]:
    return (
        "AND ((project_id IS NULL AND ? IS NULL) OR (project_id = ?))",
        [project_id, project_id],
    )


def _lane_clause(lanes: frozenset[str] | None) -> tuple[str, list[object]]:
    if not lanes:
        return "", []
    placeholders = ", ".join("?" for _ in lanes)
    return f"AND lane IN ({placeholders})", list(lanes)


def _spark_semantic_candidate_scores(
    conn: sqlite3.Connection,
    query_embedding: list[float] | None,
    limit: int,
    *,
    project_id: int | None,
    lanes: frozenset[str] | None,
) -> dict[int, float]:
    import crowley

    if not query_embedding:
        return {}

    project_sql, project_params = _project_clause(project_id)
    lane_sql, lane_params = _lane_clause(lanes)

    if sparks._ensure_spark_vec_table(conn):
        try:
            import crowley

            rows = conn.execute(
                f"""
                SELECT spark_id, distance
                FROM spark_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
                """,
                (crowley._vec_bind(query_embedding), limit),
            ).fetchall()
            if rows:
                eligible: dict[int, float] = {}
                for row in rows:
                    spark_id = int(row["spark_id"])
                    spark_row = _load_spark_row(
                        conn,
                        spark_id,
                        project_id=project_id,
                        lanes=lanes,
                    )
                    if spark_row is None:
                        continue
                    semantic = _clamp01(1.0 - float(row["distance"]))
                    eligible[spark_id] = semantic
                if eligible:
                    return dict(
                        sorted(eligible.items(), key=lambda item: item[1], reverse=True)[
                            :limit
                        ]
                    )
        except Exception:
            pass

    rows = conn.execute(
        f"""
        SELECT id, embedding_blob
        FROM sparks
        WHERE trust_state != 'rejected' AND embedding_blob IS NOT NULL
          {project_sql}
          {lane_sql}
        """,
        project_params + lane_params,
    ).fetchall()
    scored: list[tuple[int, float]] = []
    for row in rows:
        vector = crowley._unpack_embedding(row["embedding_blob"])
        if not vector:
            continue
        scored.append(
            (int(row["id"]), _clamp01(crowley._cosine_similarity(query_embedding, vector)))
        )
    scored.sort(key=lambda item: item[1], reverse=True)
    return dict(scored[:limit])


def _spark_keyword_candidate_scores(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    *,
    project_id: int | None,
    lanes: frozenset[str] | None,
) -> dict[int, float]:
    import crowley

    tokens = crowley._tokenize(query)
    if not tokens:
        return {}

    project_sql, project_params = _project_clause(project_id)
    lane_sql, lane_params = _lane_clause(lanes)
    rows = conn.execute(
        f"""
        SELECT id, content
        FROM sparks
        WHERE trust_state != 'rejected'
          {project_sql}
          {lane_sql}
        """,
        project_params + lane_params,
    ).fetchall()
    scored: list[tuple[int, float, int]] = []
    for row in rows:
        kw = crowley._keyword_score_for_item(tokens, str(row["content"]), None)
        if kw <= 0.0:
            continue
        scored.append((int(row["id"]), kw, int(row["id"])))
    scored.sort(key=lambda item: (item[1], -item[2]), reverse=True)
    return {item[0]: item[1] for item in scored[:limit]}


def _pinned_spark_ids(
    conn: sqlite3.Connection,
    *,
    project_id: int | None,
    lanes: frozenset[str] | None,
) -> set[int]:
    project_sql, project_params = _project_clause(project_id)
    lane_sql, lane_params = _lane_clause(lanes)
    rows = conn.execute(
        f"""
        SELECT id FROM sparks
        WHERE trust_state = 'pinned'
          {project_sql}
          {lane_sql}
        """,
        project_params + lane_params,
    ).fetchall()
    return {int(row["id"]) for row in rows}


def _load_spark_row(
    conn: sqlite3.Connection,
    spark_id: int,
    *,
    project_id: int | None,
    lanes: frozenset[str] | None,
) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
    if row is None:
        return None
    if str(row["trust_state"]) == "rejected":
        return None
    if lanes is not None and str(row["lane"]) not in lanes:
        return None
    row_project = row["project_id"]
    if project_id is None:
        if row_project is not None:
            return None
    elif row_project is not None and int(row_project) != project_id:
        return None
    return row


def _spark_recency_score(row: sqlite3.Row) -> float:
    import crowley

    ts = row["last_accessed_at"] or row["updated_at"] or row["created_at"]
    return _clamp01(crowley._recency_score(str(ts)))


def _spark_graph_reinforcement(conn: sqlite3.Connection, spark_id: int) -> float:
    row = conn.execute(
        """
        SELECT MAX(confidence) AS max_conf
        FROM spark_links
        WHERE to_spark_id = ? AND link_type = ?
        """,
        (spark_id, sparks.SPARK_LINK_TYPE_REINFORCES),
    ).fetchone()
    if row is None:
        return 0.0
    max_conf = row["max_conf"]
    if max_conf is None:
        return 0.0
    return _clamp01(float(max_conf))


def _certainty_multiplier(row: sqlite3.Row) -> float:
    certainty = str(row["certainty"] or "tentative")
    return CERTAINTY_SCORE_MULTIPLIERS.get(certainty, 0.85)


def _score_spark(
    row: sqlite3.Row,
    *,
    semantic: float,
    graph: float,
    live_confidence: float,
) -> tuple[float, dict[str, float]]:
    confidence = _clamp01(live_confidence)
    recency = _spark_recency_score(row)
    semantic_c = _clamp01(semantic)
    graph_c = _clamp01(graph)
    certainty_multiplier = _certainty_multiplier(row)
    breakdown = {
        "semantic": round(semantic_c, 4),
        "confidence": round(confidence, 4),
        "recency": round(recency, 4),
        "graph_reinforcement": round(graph_c, 4),
        "certainty_multiplier": round(certainty_multiplier, 4),
    }
    score = (
        W_SPARK_SEMANTIC * semantic_c
        + W_SPARK_CONFIDENCE * confidence
        + W_SPARK_RECENCY * recency
        + W_SPARK_GRAPH * graph_c
    )
    return round(score * certainty_multiplier, 4), breakdown


def _bump_spark_access(
    conn: sqlite3.Connection, spark_ids: list[int], now: str
) -> None:
    for spark_id in spark_ids:
        conn.execute(
            """
            UPDATE sparks
            SET access_count = access_count + 1, last_accessed_at = ?
            WHERE id = ?
            """,
            (now, spark_id),
        )


def _rank_spark_candidates(
    conn: sqlite3.Connection,
    candidate_ids: set[int],
    *,
    semantic_scores: dict[int, float],
    keyword_candidate_ids: set[int],
    graph_boosts: dict[int, float] | None = None,
    project_id: int | None,
    lanes: frozenset[str] | None,
) -> list[SparkRetrievalResult]:
    results: list[SparkRetrievalResult] = []
    graph_boosts = graph_boosts or {}
    pattern_spark_ids = spark_lifecycle.active_pattern_spark_ids(conn)
    for spark_id in candidate_ids:
        row = _load_spark_row(conn, spark_id, project_id=project_id, lanes=lanes)
        if row is None:
            continue
        semantic = semantic_scores.get(spark_id, 0.0)
        if semantic <= 0.0 and spark_id in keyword_candidate_ids:
            semantic = SPARK_KEYWORD_SEMANTIC_FLOOR
        graph = max(
            _spark_graph_reinforcement(conn, spark_id),
            graph_boosts.get(spark_id, 0.0),
        )
        live_confidence = spark_lifecycle.live_confidence_for_spark(
            conn,
            row,
            pattern_spark_ids=pattern_spark_ids,
        )
        score, breakdown = _score_spark(
            row,
            semantic=semantic,
            graph=graph,
            live_confidence=live_confidence,
        )
        results.append(
            SparkRetrievalResult(
                spark_id=spark_id,
                content=str(row["content"]),
                lane=str(row["lane"]),
                trust_state=str(row["trust_state"]),
                confidence=live_confidence,
                score=score,
                score_breakdown=breakdown,
                sensitivity=str(row["sensitivity"] or "normal"),
            )
        )
    return sorted(results, key=lambda item: (-item.score, item.spark_id))


def retrieve_sparks(
    query: str,
    *,
    limit: int = SPARK_DEFAULT_LIMIT,
    project_id: int | None = None,
    lanes: frozenset[str] | None = None,
    conn: sqlite3.Connection | None = None,
    bump_access: bool = True,
    expand_hops: int = 0,
    expand_max_nodes: int = spark_graph.SPARK_GRAPH_MAX_NODES,
    depth: str | None = None,
) -> list[SparkRetrievalResult]:
    """Hybrid spark retrieval with canonical deterministic scoring."""
    import crowley

    owns_conn = conn is None
    db = conn or crowley.connect_db()
    try:
        query_embedding = crowley.embed_text(query)
        semantic_scores = _spark_semantic_candidate_scores(
            db,
            query_embedding,
            SPARK_RETRIEVE_VECTOR_CANDIDATES,
            project_id=project_id,
            lanes=lanes,
        )
        keyword_scores = _spark_keyword_candidate_scores(
            db,
            query,
            SPARK_RETRIEVE_KEYWORD_CANDIDATES,
            project_id=project_id,
            lanes=lanes,
        )
        keyword_candidate_ids = set(keyword_scores.keys())
        candidate_ids: set[int] = (
            set(semantic_scores.keys()) | keyword_candidate_ids | _pinned_spark_ids(
                db, project_id=project_id, lanes=lanes
            )
        )

        ranked = _rank_spark_candidates(
            db,
            candidate_ids,
            semantic_scores=semantic_scores,
            keyword_candidate_ids=keyword_candidate_ids,
            project_id=project_id,
            lanes=lanes,
        )
        if expand_hops > 0 and ranked:
            seed_ids = [item.spark_id for item in ranked[: max(0, limit)]]
            expansion = spark_graph.expand_spark_graph(
                db,
                seed_ids,
                max_hops=expand_hops,
                max_nodes=expand_max_nodes,
                project_id=project_id,
                lanes=lanes,
            )
            if expansion.hop_distance:
                ranked = _rank_spark_candidates(
                    db,
                    candidate_ids | set(expansion.hop_distance.keys()),
                    semantic_scores=semantic_scores,
                    keyword_candidate_ids=keyword_candidate_ids,
                    graph_boosts=expansion.graph_boost,
                    project_id=project_id,
                    lanes=lanes,
                )

        filtered = spark_security.filter_ranked_sparks(
            ranked,
            query_lanes=lanes,
            depth=depth,
        )
        top = filtered[: max(0, limit)]
        if bump_access and top:
            now = crowley._now_iso()
            _bump_spark_access(db, [item.spark_id for item in top], now)
            if owns_conn:
                db.commit()
        return top
    finally:
        if owns_conn:
            db.close()
