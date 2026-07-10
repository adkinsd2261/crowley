"""V4.3.1/V4.3.2 — memory_items → sparks corpus migration policy and helpers.

Read-only selection and dry-run extraction live here; scripts wrap CLI.
memory_items remain receipts/fallback — never deleted in migration apply.
V4.3.2 adds coverage targets, candidate tiers A–D, and expansion tooling.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import crowley
import sparks

# --- Selection policy -------------------------------------------------------

MIGRATE_TYPES = frozenset(
    {"decision", "constraint", "lesson", "preference", "summary", "project_update"}
)
EXCLUDE_STATUSES = frozenset({"merged", "rejected", "staged"})
HIGH_IMPORTANCE_MIN = 4
SHORT_MAX = 280
MIN_CONTENT_LEN = 24
DEFAULT_APPLY_LIMIT_CAP = 50

# V4.3.2 candidate tiers (A highest → D excluded)
TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_D = "D"
MIGRATE_TIERS = frozenset({TIER_A, TIER_B, TIER_C})
TIER_RANK_BASE = {TIER_A: 0, TIER_B: 20, TIER_C: 40, TIER_D: 90}

# Coverage targets for spark-first corpus (V4.3.2 T1)
COVERAGE_TARGETS = {
    "active_or_pinned_sparks_min": 50,
    "total_sparks_with_lineage_min": 200,
    "active_memory_items_without_lineage_max": 400,
    "tier_a_migrated_min": 20,
    "tier_b_migrated_min": 80,
}

TYPE_TO_SPARK = {
    "decision": "decision",
    "lesson": "observation",
    "preference": "intent",
    "constraint": "fact",
    "summary": "observation",
    "project_update": "observation",
}
TYPE_TO_LANE = {
    "decision": "work",
    "lesson": "learning",
    "preference": "operating_style",
    "constraint": "work",
    "summary": "work",
    "project_update": "work",
}

# Noise / skip patterns (handoff receipts, QA chatter, side-quest recovery)
_HANDOFF_MARKERS = (
    "builder_handoff",
    "architect_handoff",
    "handoff #",
    "claimed ticket",
    "ticket marked done",
    "cursor_sync",
    "codex_sync",
    "events from other agents",
)
_QA_NOISE_MARKERS = (
    "unittest discovery",
    "qa-result",
    "tests run:",
    "pytest ",
)
_SIDEQUEST_MARKERS = (
    "side-quest",
    "side quest",
    "quarantine",
    "reverted the side-quest",
    "recovery complete: codebase is back",
    "discarded/quarantined",
)
# Ticket approval/denial chatter — Tier D unless manually whitelisted
_TICKET_CHATTER_MARKERS = (
    "approve #",
    "deny #",
    "approved #",
    "denied #",
    "approve v4.",
    "deny v4.",
    "cursor may proceed to #",
    "cursor may close #",
    "cursor may implement",
    "ticket marked done",
    "claimed ticket #",
    "plan-only handoff",
    "e2e-not-clean",
    "resubmission",
)

HEALTH_RE = re.compile(
    r"\b(health|sleep|walk|exercise|gym|diet|stress|anxiety|energy)\b", re.I
)
MONEY_RE = re.compile(
    r"\b(money|budget|finance|invoice|revenue|cost|pricing|cash)\b", re.I
)
REL_RE = re.compile(
    r"\b(relationship|partner|family|friend|team dynamics)\b", re.I
)
LEARN_RE = re.compile(r"\b(learn|lesson|study|course|skill|practice)\b", re.I)
STYLE_RE = re.compile(
    r"\b(prefer|preference|operating style|workflow|habit|ritual)\b", re.I
)


@dataclass(frozen=True)
class CandidateDecision:
    include: bool
    reason: str
    proposed_trust: str
    rank: int
    tier: str = TIER_D


def _row_text(row: Any) -> str:
    summary = str(row["summary"] or "").strip()
    content = str(row["content"] or "").strip()
    return summary or content


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clip_spark_content(text: str, limit: int = SHORT_MAX) -> str:
    cleaned = _normalize_ws(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def infer_lane(memory_type: str, content: str) -> str:
    if HEALTH_RE.search(content):
        return "health"
    if MONEY_RE.search(content):
        return "money"
    if REL_RE.search(content):
        return "relationships"
    if LEARN_RE.search(content) or memory_type == "lesson":
        return "learning"
    if STYLE_RE.search(content) or memory_type == "preference":
        return "operating_style"
    return TYPE_TO_LANE.get(memory_type, "work")


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _is_high_signal(row: Any) -> bool:
    pinned = bool(int(row["pinned"] or 0))
    importance = int(row["importance"] or 0)
    memory_type = str(row["memory_type"] or "")
    source = str(row["source"] or "").lower()
    if pinned:
        return True
    if importance >= HIGH_IMPORTANCE_MIN:
        return True
    if memory_type in {"decision", "constraint", "lesson", "preference"}:
        return True
    if source in {"canon", "manual", "portable_terminal", "consolidation"}:
        return True
    return False


def _is_ticket_chatter(text: str) -> bool:
    return _contains_any(text, _TICKET_CHATTER_MARKERS)


def classify_tier(row: Any) -> str:
    """Assign Tier A/B/C/D for a memory_item (before include/exclude)."""
    memory_type = str(row["memory_type"] or "")
    source = str(row["source"] or "").lower()
    pinned = bool(int(row["pinned"] or 0))
    importance = int(row["importance"] or 0)
    text = _row_text(row)

    # Tier D: noise / receipts / ticket chatter
    if memory_type in {"event", "qa_result", "bug"}:
        return TIER_D
    if _contains_any(text, _SIDEQUEST_MARKERS) and not pinned:
        return TIER_D
    if _contains_any(text, _QA_NOISE_MARKERS) and not pinned:
        return TIER_D
    if _is_ticket_chatter(text) and not (pinned and source == "canon"):
        return TIER_D
    if (
        _contains_any(text, _HANDOFF_MARKERS)
        or source in {"cursor", "codex", "agent_handoff"}
        or "handoff" in source
    ):
        if memory_type not in {"decision", "constraint", "lesson", "preference"}:
            return TIER_D
        if not (pinned or source == "canon" or importance >= HIGH_IMPORTANCE_MIN):
            return TIER_D

    # Tier A: canon / pinned / current-state
    if pinned and source == "canon":
        return TIER_A
    if pinned and memory_type in {"decision", "constraint", "preference", "summary"}:
        return TIER_A
    if source == "canon" and memory_type in {
        "decision",
        "constraint",
        "preference",
        "summary",
        "lesson",
    }:
        return TIER_A

    # Tier B: durable decisions / constraints / preferences / lessons
    if memory_type in {"decision", "constraint", "preference", "lesson"}:
        return TIER_B
    if memory_type == "summary" and (
        pinned or source in {"manual", "consolidation", "portable_terminal"}
    ):
        return TIER_B

    # Tier C: high-signal project updates
    if memory_type == "project_update" and (
        pinned or importance >= HIGH_IMPORTANCE_MIN
    ):
        return TIER_C
    if memory_type == "summary" and importance >= HIGH_IMPORTANCE_MIN:
        return TIER_C

    return TIER_D


def evaluate_candidate(row: Any, *, already_linked: bool) -> CandidateDecision:
    """Deterministic include/exclude for one memory_item row."""
    status = str(row["status"] or "")
    memory_type = str(row["memory_type"] or "")
    text = _row_text(row)
    source = str(row["source"] or "").lower()
    pinned = bool(int(row["pinned"] or 0))
    importance = int(row["importance"] or 0)
    tier = classify_tier(row)

    if already_linked:
        return CandidateDecision(False, "already_linked", "candidate", 99, tier)
    if status in EXCLUDE_STATUSES:
        return CandidateDecision(
            False, f"status_{status}", "candidate", 99, TIER_D
        )
    if status != "active":
        return CandidateDecision(
            False, f"status_{status}", "candidate", 99, TIER_D
        )
    if len(_normalize_ws(text)) < MIN_CONTENT_LEN:
        return CandidateDecision(False, "too_short", "candidate", 99, TIER_D)

    if tier == TIER_D:
        reason = "tier_d_excluded"
        if _is_ticket_chatter(text):
            reason = "ticket_chatter"
        elif _contains_any(text, _SIDEQUEST_MARKERS):
            reason = "sidequest_noise"
        elif memory_type == "qa_result" or _contains_any(text, _QA_NOISE_MARKERS):
            reason = "qa_noise"
        elif (
            _contains_any(text, _HANDOFF_MARKERS)
            or source in {"cursor", "codex", "agent_handoff"}
            or "handoff" in source
        ):
            reason = "handoff_receipt"
        elif memory_type == "project_update":
            reason = "low_signal_project_update"
        elif memory_type not in MIGRATE_TYPES:
            reason = "type_excluded"
        return CandidateDecision(False, reason, "candidate", 90, TIER_D)

    proposed_trust = "candidate"
    if pinned and source == "canon":
        proposed_trust = "pinned"
    elif pinned and memory_type == "decision":
        proposed_trust = "active"
    elif source == "canon" and memory_type in {"decision", "constraint", "summary"}:
        proposed_trust = "active"

    rank = _rank_score(row, tier=tier)
    reason = _include_reason(row, tier=tier)
    return CandidateDecision(True, reason, proposed_trust, rank, tier)


def _rank_score(row: Any, *, tier: str | None = None) -> int:
    """Lower is better. Tier A before B before C; ticket chatter never ahead."""
    memory_type = str(row["memory_type"] or "")
    source = str(row["source"] or "").lower()
    pinned = bool(int(row["pinned"] or 0))
    importance = int(row["importance"] or 0)
    resolved_tier = tier or classify_tier(row)
    score = TIER_RANK_BASE.get(resolved_tier, 90)
    if pinned and source == "canon":
        score += 0
    elif pinned and memory_type == "decision":
        score += 1
    elif memory_type == "decision" and source == "canon":
        score += 2
    elif memory_type == "decision":
        score += 3
    elif memory_type == "constraint":
        score += 4
    elif memory_type == "lesson":
        score += 5
    elif memory_type == "preference":
        score += 6
    elif memory_type == "summary":
        score += 7
    elif memory_type == "project_update":
        score += 8
    else:
        score += 15
    score -= min(importance, 5)
    return score


def _include_reason(row: Any, *, tier: str | None = None) -> str:
    memory_type = str(row["memory_type"] or "")
    source = str(row["source"] or "").lower()
    pinned = bool(int(row["pinned"] or 0))
    importance = int(row["importance"] or 0)
    resolved_tier = tier or classify_tier(row)
    parts: list[str] = [f"tier_{resolved_tier}"]
    if pinned:
        parts.append("pinned")
    if source == "canon":
        parts.append("canon")
    parts.append(memory_type)
    if importance >= HIGH_IMPORTANCE_MIN:
        parts.append(f"importance_{importance}")
    return "+".join(parts)


def linked_memory_item_ids(conn: Any) -> set[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT source_memory_item_id AS id
        FROM sparks
        WHERE source_memory_item_id IS NOT NULL
        """
    ).fetchall()
    return {int(r["id"]) for r in rows if r["id"] is not None}


