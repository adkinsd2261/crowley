"""V4.3 T1 — rules-first cognitive query interpreter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import sparks

QueryMode = Literal["recall", "decision", "reflection", "planning"]

QUERY_MODES: frozenset[str] = frozenset(
    {"recall", "decision", "reflection", "planning"}
)

# Longer phrases first within each mode for contains matching.
_MODE_MARKERS: dict[QueryMode, tuple[str, ...]] = {
    "planning": (
        "next steps",
        "how should i",
        "what should i do",
        "roadmap",
        "prioritize",
        "timeline",
        "schedule",
        "planning",
        "plan",
    ),
    "decision": (
        "which option",
        "should i",
        "or not",
        "tradeoff",
        "trade-off",
        "commit to",
        "decide",
        "choose",
        "versus",
        "vs",
    ),
    "reflection": (
        "how do i feel",
        "looking back",
        "what did i learn",
        "why do i always",
        "reflect",
        "reflection",
        "patterns",
        "pattern",
    ),
    "recall": (
        "what did",
        "when did",
        "what was",
        "remind me",
        "show me",
        "do i have",
        "list",
    ),
}

# No-op placeholder for future tie-break models (T1: never call providers).
_MODEL_TIEBREAK_HOOK = None

# Deterministic lane keyword map (word-boundary). Complements SPARK_LANES + DOMAIN_ALIASES.
_LANE_QUERY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "money": (
        "budget",
        "salary",
        "insurance",
        "expense",
        "expenses",
        "subscription",
        "subscriptions",
        "invest",
        "investment",
        "payment",
        "payments",
        "paying",
    ),
    "health": (
        "doctor",
        "therapy",
        "sleep",
        "workout",
        "knee",
        "medication",
        "medications",
    ),
    "work": (
        "offer",
        "standup",
        "deadline",
        "deadlines",
        "employer",
        "coworker",
        "coworkers",
    ),
    "relationships": (
        "partner",
        "friend",
        "friends",
        "family",
        "spouse",
    ),
    "learning": (
        "course",
        "study",
        "lesson",
        "curriculum",
    ),
    "operating_style": (
        "habit",
        "habits",
        "routine",
        "routines",
        "workflow",
    ),
}


@dataclass(frozen=True)
class QueryInterpretation:
    mode: QueryMode
    confidence: float
    reason: str
    hints: dict[str, object] = field(default_factory=dict)
    inferred_lanes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "confidence": self.confidence,
            "reason": self.reason,
            "hints": dict(self.hints),
            "inferred_lanes": list(self.inferred_lanes),
        }


def _normalize_query(q: str) -> str:
    return " ".join(str(q or "").split()).strip()


def _marker_hits(lowered: str, markers: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for marker in markers:
        token = marker.strip().lower()
        if not token:
            continue
        if " " in token:
            if token in lowered:
                hits.append(token)
            continue
        if re.search(rf"\b{re.escape(token)}\b", lowered):
            hits.append(token)
    return hits


def _score_modes(lowered: str) -> dict[QueryMode, list[str]]:
    return {
        mode: _marker_hits(lowered, markers)
        for mode, markers in _MODE_MARKERS.items()
    }


def _confidence_from_margin(winner_hits: int, runner_hits: int) -> float:
    if winner_hits <= 0:
        return 0.35
    margin = winner_hits - runner_hits
    if margin <= 0:
        return 0.45
    return min(0.95, 0.55 + 0.15 * winner_hits + 0.1 * margin)


def infer_lanes_from_query(q: str) -> list[str]:
    """Infer candidate lanes from SPARK_LANES, DOMAIN_ALIASES, and keyword map.

    Returns a sorted unique list. Filtering is applied by orchestration (T2),
    not by this helper alone — retrieve_sparks must not auto-infer.
    """
    lowered = _normalize_query(q).lower()
    if not lowered:
        return []

    found: set[str] = set()
    for lane in sparks.SPARK_LANES:
        if re.search(rf"\b{re.escape(lane)}\b", lowered):
            found.add(lane)
    for alias, lane in sparks.DOMAIN_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            found.add(lane)
    for lane, keywords in _LANE_QUERY_KEYWORDS.items():
        if lane not in sparks.SPARK_LANES:
            continue
        for keyword in keywords:
            if re.search(rf"\b{re.escape(keyword)}\b", lowered):
                found.add(lane)
                break
    return sorted(found)


def interpret_query(
    q: str,
    *,
    explicit_mode: str | None = None,
) -> QueryInterpretation:
    """Classify a retrieval query into recall|decision|reflection|planning."""
    if explicit_mode is not None:
        mode = str(explicit_mode).strip().lower()
        if mode not in QUERY_MODES:
            raise ValueError(
                "query_mode must be one of recall|decision|reflection|planning"
            )
        return QueryInterpretation(
            mode=mode,  # type: ignore[arg-type]
            confidence=1.0,
            reason="explicit_query_mode",
            hints={"explicit": True},
            inferred_lanes=infer_lanes_from_query(q),
        )

    normalized = _normalize_query(q)
    inferred = infer_lanes_from_query(normalized)
    if not normalized:
        return QueryInterpretation(
            mode="recall",
            confidence=0.2,
            reason="empty_query",
            hints={},
            inferred_lanes=inferred,
        )

    lowered = normalized.lower()
    hits_by_mode = _score_modes(lowered)
    scored = sorted(
        ((mode, hits) for mode, hits in hits_by_mode.items() if hits),
        key=lambda item: (-len(item[1]), item[0]),
    )

    if not scored:
        return QueryInterpretation(
            mode="recall",
            confidence=0.4,
            reason="default_recall",
            hints={"matched_markers": []},
            inferred_lanes=inferred,
        )

    top_mode, top_hits = scored[0]
    top_count = len(top_hits)
    runner_count = len(scored[1][1]) if len(scored) > 1 else 0
    tied = [mode for mode, hits in scored if len(hits) == top_count]

    if len(tied) > 1:
        # T1: rules-only tie-break. Model hook is intentionally a no-op.
        _ = _MODEL_TIEBREAK_HOOK
        return QueryInterpretation(
            mode="recall",
            confidence=0.45,
            reason="tie_break_recall",
            hints={
                "tied_modes": sorted(tied),
                "matched_markers": {
                    mode: hits_by_mode[mode] for mode in sorted(tied)
                },
            },
            inferred_lanes=inferred,
        )

    return QueryInterpretation(
        mode=top_mode,
        confidence=_confidence_from_margin(top_count, runner_count),
        reason=f"markers_{top_mode}",
        hints={"matched_markers": top_hits},
        inferred_lanes=inferred,
    )
