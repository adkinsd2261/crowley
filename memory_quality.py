"""V3.9.19 memory quality — ingest dedup, retrieval validation, lifecycle cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

CONSTRAINT_SIMILARITY_THRESHOLD = 0.65
SEMANTIC_SIMILARITY_THRESHOLD = 0.85
CONSTRAINT_LOOKBACK_DAYS = 90
SEMANTIC_LOOKBACK_HOURS = 72

CONSTRAINT_TYPES = frozenset({"constraint"})
SEMANTIC_DEDUPE_TYPES = frozenset({"summary", "project_update", "lesson", "event"})

STRONG_RETRIEVAL_MIN_SCORE = 0.55
STRONG_RETRIEVAL_MIN_SEMANTIC = 0.35


def token_similarity(left: str, right: str) -> float:
    left_tokens = {t for t in left.lower().split() if len(t) > 2}
    right_tokens = {t for t in right.lower().split() if len(t) > 2}
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union)


def find_ingest_duplicate(
    conn,
    memory_type: str,
    content: str,
    project_id: int | None,
) -> tuple[int | None, str | None]:
    """
    Return (existing_memory_id, reason) when ingest should skip/merge.
    Extends exact dedupe with constraint and semantic-type similarity checks.
    """
    import crowley

    existing = crowley._find_recent_duplicate_memory_item(  # noqa: SLF001
        conn, memory_type, content, project_id
    )
    if existing is not None:
        return int(existing), "exact_dedupe"

    normalized_type = memory_type.strip().lower()
    if normalized_type in CONSTRAINT_TYPES:
        return _find_similar_memory(
            conn,
            memory_type=normalized_type,
            content=content,
            project_id=project_id,
            since=datetime.now(timezone.utc) - timedelta(days=CONSTRAINT_LOOKBACK_DAYS),
            threshold=CONSTRAINT_SIMILARITY_THRESHOLD,
            reason="constraint_semantic_duplicate",
        )
    if normalized_type in SEMANTIC_DEDUPE_TYPES:
        return _find_similar_memory(
            conn,
            memory_type=normalized_type,
            content=content,
            project_id=project_id,
            since=datetime.now(timezone.utc) - timedelta(hours=SEMANTIC_LOOKBACK_HOURS),
            threshold=SEMANTIC_SIMILARITY_THRESHOLD,
            reason="semantic_duplicate",
        )
    return None, None


def _constraints_are_conflicting(left: str, right: str) -> bool:
    """Same topic but opposing constraint wording — do not dedupe."""
    if token_similarity(left, right) < 0.45:
        return False
    import crowley

    left_polarity = crowley._hygiene_polarity(left)  # noqa: SLF001
    right_polarity = crowley._hygiene_polarity(right)  # noqa: SLF001
    if left_polarity != 0 and right_polarity != 0 and left_polarity != right_polarity:
        return True
    combined = f"{left} {right}".lower()
    return any(
        marker in combined
        for marker in ("opposite", "instead of", "rather than", "conflicts with")
    )


def _find_similar_memory(
    conn,
    *,
    memory_type: str,
    content: str,
    project_id: int | None,
    since: datetime,
    threshold: float,
    reason: str,
) -> tuple[int | None, str | None]:
    params: list[object] = [memory_type, since.isoformat()]
    project_clause = ""
    if project_id is None:
        project_clause = "AND project_id IS NULL"
    else:
        project_clause = "AND project_id = ?"
        params.append(project_id)
    rows = conn.execute(
        f"""
        SELECT id, content FROM memory_items
        WHERE memory_type = ? AND status = 'active'
          AND datetime(created_at) >= datetime(?)
          {project_clause}
        ORDER BY id DESC
        LIMIT 200
        """,
        params,
    ).fetchall()
    for row in rows:
        existing_content = str(row["content"])
        if memory_type == "constraint" and _constraints_are_conflicting(content, existing_content):
            continue
        if token_similarity(content, existing_content) >= threshold:
            return int(row["id"]), reason
    return None, None


def assess_retrieval_strength(
    query: str,
    results: list[dict[str, object]],
) -> str:
    """#154 — post-retrieval sufficiency signal (non-blocking)."""
    del query
    if not results:
        return "weak"
    top = results[0]
    score = float(top.get("score", 0) or 0)
    breakdown = top.get("score_breakdown")
    semantic = 0.0
    if isinstance(breakdown, dict):
        semantic = float(breakdown.get("semantic", 0) or 0)
    if score >= STRONG_RETRIEVAL_MIN_SCORE and semantic >= STRONG_RETRIEVAL_MIN_SEMANTIC:
        return "strong"
    if score >= 0.4 or semantic >= 0.25:
        return "moderate"
    return "weak"


def annotate_retrieval_payload(payload: dict[str, object]) -> dict[str, object]:
    """Add retrieval_strength to retrieve API payloads."""
    results = payload.get("results")
    if not isinstance(results, list):
        payload["retrieval_strength"] = "weak"
        return payload
    typed_results = [r for r in results if isinstance(r, dict)]
    strength = assess_retrieval_strength(str(payload.get("query", "")), typed_results)
    payload["retrieval_strength"] = strength
    payload["retrieval_validation"] = {
        "strength": strength,
        "result_count": len(typed_results),
        "top_score": float(typed_results[0].get("score", 0) or 0) if typed_results else 0.0,
    }
    return payload


def run_minimal_lifecycle_cleanup(*, dry_run: bool = True) -> dict[str, object]:
    """#157 — merge duplicate clusters and mark stale low-access memories."""
    import crowley

    conn = crowley.connect_db()
    try:
        before = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
            ).fetchone()["n"]
        )
        duplicates = crowley.run_duplicate_merge(conn, dry_run=dry_run)
        stale = crowley.run_stale_marking(conn, dry_run=dry_run)
        if not dry_run:
            conn.commit()
        after = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
            ).fetchone()["n"]
        )
    finally:
        conn.close()
    return {
        "dry_run": dry_run,
        "active_before": before,
        "active_after": after,
        "duplicates": duplicates,
        "stale": stale,
        "reduced_by": max(0, before - after),
    }


def quality_payload() -> dict[str, object]:
    return {
        "constraint_similarity_threshold": CONSTRAINT_SIMILARITY_THRESHOLD,
        "semantic_similarity_threshold": SEMANTIC_SIMILARITY_THRESHOLD,
        "retrieval_strength_thresholds": {
            "strong_min_score": STRONG_RETRIEVAL_MIN_SCORE,
            "strong_min_semantic": STRONG_RETRIEVAL_MIN_SEMANTIC,
        },
    }