def load_active_memory_rows(conn: Any, *, limit: int | None = None) -> list[Any]:
    sql = """
        SELECT id, memory_type, content, summary, confidence, project_id,
               status, source, importance, pinned, created_at, updated_at
        FROM memory_items
        ORDER BY pinned DESC, importance DESC, id DESC
    """
    if limit is not None:
        sql += " LIMIT ?"
        return list(conn.execute(sql, (int(limit),)).fetchall())
    return list(conn.execute(sql).fetchall())


def select_candidates(
    conn: Any,
    *,
    limit: int | None = None,
    scan_limit: int | None = None,
    tiers: frozenset[str] | None = None,
) -> dict[str, object]:
    """Dry-run candidate selection. Never writes.

    ``tiers`` filters included candidates to the given migrate tiers (A/B/C).
    Tier D is never included.
    """
    allowed_tiers = tiers or MIGRATE_TIERS
    linked = linked_memory_item_ids(conn)
    rows = load_active_memory_rows(conn, limit=scan_limit)
    included: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    include_reasons: dict[str, int] = {}
    skip_reasons: dict[str, int] = {}
    tier_counts: dict[str, int] = {TIER_A: 0, TIER_B: 0, TIER_C: 0, TIER_D: 0}
    tier_remaining: dict[str, int] = {TIER_A: 0, TIER_B: 0, TIER_C: 0, TIER_D: 0}
    seen_fingerprints: set[str] = set()

    for row in rows:
        mid = int(row["id"])
        decision = evaluate_candidate(row, already_linked=mid in linked)
        text = _normalize_ws(_row_text(row))
        fp = text.lower()[:200]
        tier_counts[decision.tier] = tier_counts.get(decision.tier, 0) + 1
        if decision.include and fp in seen_fingerprints:
            decision = CandidateDecision(
                False, "duplicate_summary", "candidate", 88, decision.tier
            )
        if decision.include and decision.tier not in allowed_tiers:
            decision = CandidateDecision(
                False,
                f"tier_{decision.tier}_filtered",
                "candidate",
                decision.rank,
                decision.tier,
            )
        entry = {
            "memory_item_id": mid,
            "memory_type": str(row["memory_type"]),
            "source": str(row["source"]),
            "importance": int(row["importance"] or 0),
            "pinned": bool(int(row["pinned"] or 0)),
            "status": str(row["status"]),
            "preview": text[:120],
            "tier": decision.tier,
            "include_reason": decision.reason if decision.include else None,
            "skip_reason": None if decision.include else decision.reason,
            "proposed_trust": decision.proposed_trust,
            "rank": decision.rank,
        }
        if decision.include:
            seen_fingerprints.add(fp)
            included.append(entry)
            include_reasons[decision.reason] = include_reasons.get(decision.reason, 0) + 1
            tier_remaining[decision.tier] = tier_remaining.get(decision.tier, 0) + 1
        else:
            skipped.append(entry)
            skip_reasons[decision.reason] = skip_reasons.get(decision.reason, 0) + 1
            if decision.tier == TIER_D or decision.reason.startswith("status_"):
                pass
            elif mid not in linked:
                # Count unmigrated rows still sitting in A/B/C but skipped for other reasons
                if decision.reason == "already_linked":
                    pass

    included.sort(
        key=lambda e: (int(e["rank"]), -int(e["importance"]), -int(e["memory_item_id"]))
    )
    if limit is not None:
        included = included[: int(limit)]

    # Remaining = included before limit truncation for full scan
    remaining_full = {
        TIER_A: sum(1 for e in included if e["tier"] == TIER_A)
        if limit is None
        else tier_remaining.get(TIER_A, 0),
        TIER_B: tier_remaining.get(TIER_B, 0),
        TIER_C: tier_remaining.get(TIER_C, 0),
        TIER_D: tier_counts.get(TIER_D, 0),
    }
    if limit is not None:
        # Recompute remaining from pre-limit counts stored in tier_remaining
        remaining_full = {
            TIER_A: tier_remaining.get(TIER_A, 0),
            TIER_B: tier_remaining.get(TIER_B, 0),
            TIER_C: tier_remaining.get(TIER_C, 0),
            TIER_D: int(skip_reasons.get("tier_d_excluded", 0))
            + int(skip_reasons.get("ticket_chatter", 0))
            + int(skip_reasons.get("handoff_receipt", 0))
            + int(skip_reasons.get("qa_noise", 0))
            + int(skip_reasons.get("sidequest_noise", 0))
            + int(skip_reasons.get("type_excluded", 0))
            + int(skip_reasons.get("low_signal_project_update", 0)),
        }

    return {
        "generated_at": crowley._now_iso(),
        "dry_run": True,
        "scanned": len(rows),
        "already_linked": len(linked),
        "included_count": len(included),
        "skipped_count": len(skipped),
        "include_reason_counts": dict(sorted(include_reasons.items())),
        "skip_reason_counts": dict(sorted(skip_reasons.items())),
        "tier_counts_scanned": dict(sorted(tier_counts.items())),
        "tier_remaining": dict(sorted(remaining_full.items())),
        "allowed_tiers": sorted(allowed_tiers),
        "candidates": included,
        "skipped_sample": skipped[:25],
        "policy": {
            "migrate_types": sorted(MIGRATE_TYPES),
            "exclude_statuses": sorted(EXCLUDE_STATUSES),
            "tiers": {
                "A": "canon/pinned/current-state",
                "B": "durable decisions/constraints/preferences/lessons",
                "C": "high-signal project updates",
                "D": "receipts/noise/ticket chatter (excluded)",
            },
            "no_bulk_dump": True,
            "memory_items_remain": True,
        },
    }


