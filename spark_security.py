"""V4 T18 — spark sensitivity exposure gates for retrieval and context."""

from __future__ import annotations

HIGH_SENSITIVITY_MIN_SCORE = 0.7
_CONTEXT_DEPTHS = frozenset({"light", "medium", "deep"})


def normalize_depth(depth: str | None) -> str:
    if depth is None:
        return "medium"
    normalized = str(depth).strip().lower()
    if normalized not in _CONTEXT_DEPTHS:
        return "medium"
    return normalized


def spark_exposure_allowed(
    *,
    sensitivity: str,
    spark_lane: str,
    query_lanes: frozenset[str] | None,
    depth: str | None,
    score: float,
) -> bool:
    """Deterministic exposure gate for sensitive/high sparks."""
    level = str(sensitivity or "normal").strip().lower()
    if level == "normal":
        return True
    if query_lanes is None:
        return False
    if str(spark_lane) not in query_lanes:
        return False
    if level == "sensitive":
        return True
    if level == "high":
        if normalize_depth(depth) == "light":
            return False
        return float(score) > HIGH_SENSITIVITY_MIN_SCORE
    return True


def filter_ranked_sparks(
    ranked: list[object],
    *,
    query_lanes: frozenset[str] | None,
    depth: str | None,
) -> list[object]:
    """Filter ranked SparkRetrievalResult rows after scoring, before slicing."""
    kept: list[object] = []
    for item in ranked:
        sensitivity = getattr(item, "sensitivity", "normal")
        if spark_exposure_allowed(
            sensitivity=str(sensitivity),
            spark_lane=str(item.lane),
            query_lanes=query_lanes,
            depth=depth,
            score=float(item.score),
        ):
            kept.append(item)
    return kept