def build_coverage_report(conn: Any | None = None) -> dict[str, object]:
    """Coverage targets + tier remaining + spark lineage stats (read-only)."""
    owns = conn is None
    if owns:
        conn = crowley.connect_db()
    assert conn is not None
    try:
        inventory = build_inventory(conn)
        selection = select_candidates(conn, limit=None)

        def _count(sql: str, params: tuple = ()) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row["n"] if row is not None else 0)

        sparks_by_trust = inventory.get("sparks_by_trust_state") or []
        sparks_by_lane = inventory.get("sparks_by_lane") or []
        active_or_pinned = int(inventory.get("sparks_active") or 0) + int(
            inventory.get("sparks_pinned") or 0
        )
        lineage_total = _count(
            "SELECT COUNT(*) AS n FROM sparks WHERE source_memory_item_id IS NOT NULL"
        )
        # Coverage of migrated sparks by source memory_type
        by_source_type = [
            dict(r)
            for r in conn.execute(
                """
                SELECT mi.memory_type, COUNT(*) AS n
                FROM sparks s
                JOIN memory_items mi ON mi.id = s.source_memory_item_id
                GROUP BY mi.memory_type
                ORDER BY n DESC
                """
            ).fetchall()
        ]
        by_source = [
            dict(r)
            for r in conn.execute(
                """
                SELECT mi.source, COUNT(*) AS n
                FROM sparks s
                JOIN memory_items mi ON mi.id = s.source_memory_item_id
                GROUP BY mi.source
                ORDER BY n DESC
                LIMIT 20
                """
            ).fetchall()
        ]
        targets = dict(COVERAGE_TARGETS)
        progress = {
            "active_or_pinned_sparks": active_or_pinned,
            "total_sparks_with_lineage": lineage_total,
            "active_memory_items_without_lineage": int(
                inventory.get("active_memory_items_without_spark_lineage") or 0
            ),
            "tier_remaining": selection.get("tier_remaining"),
            "tier_counts_scanned": selection.get("tier_counts_scanned"),
        }
        gaps = {
            "active_or_pinned_sparks": max(
                0, targets["active_or_pinned_sparks_min"] - active_or_pinned
            ),
            "total_sparks_with_lineage": max(
                0, targets["total_sparks_with_lineage_min"] - lineage_total
            ),
            "active_memory_items_without_lineage_over": max(
                0,
                int(progress["active_memory_items_without_lineage"])
                - targets["active_memory_items_without_lineage_max"],
            ),
        }
        return {
            "generated_at": crowley._now_iso(),
            "read_only": True,
            "targets": targets,
            "progress": progress,
            "gaps": gaps,
            "sparks_total": inventory.get("sparks_total"),
            "sparks_active": inventory.get("sparks_active"),
            "sparks_pinned": inventory.get("sparks_pinned"),
            "sparks_by_trust_state": sparks_by_trust,
            "sparks_by_lane": sparks_by_lane,
            "migrated_by_memory_type": by_source_type,
            "migrated_by_source": by_source,
            "memory_items_active": inventory.get("memory_items_active"),
            "active_memory_items_without_spark_lineage": inventory.get(
                "active_memory_items_without_spark_lineage"
            ),
            "candidate_include_count": selection.get("included_count"),
            "candidate_skip_reason_counts": selection.get("skip_reason_counts"),
            "tier_remaining": selection.get("tier_remaining"),
            "cold_start_retrieval": inventory.get("cold_start_retrieval"),
        }
    finally:
        if owns:
            conn.close()


def format_coverage_markdown(report: dict[str, object]) -> str:
    targets = report.get("targets") or {}
    progress = report.get("progress") or {}
    gaps = report.get("gaps") or {}
    lines = [
        "# Spark Corpus Coverage Report (V4.3.2)",
        "",
        f"Generated: {report.get('generated_at')}",
        "",
        "## Targets",
        "",
    ]
    for key, val in targets.items():
        lines.append(f"- `{key}`: {val}")
    lines.extend(["", "## Progress", ""])
    for key, val in progress.items():
        lines.append(f"- `{key}`: {val}")
    lines.extend(["", "## Gaps (remaining to target)", ""])
    for key, val in gaps.items():
        lines.append(f"- `{key}`: {val}")
    lines.extend(["", "## Tier remaining (unmigrated candidates)", ""])
    for tier, n in (report.get("tier_remaining") or {}).items():
        lines.append(f"- Tier {tier}: {n}")
    lines.append("")
    return "\n".join(lines)


def _confidence_from_row(row: Any) -> float:
    try:
        raw = float(row["confidence"] or 0.55)
    except (TypeError, ValueError):
        raw = 0.55
    return max(0.35, min(0.92, raw if raw > 0 else 0.55))


def map_short_row_to_spark(row: Any) -> dict[str, object] | None:
    """Deterministic short/canon/decision mapping. Returns raw spark dict or None."""
    memory_type = str(row["memory_type"] or "")
    raw = _row_text(row)
    content = clip_spark_content(raw, SHORT_MAX)
    if len(content) < MIN_CONTENT_LEN:
        return None
    certainty = "confirmed" if memory_type in {"decision", "constraint", "preference"} else "tentative"
    if memory_type == "summary" and not bool(int(row["pinned"] or 0)):
        certainty = "tentative"
    return {
        "content": content,
        "lane": infer_lane(memory_type, content),
        "why_keep": f"Migrated from active {memory_type} memory_item #{row['id']}.",
        "worth_reason": "Valuable keeper selected for V4.3.1 spark corpus seeding.",
        "confidence": _confidence_from_row(row),
        "spark_type": TYPE_TO_SPARK.get(memory_type, "observation"),
        "certainty": certainty,
        "sensitivity": "normal",
    }


def should_promote_on_apply(row: Any, spark: dict[str, object], proposed_trust: str) -> bool:
    """Only documented canon/pinned/approved decision policy may promote active."""
    if proposed_trust not in {"active", "pinned"}:
        return False
    memory_type = str(row["memory_type"] or "")
    source = str(row["source"] or "").lower()
    pinned = bool(int(row["pinned"] or 0))
    spark_type = str(spark.get("spark_type") or "")
    certainty = str(spark.get("certainty") or "")
    if proposed_trust == "pinned" and pinned and source == "canon":
        return True
    if memory_type == "decision" and certainty == "confirmed" and spark_type == "decision":
        if pinned or source == "canon":
            return True
    if (
        source == "canon"
        and memory_type in {"decision", "constraint"}
        and certainty == "confirmed"
    ):
        return True
    return False


def build_lineage(
    *,
    memory_item_id: int,
    batch_id: str,
    path: str,
    memory_type: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    lineage: dict[str, object] = {
        "migration": "v4.3.1_spark_corpus",
        "migration_batch_id": batch_id,
        "memory_item_id": memory_item_id,
        "source_memory_item_id": memory_item_id,
        "source_memory_type": memory_type,
        "path": path,
    }
    if extra:
        lineage.update(extra)
    return lineage


def propose_sparks_for_row(
    row: Any,
    *,
    batch_id: str,
    allow_llm: bool = False,
) -> dict[str, object]:
    """Build validated spark proposals for one candidate. No DB writes."""
    memory_type = str(row["memory_type"] or "")
    mid = int(row["id"])
    raw = _row_text(row)
    original_len = len(_normalize_ws(raw))
    proposals: list[dict[str, object]] = []
    errors: list[str] = []
    path = "deterministic_short"

    if original_len > SHORT_MAX and allow_llm:
        import spark_extraction

        path = "llm_extract"
        result = spark_extraction.extract_sparks_from_text(raw)
        if not result.ok or not result.sparks:
            # Ambiguous long rows stay skipped or low-confidence candidate
            short = map_short_row_to_spark(row)
            if short is None:
                return {
                    "memory_item_id": mid,
                    "status": "skipped",
                    "reason": "long_ambiguous",
                    "proposals": [],
                    "errors": list(result.errors),
                }
            short["certainty"] = "tentative"
            short["confidence"] = min(float(short["confidence"]), 0.55)
            path = "short_clip_fallback"
            batch = [short]
        else:
            batch = list(result.sparks)
            # Long LLM output: keep tentative unless already confirmed
            for item in batch:
                if str(item.get("certainty") or "") == "confirmed" and memory_type not in {
                    "decision",
                    "constraint",
                }:
                    item["certainty"] = "tentative"
    elif original_len > SHORT_MAX and not allow_llm:
        short = map_short_row_to_spark(row)
        if short is None:
            return {
                "memory_item_id": mid,
                "status": "skipped",
                "reason": "too_short_after_clip",
                "proposals": [],
                "errors": [],
            }
        short["certainty"] = "tentative"
        short["confidence"] = min(float(short["confidence"]), 0.6)
        path = "short_clip"
        batch = [short]
    else:
        short = map_short_row_to_spark(row)
        if short is None:
            return {
                "memory_item_id": mid,
                "status": "skipped",
                "reason": "too_short",
                "proposals": [],
                "errors": [],
            }
        batch = [short]

    for spark_payload in batch:
        validated = sparks.validate_spark(spark_payload)
        if not validated.ok or validated.spark is None:
            errors.append("; ".join(validated.errors))
            continue
        spark = dict(validated.spark)
        proposals.append(
            {
                "spark": spark,
                "source_memory_item_id": mid,
                "lineage_json": build_lineage(
                    memory_item_id=mid,
                    batch_id=batch_id,
                    path=path,
                    memory_type=memory_type,
                ),
                "path": path,
            }
        )

    if not proposals:
        return {
            "memory_item_id": mid,
            "status": "rejected",
            "reason": "validation_failed",
            "proposals": [],
            "errors": errors,
        }
    return {
        "memory_item_id": mid,
        "status": "proposed",
        "reason": path,
        "proposals": proposals,
        "errors": errors,
    }


def dry_run_extract(
    conn: Any,
    *,
    limit: int = 50,
    allow_llm: bool = False,
    batch_id: str | None = None,
    tiers: frozenset[str] | None = None,
) -> dict[str, object]:
    """Generate validated spark proposals for selected candidates. No writes."""
    batch = batch_id or f"dryrun-{uuid.uuid4().hex[:12]}"
    selection = select_candidates(conn, limit=limit, tiers=tiers)
    proposed = 0
    skipped = 0
    rejected = 0
    items: list[dict[str, object]] = []

    for cand in selection["candidates"]:
        mid = int(cand["memory_item_id"])  # type: ignore[index]
        row = conn.execute(
            """
            SELECT id, memory_type, content, summary, confidence, project_id,
                   status, source, importance, pinned
            FROM memory_items WHERE id = ?
            """,
            (mid,),
        ).fetchone()
        if row is None:
            skipped += 1
            continue
        result = propose_sparks_for_row(row, batch_id=batch, allow_llm=allow_llm)
        status = str(result["status"])
        if status == "proposed":
            proposed += len(result["proposals"])  # type: ignore[arg-type]
        elif status == "rejected":
            rejected += 1
        else:
            skipped += 1
        items.append(
            {
                **result,
                "include_reason": cand.get("include_reason"),
                "proposed_trust": cand.get("proposed_trust"),
            }
        )

    return {
        "generated_at": crowley._now_iso(),
        "dry_run": True,
        "migration_batch_id": batch,
        "candidate_count": selection["included_count"],
        "proposed_spark_count": proposed,
        "skipped": skipped,
        "rejected": rejected,
        "items": items,
        "selection_summary": {
            "include_reason_counts": selection["include_reason_counts"],
            "skip_reason_counts": selection["skip_reason_counts"],
        },
    }


def apply_extract_batch(
    conn: Any,
    *,
    limit: int,
    allow_llm: bool = False,
    batch_id: str | None = None,
    promote_policy: bool = True,
    tiers: frozenset[str] | None = None,
) -> dict[str, object]:
    """Apply a small bounded batch via upsert_spark_with_dedup.

    Requires explicit caller-supplied limit. Default trust_state is candidate;
    promotion only for documented canon/pinned/approved decision policy.
    """
    if limit <= 0:
        raise ValueError("apply requires a positive --limit")
    if limit > DEFAULT_APPLY_LIMIT_CAP:
        raise ValueError(
            f"apply --limit must be <= {DEFAULT_APPLY_LIMIT_CAP} for small batches"
        )

    batch = batch_id or f"apply-{uuid.uuid4().hex[:12]}"
    # Scan without include-limit so already-linked rows are visible for idempotent skips.
    selection = select_candidates(conn, limit=None, tiers=tiers)
    candidates = list(selection["candidates"] or [])
    already_linked_skips = int(
        (selection.get("skip_reason_counts") or {}).get("already_linked", 0)
    )
    # Prefer not-yet-linked candidates up to limit; count prior links as skipped.
    to_apply = candidates[: int(limit)]
    counts = {
        "inserted": 0,
        "linked": 0,
        "merged": 0,
        "promoted": 0,
        "rejected": 0,
        "skipped": already_linked_skips,
    }
    details: list[dict[str, object]] = []
    if already_linked_skips:
        details.append(
            {
                "action": "skipped_already_linked_batch",
                "count": already_linked_skips,
            }
        )

    import spark_lifecycle

    for cand in to_apply:
        mid = int(cand["memory_item_id"])  # type: ignore[index]
        # Idempotency: skip if already linked since selection
        existing = conn.execute(
            "SELECT id FROM sparks WHERE source_memory_item_id = ? LIMIT 1",
            (mid,),
        ).fetchone()
        if existing is not None:
            counts["skipped"] += 1
            details.append({"memory_item_id": mid, "action": "skipped_already_linked"})
            continue

        row = conn.execute(
            """
            SELECT id, memory_type, content, summary, confidence, project_id,
                   status, source, importance, pinned
            FROM memory_items WHERE id = ?
            """,
            (mid,),
        ).fetchone()
        if row is None:
            counts["skipped"] += 1
            continue

        result = propose_sparks_for_row(row, batch_id=batch, allow_llm=allow_llm)
        if result["status"] != "proposed":
            if result["status"] == "rejected":
                counts["rejected"] += 1
            else:
                counts["skipped"] += 1
            details.append(
                {
                    "memory_item_id": mid,
                    "action": str(result["status"]),
                    "reason": result.get("reason"),
                    "errors": result.get("errors"),
                }
            )
            continue

        project_id = int(row["project_id"]) if row["project_id"] is not None else None
        proposed_trust = str(cand.get("proposed_trust") or "candidate")

        for proposal in result["proposals"]:  # type: ignore[attr-defined]
            spark = dict(proposal["spark"])  # type: ignore[index]
            lineage = dict(proposal["lineage_json"])  # type: ignore[index]
            trust_state = "candidate"
            upsert = sparks.upsert_spark_with_dedup(
                conn,
                spark,
                source_memory_item_id=mid,
                project_id=project_id,
                trust_state=trust_state,
                lineage_json=lineage,
            )
            action = upsert.action
            counts[action] = counts.get(action, 0) + 1
            detail: dict[str, object] = {
                "memory_item_id": mid,
                "spark_id": upsert.spark_id,
                "action": action,
                "trust_state": trust_state,
            }

            if (
                promote_policy
                and action == "inserted"
                and should_promote_on_apply(row, spark, proposed_trust)
            ):
                # Pinned canon → pinned; otherwise active via lifecycle
                if proposed_trust == "pinned":
                    conn.execute(
                        """
                        UPDATE sparks
                        SET trust_state = 'pinned', updated_at = ?
                        WHERE id = ?
                        """,
                        (crowley._now_iso(), upsert.spark_id),
                    )
                    counts["promoted"] += 1
                    detail["trust_state"] = "pinned"
                    detail["promoted"] = True
                else:
                    promo = spark_lifecycle.promote_spark_to_active(
                        conn,
                        upsert.spark_id,
                        manual=True,
                        promoted_by="v4.3.1_migration",
                        promotion_source="corpus_migration",
                    )
                    if promo.ok:
                        counts["promoted"] += 1
                        detail["trust_state"] = "active"
                        detail["promoted"] = True
            details.append(detail)

    return {
        "generated_at": crowley._now_iso(),
        "dry_run": False,
        "migration_batch_id": batch,
        "limit": limit,
        "candidate_count": selection["included_count"],
        "tiers": sorted(tiers) if tiers else sorted(MIGRATE_TIERS),
        **counts,
        "details": details,
        "memory_items_mutated": False,
    }


# --- V4.3.2 multi-batch expansion -------------------------------------------

DRY_RUN_ARTIFACT_NAME = "memory_to_spark_dryrun.json"
DRY_RUN_MAX_AGE_SECONDS = 6 * 60 * 60  # 6 hours


def _corpus_counts(conn: Any) -> dict[str, int]:
    def _count(sql: str) -> int:
        return int(conn.execute(sql).fetchone()["n"])

    return {
        "sparks_total": _count("SELECT COUNT(*) AS n FROM sparks"),
        "sparks_active": _count(
            "SELECT COUNT(*) AS n FROM sparks WHERE trust_state = 'active'"
        ),
        "sparks_pinned": _count(
            "SELECT COUNT(*) AS n FROM sparks WHERE trust_state = 'pinned'"
        ),
        "sparks_with_lineage": _count(
            "SELECT COUNT(*) AS n FROM sparks WHERE source_memory_item_id IS NOT NULL"
        ),
        "memory_items_total": _count("SELECT COUNT(*) AS n FROM memory_items"),
        "memory_items_active": _count(
            "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
        ),
    }


def dry_run_artifact_path(root: Any | None = None) -> Any:
    from pathlib import Path

    base = Path(root) if root is not None else Path(__file__).resolve().parent
    return base / "docs" / "artifacts" / DRY_RUN_ARTIFACT_NAME


def check_dry_run_gate(
    *,
    reviewed: bool = False,
    artifact_path: Any | None = None,
    max_age_seconds: int = DRY_RUN_MAX_AGE_SECONDS,
) -> tuple[bool, str]:
    """Return (ok, reason). Apply requires recent dry-run artifact or --reviewed."""
    if reviewed:
        return True, "explicit_reviewed_flag"
    path = artifact_path or dry_run_artifact_path()
    from pathlib import Path

    path = Path(path)
    if not path.is_file():
        return False, f"missing_dry_run_artifact:{path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"invalid_dry_run_artifact:{exc}"
    if not payload.get("dry_run"):
        return False, "artifact_not_dry_run"
    generated = str(payload.get("generated_at") or "")
    ts = crowley._parse_memory_timestamp(generated)
    if ts is None:
        return False, "artifact_missing_generated_at"
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (now - ts).total_seconds()
    if age > max_age_seconds:
        return False, f"dry_run_artifact_stale:{int(age)}s"
    return True, f"dry_run_artifact_ok:{path.name}"


def apply_multi_batch(
    conn: Any,
    *,
    limit: int,
    max_batches: int = 1,
    allow_llm: bool = False,
    batch_id_prefix: str | None = None,
    promote_policy: bool = False,
    tiers: frozenset[str] | None = None,
    reviewed: bool = False,
    artifact_path: Any | None = None,
    require_dry_run_gate: bool = True,
) -> dict[str, object]:
    """Apply up to max_batches capped batches. No memory_items archive/delete."""
    if limit <= 0:
        raise ValueError("apply requires a positive --limit")
    if limit > DEFAULT_APPLY_LIMIT_CAP:
        raise ValueError(
            f"apply --limit must be <= {DEFAULT_APPLY_LIMIT_CAP} per batch"
        )
    if max_batches <= 0:
        raise ValueError("max_batches must be positive")

    if require_dry_run_gate:
        ok, reason = check_dry_run_gate(
            reviewed=reviewed, artifact_path=artifact_path
        )
        if not ok:
            raise ValueError(
                f"apply refused: {reason} "
                "(run dry-run --write first or pass reviewed=True / --reviewed)"
            )
        gate_reason = reason
    else:
        gate_reason = "gate_bypassed"

    before = _corpus_counts(conn)
    prefix = batch_id_prefix or f"v432-{uuid.uuid4().hex[:8]}"
    batches: list[dict[str, object]] = []
    totals = {
        "inserted": 0,
        "linked": 0,
        "merged": 0,
        "promoted": 0,
        "rejected": 0,
        "skipped": 0,
    }

    for index in range(int(max_batches)):
        batch_id = f"{prefix}-b{index + 1}"
        report = apply_extract_batch(
            conn,
            limit=limit,
            allow_llm=allow_llm,
            batch_id=batch_id,
            promote_policy=promote_policy,
            tiers=tiers,
        )
        batches.append(report)
        for key in totals:
            totals[key] += int(report.get(key, 0))
        # Stop early if nothing new inserted/linked/merged
        if (
            int(report.get("inserted", 0))
            + int(report.get("linked", 0))
            + int(report.get("merged", 0))
            == 0
        ):
            break

    after = _corpus_counts(conn)
    return {
        "generated_at": crowley._now_iso(),
        "dry_run": False,
        "gate": gate_reason,
        "batch_id_prefix": prefix,
        "max_batches": max_batches,
        "batches_run": len(batches),
        "limit_per_batch": limit,
        "tiers": sorted(tiers) if tiers else sorted(MIGRATE_TIERS),
        "before": before,
        "after": after,
        "totals": totals,
        "batches": batches,
        "memory_items_mutated": False,
        "memory_items_archived": False,
        "memory_items_deleted": False,
    }


# --- V4.3.2 T3 promotion review ---------------------------------------------

PROMOTION_REVIEW_MIN_CONFIDENCE = 0.65
PROMOTION_APPLY_LIMIT_CAP = 50


def _load_spark_with_source(conn: Any, spark_id: int | None = None) -> list[Any]:
    sql = """
        SELECT s.*, mi.memory_type AS src_memory_type, mi.source AS src_source,
               mi.pinned AS src_pinned, mi.importance AS src_importance,
               mi.content AS src_content, mi.summary AS src_summary
        FROM sparks s
        LEFT JOIN memory_items mi ON mi.id = s.source_memory_item_id
        WHERE s.trust_state = 'candidate'
    """
    params: tuple = ()
    if spark_id is not None:
        sql += " AND s.id = ?"
        params = (int(spark_id),)
    sql += " ORDER BY s.id ASC"
    return list(conn.execute(sql, params).fetchall())


def evaluate_promotion_review(row: Any) -> dict[str, object]:
    """Deterministic promote/hold decision for one candidate spark."""
    content = str(row["content"] or "")
    spark_type = str(row["spark_type"] or "")
    certainty = str(row["certainty"] or "")
    confidence = float(row["confidence"] or row["base_confidence"] or 0)
    sensitivity = str(row["sensitivity"] or "normal")
    src_type = str(row["src_memory_type"] or "")
    src_source = str(row["src_source"] or "").lower()
    src_pinned = bool(int(row["src_pinned"] or 0))
    src_importance = int(row["src_importance"] or 0)

    # Synthetic row for tier classification from source memory
    class _Src:
        def __getitem__(self, key: str) -> object:
            mapping = {
                "memory_type": src_type,
                "source": src_source,
                "pinned": 1 if src_pinned else 0,
                "importance": src_importance,
                "content": row["src_content"] or content,
                "summary": row["src_summary"] or "",
            }
            return mapping[key]

    src_row = _Src()
    tier = classify_tier(src_row) if src_type else TIER_D

    hold_reason: str | None = None
    if sensitivity != "normal":
        hold_reason = "sensitive"
    elif sparks._spark_content_security_errors(content):
        hold_reason = "security_failed"
    elif _is_ticket_chatter(content) or _is_ticket_chatter(str(row["src_content"] or "")):
        hold_reason = "ticket_chatter"
    elif _contains_any(content, _SIDEQUEST_MARKERS):
        hold_reason = "sidequest_noise"
    elif certainty != "confirmed":
        hold_reason = "not_confirmed"
    elif confidence < PROMOTION_REVIEW_MIN_CONFIDENCE:
        hold_reason = "low_confidence"
    elif spark_type not in {"decision", "fact", "intent"}:
        hold_reason = "spark_type_not_durable"
    elif tier == TIER_D:
        hold_reason = "tier_d_source"
    elif src_type not in {"decision", "constraint", "preference", "lesson", "summary"}:
        hold_reason = "source_type_not_durable"
    elif tier == TIER_C and not (src_pinned or src_source == "canon"):
        hold_reason = "tier_c_needs_review"
    elif src_source in {"codex", "cursor"} and not (src_pinned or src_source == "canon"):
        # Agent-authored decisions without canon/pin stay held (often ticket chatter)
        if _is_ticket_chatter(content) or "approve" in content.lower() or "deny" in content.lower():
            hold_reason = "ticket_chatter"
        elif tier != TIER_A:
            hold_reason = "agent_decision_hold"

    if hold_reason:
        return {
            "action": "hold",
            "reason": hold_reason,
            "proposed_trust": "candidate",
            "tier": tier,
        }

    # Promote path
    if src_pinned and src_source == "canon":
        return {
            "action": "promote",
            "reason": "tier_A_pinned",
            "proposed_trust": "pinned",
            "tier": tier,
        }
    if tier == TIER_A and certainty == "confirmed":
        return {
            "action": "promote",
            "reason": "tier_A_active",
            "proposed_trust": "active",
            "tier": tier,
        }
    if (
        tier == TIER_B
        and certainty == "confirmed"
        and spark_type in {"decision", "fact", "intent"}
        and (
            src_source in {"canon", "manual", "consolidation", "portable_terminal"}
            or src_pinned
        )
    ):
        return {
            "action": "promote",
            "reason": "tier_B_active",
            "proposed_trust": "active",
            "tier": tier,
        }
    return {
        "action": "hold",
        "reason": "policy_no_match",
        "proposed_trust": "candidate",
        "tier": tier,
    }


def review_migrated_sparks(
    conn: Any,
    *,
    limit: int | None = None,
    whitelist_ids: frozenset[int] | None = None,
) -> dict[str, object]:
    """Dry-run promotion review. Never writes."""
    rows = _load_spark_with_source(conn)
    promote: list[dict[str, object]] = []
    hold: list[dict[str, object]] = []
    reason_counts: dict[str, int] = {}

    for row in rows:
        spark_id = int(row["id"])
        decision = evaluate_promotion_review(row)
        if whitelist_ids and spark_id in whitelist_ids:
            decision = {
                "action": "promote",
                "reason": "manual_whitelist",
                "proposed_trust": "active",
                "tier": decision.get("tier") or TIER_B,
            }
        entry = {
            "spark_id": spark_id,
            "source_memory_item_id": row["source_memory_item_id"],
            "spark_type": row["spark_type"],
            "certainty": row["certainty"],
            "confidence": float(row["confidence"] or 0),
            "lane": row["lane"],
            "preview": str(row["content"] or "")[:120],
            "src_memory_type": row["src_memory_type"],
            "src_source": row["src_source"],
            **decision,
        }
        reason = str(decision["reason"])
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if decision["action"] == "promote":
            promote.append(entry)
        else:
            hold.append(entry)

    if limit is not None:
        promote = promote[: int(limit)]

    return {
        "generated_at": crowley._now_iso(),
        "dry_run": True,
        "scanned": len(rows),
        "promote_count": len(promote),
        "hold_count": len(hold),
        "reason_counts": dict(sorted(reason_counts.items())),
        "promote": promote,
        "hold_sample": hold[:30],
        "policy": {
            "min_confidence": PROMOTION_REVIEW_MIN_CONFIDENCE,
            "ticket_chatter_held": True,
            "no_broad_auto_promote": True,
        },
    }


def apply_promotion_review(
    conn: Any,
    *,
    limit: int,
    whitelist_ids: frozenset[int] | None = None,
) -> dict[str, object]:
    """Apply bounded promotion from review policy. Preserves lineage."""
    if limit <= 0:
        raise ValueError("promotion apply requires a positive --limit")
    if limit > PROMOTION_APPLY_LIMIT_CAP:
        raise ValueError(
            f"promotion --limit must be <= {PROMOTION_APPLY_LIMIT_CAP}"
        )

    import spark_lifecycle

    review = review_migrated_sparks(conn, limit=limit, whitelist_ids=whitelist_ids)
    before = _corpus_counts(conn)
    promoted = 0
    pinned = 0
    held = 0
    details: list[dict[str, object]] = []

    for entry in review["promote"]:
        spark_id = int(entry["spark_id"])  # type: ignore[index]
        proposed = str(entry["proposed_trust"])
        row = conn.execute(
            "SELECT id, source_memory_item_id, lineage_json, trust_state FROM sparks WHERE id = ?",
            (spark_id,),
        ).fetchone()
        if row is None or str(row["trust_state"]) != "candidate":
            held += 1
            details.append({"spark_id": spark_id, "action": "skipped_state"})
            continue
        source_id = row["source_memory_item_id"]
        lineage_before = row["lineage_json"]

        if proposed == "pinned":
            conn.execute(
                """
                UPDATE sparks
                SET trust_state = 'pinned', updated_at = ?,
                    lineage_json = ?
                WHERE id = ?
                """,
                (
                    crowley._now_iso(),
                    spark_lifecycle._merge_spark_lineage(
                        row,
                        {
                            "promoted_by": "v4.3.2_promotion_review",
                            "promotion_source": "corpus_promotion_review",
                            "promotion_reason": entry.get("reason"),
                        },
                    ),
                    spark_id,
                ),
            )
            pinned += 1
            promoted += 1
            action = "pinned"
        else:
            result = spark_lifecycle.promote_spark_to_active(
                conn,
                spark_id,
                manual=True,
                promoted_by="v4.3.2_promotion_review",
                promotion_source="corpus_promotion_review",
            )
            if not result.ok:
                held += 1
                details.append(
                    {
                        "spark_id": spark_id,
                        "action": "hold",
                        "reason": result.reason,
                    }
                )
                continue
            promoted += 1
            action = "active"

        # Verify lineage + source preserved
        after_row = conn.execute(
            "SELECT source_memory_item_id, lineage_json, trust_state FROM sparks WHERE id = ?",
            (spark_id,),
        ).fetchone()
        details.append(
            {
                "spark_id": spark_id,
                "action": action,
                "reason": entry.get("reason"),
                "source_memory_item_id": after_row["source_memory_item_id"],
                "source_preserved": after_row["source_memory_item_id"] == source_id,
                "lineage_preserved": bool(after_row["lineage_json"]),
            }
        )
        _ = lineage_before

    after = _corpus_counts(conn)
    return {
        "generated_at": crowley._now_iso(),
        "dry_run": False,
        "limit": limit,
        "before": before,
        "after": after,
        "promoted": promoted,
        "pinned": pinned,
        "held": held,
        "details": details,
        "review_summary": {
            "promote_count": review["promote_count"],
            "hold_count": review["hold_count"],
            "reason_counts": review["reason_counts"],
        },
    }


# --- V4.3.2 T4 legacy demotion / archive ------------------------------------

ARCHIVE_DRY_RUN_ARTIFACT = "memory_items_demotion_dryrun.json"
ARCHIVE_APPLY_LIMIT_CAP = 200
DEMOTE_STATUSES = frozenset({"archived", "stale"})


def _parse_linked_ticket_ids(raw: object) -> list[int]:
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    out: list[int] = []
    for item in parsed:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _has_active_or_pinned_spark(conn: Any, memory_item_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 AS ok FROM sparks
        WHERE source_memory_item_id = ?
          AND trust_state IN ('active', 'pinned')
        LIMIT 1
        """,
        (int(memory_item_id),),
    ).fetchone()
    return row is not None


def _has_any_spark_lineage(conn: Any, memory_item_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 AS ok FROM sparks
        WHERE source_memory_item_id = ?
        LIMIT 1
        """,
        (int(memory_item_id),),
    ).fetchone()
    return row is not None


def evaluate_demotion(row: Any, conn: Any) -> dict[str, object]:
    """Decide archive/stale/protect/skip for one active memory_item."""
    mid = int(row["id"])
    status = str(row["status"] or "")
    if status != "active":
        return {"action": "skip", "reason": f"status_{status}", "new_status": None}

    memory_type = str(row["memory_type"] or "")
    source = str(row["source"] or "").lower()
    pinned = bool(int(row["pinned"] or 0))
    text = _row_text(row)
    tickets = _parse_linked_ticket_ids(row["linked_ticket_ids_json"])
    has_active_spark = _has_active_or_pinned_spark(conn, mid)
    has_lineage = _has_any_spark_lineage(conn, mid)
    tier = classify_tier(row)

    protected = False
    protect_reason = None
    if pinned or source == "canon":
        protected = True
        protect_reason = "pinned_or_canon"
    elif tickets:
        protected = True
        protect_reason = "ticket_linked"

    if protected and not has_active_spark:
        return {
            "action": "protect",
            "reason": protect_reason,
            "new_status": None,
            "tier": tier,
            "has_lineage": has_lineage,
            "has_active_spark": False,
        }

    # Represented by active/pinned spark → safe to archive receipt
    if has_active_spark:
        return {
            "action": "archive",
            "reason": "represented_by_active_spark",
            "new_status": "archived",
            "tier": tier,
            "has_lineage": True,
            "has_active_spark": True,
        }

    # Any spark lineage → mark stale (still recoverable; not primary cognitive)
    if has_lineage:
        return {
            "action": "stale",
            "reason": "has_spark_lineage_candidate",
            "new_status": "stale",
            "tier": tier,
            "has_lineage": True,
            "has_active_spark": False,
        }

    # Deterministic low-value / noise without lineage
    if tier == TIER_D:
        if (
            _is_ticket_chatter(text)
            or _contains_any(text, _HANDOFF_MARKERS)
            or _contains_any(text, _QA_NOISE_MARKERS)
            or _contains_any(text, _SIDEQUEST_MARKERS)
            or memory_type in {"event", "qa_result", "bug"}
            or source in {"cursor", "codex", "agent_handoff"}
        ):
            return {
                "action": "archive",
                "reason": "tier_d_noise",
                "new_status": "archived",
                "tier": tier,
                "has_lineage": False,
                "has_active_spark": False,
            }

    return {
        "action": "skip",
        "reason": "no_demotion_rule",
        "new_status": None,
        "tier": tier,
        "has_lineage": has_lineage,
        "has_active_spark": has_active_spark,
    }


def review_memory_demotion(
    conn: Any,
    *,
    limit: int | None = None,
    scan_limit: int | None = None,
) -> dict[str, object]:
    """Dry-run demotion review. Never writes or deletes."""
    sql = """
        SELECT id, memory_type, content, summary, status, source, importance,
               pinned, linked_ticket_ids_json, created_at
        FROM memory_items
        WHERE status = 'active'
        ORDER BY pinned DESC, importance DESC, id DESC
    """
    if scan_limit is not None:
        rows = list(conn.execute(sql + " LIMIT ?", (int(scan_limit),)).fetchall())
    else:
        rows = list(conn.execute(sql).fetchall())

    archive: list[dict[str, object]] = []
    stale: list[dict[str, object]] = []
    protect: list[dict[str, object]] = []
    skipped = 0
    reason_counts: dict[str, int] = {}

    for row in rows:
        decision = evaluate_demotion(row, conn)
        reason = str(decision["reason"])
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        entry = {
            "memory_item_id": int(row["id"]),
            "memory_type": row["memory_type"],
            "source": row["source"],
            "pinned": bool(int(row["pinned"] or 0)),
            "preview": _normalize_ws(_row_text(row))[:100],
            **decision,
        }
        action = str(decision["action"])
        if action == "archive":
            archive.append(entry)
        elif action == "stale":
            stale.append(entry)
        elif action == "protect":
            protect.append(entry)
        else:
            skipped += 1

    changes = archive + stale
    if limit is not None:
        changes = changes[: int(limit)]
        archive = [e for e in changes if e["action"] == "archive"]
        stale = [e for e in changes if e["action"] == "stale"]

    before = {
        "memory_items_active": int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
            ).fetchone()["n"]
        ),
        "memory_items_archived": int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'archived'"
            ).fetchone()["n"]
        ),
        "memory_items_stale": int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'stale'"
            ).fetchone()["n"]
        ),
        "memory_items_total": int(
            conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()["n"]
        ),
    }
    return {
        "generated_at": crowley._now_iso(),
        "dry_run": True,
        "scanned": len(rows),
        "archive_count": len(archive),
        "stale_count": len(stale),
        "protect_count": len(protect),
        "skipped": skipped,
        "reason_counts": dict(sorted(reason_counts.items())),
        "before": before,
        "archive": archive,
        "stale": stale,
        "protect_sample": protect[:25],
        "policy": {
            "no_delete": True,
            "protect_pinned_canon_ticket_linked": True,
            "require_active_spark_to_archive_protected": True,
        },
    }


def check_demotion_dry_run_gate(
    *,
    reviewed: bool = False,
    artifact_path: Any | None = None,
    max_age_seconds: int = DRY_RUN_MAX_AGE_SECONDS,
) -> tuple[bool, str]:
    if reviewed:
        return True, "explicit_reviewed_flag"
    from pathlib import Path

    path = Path(artifact_path) if artifact_path else (
        Path(__file__).resolve().parent / "docs" / "artifacts" / ARCHIVE_DRY_RUN_ARTIFACT
    )
    if not path.is_file():
        return False, f"missing_demotion_dry_run:{path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"invalid_demotion_dry_run:{exc}"
    if not payload.get("dry_run"):
        return False, "artifact_not_dry_run"
    generated = str(payload.get("generated_at") or "")
    ts = crowley._parse_memory_timestamp(generated)
    if ts is None:
        return False, "artifact_missing_generated_at"
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (now - ts).total_seconds()
    if age > max_age_seconds:
        return False, f"demotion_dry_run_stale:{int(age)}s"
    return True, f"demotion_dry_run_ok:{path.name}"


def apply_memory_demotion(
    conn: Any,
    *,
    limit: int,
    reviewed: bool = False,
    artifact_path: Any | None = None,
    require_dry_run_gate: bool = True,
) -> dict[str, object]:
    """Archive/stale selected memory_items. Never deletes rows."""
    if limit <= 0:
        raise ValueError("demotion apply requires a positive --limit")
    if limit > ARCHIVE_APPLY_LIMIT_CAP:
        raise ValueError(
            f"demotion --limit must be <= {ARCHIVE_APPLY_LIMIT_CAP}"
        )
    if require_dry_run_gate:
        ok, reason = check_demotion_dry_run_gate(
            reviewed=reviewed, artifact_path=artifact_path
        )
        if not ok:
            raise ValueError(
                f"demotion apply refused: {reason} "
                "(run dry-run --write first or pass --reviewed)"
            )
        gate = reason
    else:
        gate = "gate_bypassed"

    review = review_memory_demotion(conn, limit=limit)
    before_total = int(
        conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()["n"]
    )
    changed: list[dict[str, object]] = []
    archived = 0
    staled = 0
    protected = 0

    for entry in list(review["archive"]) + list(review["stale"]):
        mid = int(entry["memory_item_id"])  # type: ignore[index]
        # Re-evaluate at apply time for safety
        row = conn.execute(
            """
            SELECT id, memory_type, content, summary, status, source, importance,
                   pinned, linked_ticket_ids_json
            FROM memory_items WHERE id = ?
            """,
            (mid,),
        ).fetchone()
        if row is None:
            continue
        decision = evaluate_demotion(row, conn)
        if decision["action"] == "protect":
            protected += 1
            changed.append(
                {
                    "memory_item_id": mid,
                    "action": "protect",
                    "reason": decision["reason"],
                }
            )
            continue
        new_status = decision.get("new_status")
        if new_status not in DEMOTE_STATUSES:
            continue
        # Stamp metadata
        meta_raw = None
        try:
            # metadata may not be in SELECT; fetch
            meta_row = conn.execute(
                "SELECT metadata_json FROM memory_items WHERE id = ?", (mid,)
            ).fetchone()
            meta_raw = meta_row["metadata_json"] if meta_row else None
        except Exception:  # noqa: BLE001
            meta_raw = None
        metadata: dict[str, object] = {}
        if meta_raw:
            try:
                parsed = json.loads(str(meta_raw))
                if isinstance(parsed, dict):
                    metadata = parsed
            except json.JSONDecodeError:
                metadata = {}
        metadata["corpus_demotion"] = {
            "at": crowley._now_iso(),
            "reason": decision["reason"],
            "from_status": "active",
            "to_status": new_status,
            "ladder": "v4.3.2",
        }
        conn.execute(
            """
            UPDATE memory_items
            SET status = ?, updated_at = ?, metadata_json = ?
            WHERE id = ? AND status = 'active'
            """,
            (
                str(new_status),
                crowley._now_iso(),
                json.dumps(metadata, sort_keys=True, ensure_ascii=False),
                mid,
            ),
        )
        if new_status == "archived":
            archived += 1
        else:
            staled += 1
        changed.append(
            {
                "memory_item_id": mid,
                "action": str(decision["action"]),
                "reason": decision["reason"],
                "new_status": new_status,
            }
        )

    after_total = int(
        conn.execute("SELECT COUNT(*) AS n FROM memory_items").fetchone()["n"]
    )
    if after_total != before_total:
        raise RuntimeError("demotion must not delete memory_items")

    after = {
        "memory_items_active": int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
            ).fetchone()["n"]
        ),
        "memory_items_archived": int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'archived'"
            ).fetchone()["n"]
        ),
        "memory_items_stale": int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'stale'"
            ).fetchone()["n"]
        ),
        "memory_items_total": after_total,
    }
    return {
        "generated_at": crowley._now_iso(),
        "dry_run": False,
        "gate": gate,
        "limit": limit,
        "before": review["before"],
        "after": after,
        "archived": archived,
        "staled": staled,
        "protected": protected,
        "changed": changed,
        "memory_items_deleted": False,
        "rows_deleted": 0,
    }


def build_inventory(conn: Any | None = None) -> dict[str, object]:
    """Read-only corpus inventory for T1."""
    owns = conn is None
    if owns:
        conn = crowley.connect_db()
    assert conn is not None
    try:
        def _count(sql: str, params: tuple = ()) -> int:
            row = conn.execute(sql, params).fetchone()
            return int(row["n"] if row is not None else 0)

        def _group(sql: str) -> list[dict[str, object]]:
            return [dict(r) for r in conn.execute(sql).fetchall()]

        tables = {
            "memories": _count("SELECT COUNT(*) AS n FROM memories"),
            "memory_items": _count("SELECT COUNT(*) AS n FROM memory_items"),
            "sparks": _count("SELECT COUNT(*) AS n FROM sparks"),
            "spark_links": _count("SELECT COUNT(*) AS n FROM spark_links"),
            "patterns": _count("SELECT COUNT(*) AS n FROM patterns"),
        }
        active_memory_items = _count(
            "SELECT COUNT(*) AS n FROM memory_items WHERE status = 'active'"
        )
        sparks_total = tables["sparks"]
        active_sparks = _count(
            "SELECT COUNT(*) AS n FROM sparks WHERE trust_state = 'active'"
        )
        pinned_sparks = _count(
            "SELECT COUNT(*) AS n FROM sparks WHERE trust_state = 'pinned'"
        )
        active_without_lineage = _count(
            """
            SELECT COUNT(*) AS n FROM memory_items mi
            WHERE mi.status = 'active'
              AND NOT EXISTS (
                SELECT 1 FROM sparks s WHERE s.source_memory_item_id = mi.id
              )
            """
        )
        by_type = _group(
            """
            SELECT memory_type, COUNT(*) AS n FROM memory_items
            GROUP BY memory_type ORDER BY n DESC
            """
        )
        by_status = _group(
            """
            SELECT status, COUNT(*) AS n FROM memory_items
            GROUP BY status ORDER BY n DESC
            """
        )
        by_source = _group(
            """
            SELECT source, COUNT(*) AS n FROM memory_items
            GROUP BY source ORDER BY n DESC LIMIT 30
            """
        )
        by_importance = _group(
            """
            SELECT importance, COUNT(*) AS n FROM memory_items
            GROUP BY importance ORDER BY importance DESC
            """
        )
        by_pinned = _group(
            """
            SELECT pinned, COUNT(*) AS n FROM memory_items
            GROUP BY pinned ORDER BY pinned DESC
            """
        )
        sparks_by_trust = _group(
            """
            SELECT trust_state, COUNT(*) AS n FROM sparks
            GROUP BY trust_state ORDER BY n DESC
            """
        )
        sparks_by_lane = _group(
            """
            SELECT lane, COUNT(*) AS n FROM sparks
            GROUP BY lane ORDER BY n DESC
            """
        )
        high_value_candidates = _count(
            f"""
            SELECT COUNT(*) AS n FROM memory_items
            WHERE status = 'active'
              AND (
                pinned = 1
                OR importance >= {HIGH_IMPORTANCE_MIN}
                OR memory_type IN ('decision','constraint','lesson','preference')
                OR (memory_type = 'summary' AND source = 'canon')
              )
              AND NOT EXISTS (
                SELECT 1 FROM sparks s WHERE s.source_memory_item_id = memory_items.id
              )
            """
        )
        cold_start = active_sparks + pinned_sparks == 0

        return {
            "generated_at": crowley._now_iso(),
            "db_path": str(crowley.get_db_path()),
            "read_only": True,
            "tables": tables,
            "memory_items_total": tables["memory_items"],
            "memory_items_active": active_memory_items,
            "sparks_total": sparks_total,
            "sparks_active": active_sparks,
            "sparks_pinned": pinned_sparks,
            "active_memory_items_without_spark_lineage": active_without_lineage,
            "high_value_candidates_without_spark": high_value_candidates,
            "memory_items_by_type": by_type,
            "memory_items_by_status": by_status,
            "memory_items_by_source": by_source,
            "memory_items_by_importance": by_importance,
            "memory_items_by_pinned": by_pinned,
            "sparks_by_trust_state": sparks_by_trust,
            "sparks_by_lane": sparks_by_lane,
            "cold_start_retrieval": cold_start,
            "policy": {
                "living_store": "sparks",
                "receipts_fallback": "memory_items",
                "no_bulk_dump": True,
                "no_memory_items_delete": True,
                "migrate_types": sorted(MIGRATE_TYPES),
            },
        }
    finally:
        if owns:
            conn.close()


def format_candidate_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Memory → Spark Candidate Review (dry-run)",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Scanned: {report.get('scanned')} · Included: {report.get('included_count')} · "
        f"Skipped: {report.get('skipped_count')}",
        f"Allowed tiers: {report.get('allowed_tiers')}",
        "",
        "## Tier remaining",
        "",
    ]
    for tier, n in (report.get("tier_remaining") or {}).items():
        lines.append(f"- Tier {tier}: {n}")
    lines.extend(["", "## Include reason counts", ""])
    for reason, n in (report.get("include_reason_counts") or {}).items():
        lines.append(f"- `{reason}`: {n}")
    lines.extend(["", "## Skip reason counts", ""])
    for reason, n in (report.get("skip_reason_counts") or {}).items():
        lines.append(f"- `{reason}`: {n}")
    lines.extend(["", "## Candidates", ""])
    for cand in report.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        lines.append(
            f"- #{cand.get('memory_item_id')} [T{cand.get('tier')}/{cand.get('memory_type')}] "
            f"trust={cand.get('proposed_trust')} reason={cand.get('include_reason')} "
            f"— {cand.get('preview')}"
        )
    lines.append("")
    return "\n".join(lines)
