"""V4 T15/T16 — spark confidence decay (read-time) and lifecycle maintenance."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

import patterns
from memory_tiers import MIN_CONFIDENCE

SPARK_DECAY_HALF_LIFE_DAYS = 30
STALE_INACTIVITY_DAYS = 60
STALE_MAX_ACCESS_COUNT = 0
MAINTENANCE_STALE_FROM = frozenset({"active", "candidate"})
SPARK_SEED_TRUST_STATE = "candidate"
PROMOTION_MIN_CONFIDENCE = 0.65
AUTO_PROMOTE_CERTAINTIES = frozenset({"confirmed"})
MANUAL_PROMOTE_TRUST_FROM = frozenset({"candidate"})
NON_PROMOTABLE_TRUST_STATES = frozenset({"pinned", "active", "stale", "rejected"})


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def time_decay_factor(days_since_last_access: float) -> float:
    """Halve effective confidence every 30 days since last access."""
    days = max(0.0, float(days_since_last_access))
    return 0.5 ** (days / SPARK_DECAY_HALF_LIFE_DAYS)


def days_since_last_access(
    row: sqlite3.Row,
    *,
    now: datetime | None = None,
) -> float:
    """Days since last_accessed_at when present, otherwise created_at."""
    import crowley

    ref = row["last_accessed_at"] or row["created_at"]
    ts = crowley._parse_memory_timestamp(str(ref))
    if ts is None:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now_dt = now or datetime.now(timezone.utc)
    return max(0.0, (now_dt - ts).total_seconds() / 86400.0)


def active_pattern_spark_ids(conn: sqlite3.Connection) -> frozenset[int]:
    """Spark ids referenced by active patterns."""
    rows = conn.execute(
        """
        SELECT source_spark_ids_json
        FROM patterns
        WHERE trust_state = ?
        """,
        (patterns.PATTERN_ACTIVE_TRUST_STATE,),
    ).fetchall()
    ids: set[int] = set()
    for row in rows:
        raw = row["source_spark_ids_json"]
        if not raw:
            continue
        try:
            parsed = json.loads(str(raw))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list):
            continue
        for item in parsed:
            try:
                ids.add(int(item))
            except (TypeError, ValueError):
                continue
    return frozenset(ids)


def compute_live_confidence(
    base_confidence: float,
    days_since_last_access: float,
    *,
    pattern_participant: bool = False,
) -> float:
    """Read-time confidence from base_confidence decay and optional pattern boost."""
    base = _clamp01(float(base_confidence))
    decayed = base * time_decay_factor(days_since_last_access)
    if pattern_participant:
        decayed = min(base, decayed + patterns.PATTERN_LIFECYCLE_BOOST)
    return max(MIN_CONFIDENCE, _clamp01(decayed))


def live_confidence_for_spark(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    pattern_spark_ids: frozenset[int] | None = None,
    now: datetime | None = None,
) -> float:
    """Compute live confidence for a spark row without persisting it."""
    spark_id = int(row["id"])
    if pattern_spark_ids is None:
        pattern_spark_ids = active_pattern_spark_ids(conn)
    return compute_live_confidence(
        float(row["base_confidence"]),
        days_since_last_access(row, now=now),
        pattern_participant=spark_id in pattern_spark_ids,
    )


@dataclass(frozen=True)
class PromotionDecision:
    eligible: bool
    reason: str


@dataclass(frozen=True)
class PromotionResult:
    ok: bool
    spark_id: int
    from_state: str
    to_state: str
    reason: str
    dry_run: bool


@dataclass(frozen=True)
class SparkMaintenanceResult:
    ok: bool
    dry_run: bool
    stale_candidates: list[int] = field(default_factory=list)
    rejected_candidates: list[int] = field(default_factory=list)
    promotion_candidates: list[int] = field(default_factory=list)
    stale_applied: int = 0
    rejected_applied: int = 0
    promotions_applied: int = 0


def evaluate_promotion_eligibility(
    row: sqlite3.Row,
    *,
    manual: bool = False,
) -> PromotionDecision:
    """Return whether a spark may promote candidate → active."""
    import sparks

    trust_state = str(row["trust_state"])
    if trust_state in NON_PROMOTABLE_TRUST_STATES:
        return PromotionDecision(eligible=False, reason=trust_state)
    if trust_state not in MANUAL_PROMOTE_TRUST_FROM:
        return PromotionDecision(eligible=False, reason="wrong_state")

    sensitivity = str(row["sensitivity"] or "normal")
    if sensitivity != "normal":
        return PromotionDecision(eligible=False, reason="sensitive")

    content = str(row["content"] or "")
    if sparks._spark_content_security_errors(content):
        return PromotionDecision(eligible=False, reason="security_failed")

    if manual:
        return PromotionDecision(eligible=True, reason="manual_ok")

    certainty = str(row["certainty"] or sparks.SPARK_CERTAINTY_DEFAULT)
    if certainty not in AUTO_PROMOTE_CERTAINTIES:
        return PromotionDecision(eligible=False, reason=certainty)

    if float(row["base_confidence"]) < PROMOTION_MIN_CONFIDENCE:
        return PromotionDecision(eligible=False, reason="low_confidence")

    return PromotionDecision(eligible=True, reason="confirmed_ok")


def _merge_spark_lineage(
    row: sqlite3.Row,
    updates: dict[str, object],
) -> str:
    raw = row["lineage_json"]
    lineage: dict[str, object] = {}
    if raw:
        try:
            parsed = json.loads(str(raw))
            if isinstance(parsed, dict):
                lineage = parsed
        except json.JSONDecodeError:
            lineage = {}
    lineage.update(updates)
    return json.dumps(lineage, sort_keys=True, ensure_ascii=False)


def promote_spark_to_active(
    conn: sqlite3.Connection,
    spark_id: int,
    *,
    dry_run: bool = False,
    manual: bool = False,
    promoted_by: str = "system",
    promotion_source: str = "auto_ingest",
) -> PromotionResult:
    """Move an eligible candidate spark to active trust_state."""
    import crowley

    row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
    if row is None:
        return PromotionResult(
            ok=False,
            spark_id=spark_id,
            from_state="missing",
            to_state="active",
            reason="not_found",
            dry_run=dry_run,
        )

    from_state = str(row["trust_state"])
    decision = evaluate_promotion_eligibility(row, manual=manual)
    if not decision.eligible:
        return PromotionResult(
            ok=False,
            spark_id=spark_id,
            from_state=from_state,
            to_state="active",
            reason=decision.reason,
            dry_run=dry_run,
        )

    if dry_run:
        return PromotionResult(
            ok=True,
            spark_id=spark_id,
            from_state=from_state,
            to_state="active",
            reason=decision.reason,
            dry_run=True,
        )

    now_iso = crowley._now_iso()
    lineage_blob = _merge_spark_lineage(
        row,
        {
            "promoted_at": now_iso,
            "promoted_by": promoted_by,
            "promotion_source": promotion_source,
            "promotion_reason": decision.reason,
        },
    )
    conn.execute(
        """
        UPDATE sparks
        SET trust_state = 'active', updated_at = ?, lineage_json = ?
        WHERE id = ?
        """,
        (now_iso, lineage_blob, spark_id),
    )
    return PromotionResult(
        ok=True,
        spark_id=spark_id,
        from_state=from_state,
        to_state="active",
        reason=decision.reason,
        dry_run=False,
    )


def promote_sparks_batch(
    conn: sqlite3.Connection,
    spark_ids: list[int],
    *,
    dry_run: bool = False,
    manual: bool = False,
    promoted_by: str = "system",
    promotion_source: str = "auto_ingest",
) -> list[PromotionResult]:
    results: list[PromotionResult] = []
    for spark_id in spark_ids:
        results.append(
            promote_spark_to_active(
                conn,
                int(spark_id),
                dry_run=dry_run,
                manual=manual,
                promoted_by=promoted_by,
                promotion_source=promotion_source,
            )
        )
    return results


def promotion_summary(results: list[PromotionResult]) -> dict[str, object]:
    promoted = [item for item in results if item.ok and not item.dry_run]
    skipped = [
        {"spark_id": item.spark_id, "reason": item.reason}
        for item in results
        if not item.ok
    ]
    return {
        "attempted": len(results),
        "promoted": len(promoted),
        "skipped": skipped,
    }


def _project_clause(project_id: int | None) -> tuple[str, list[object]]:
    if project_id is None:
        return "AND project_id IS NULL", []
    return "AND project_id = ?", [project_id]


def should_mark_stale(row: sqlite3.Row, *, now: datetime | None = None) -> bool:
    """Low-usage active/candidate sparks become stale; pinned sparks are exempt."""
    trust_state = str(row["trust_state"])
    if trust_state == "pinned":
        return False
    if trust_state not in MAINTENANCE_STALE_FROM:
        return False
    if int(row["access_count"] or 0) > STALE_MAX_ACCESS_COUNT:
        return False
    return days_since_last_access(row, now=now) >= STALE_INACTIVITY_DAYS


def should_mark_rejected(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    pattern_spark_ids: frozenset[int],
    now: datetime | None = None,
) -> bool:
    if str(row["trust_state"]) != "stale":
        return False
    live = live_confidence_for_spark(
        conn,
        row,
        pattern_spark_ids=pattern_spark_ids,
        now=now,
    )
    return live <= MIN_CONFIDENCE


def run_spark_lifecycle_maintenance(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = True,
    project_id: int | None = None,
    now: datetime | None = None,
) -> SparkMaintenanceResult:
    """Apply or preview stale/rejected transitions. Never hard-deletes rows."""
    import crowley

    now_dt = now or datetime.now(timezone.utc)
    project_sql, project_params = _project_clause(project_id)
    pattern_spark_ids = active_pattern_spark_ids(conn)

    stale_rows = conn.execute(
        f"""
        SELECT *
        FROM sparks
        WHERE trust_state IN ('active', 'candidate')
          AND trust_state != 'pinned'
          {project_sql}
        """,
        project_params,
    ).fetchall()
    stale_candidates = [
        int(row["id"]) for row in stale_rows if should_mark_stale(row, now=now_dt)
    ]

    reject_rows = conn.execute(
        f"""
        SELECT *
        FROM sparks
        WHERE trust_state = 'stale'
          {project_sql}
        """,
        project_params,
    ).fetchall()
    rejected_candidates = [
        int(row["id"])
        for row in reject_rows
        if should_mark_rejected(
            conn,
            row,
            pattern_spark_ids=pattern_spark_ids,
            now=now_dt,
        )
    ]

    promotion_rows = conn.execute(
        f"""
        SELECT *
        FROM sparks
        WHERE trust_state = 'candidate'
          {project_sql}
        """,
        project_params,
    ).fetchall()
    promotion_candidates = [
        int(row["id"])
        for row in promotion_rows
        if evaluate_promotion_eligibility(row, manual=False).eligible
    ]

    stale_applied = 0
    rejected_applied = 0
    promotions_applied = 0
    if not dry_run:
        now_iso = crowley._now_iso()
        for spark_id in stale_candidates:
            row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            if row is None or not should_mark_stale(row, now=now_dt):
                continue
            live = live_confidence_for_spark(
                conn,
                row,
                pattern_spark_ids=pattern_spark_ids,
                now=now_dt,
            )
            conn.execute(
                """
                UPDATE sparks
                SET trust_state = 'stale', confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (live, now_iso, spark_id),
            )
            stale_applied += 1

        for spark_id in rejected_candidates:
            row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            if row is None or not should_mark_rejected(
                conn,
                row,
                pattern_spark_ids=pattern_spark_ids,
                now=now_dt,
            ):
                continue
            live = live_confidence_for_spark(
                conn,
                row,
                pattern_spark_ids=pattern_spark_ids,
                now=now_dt,
            )
            conn.execute(
                """
                UPDATE sparks
                SET trust_state = 'rejected', confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (live, now_iso, spark_id),
            )
            rejected_applied += 1

        for spark_id in promotion_candidates:
            row = conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()
            if row is None or not evaluate_promotion_eligibility(row, manual=False).eligible:
                continue
            result = promote_spark_to_active(
                conn,
                spark_id,
                dry_run=False,
                manual=False,
                promoted_by="system",
                promotion_source="maintenance",
            )
            if result.ok:
                promotions_applied += 1

    return SparkMaintenanceResult(
        ok=True,
        dry_run=dry_run,
        stale_candidates=stale_candidates,
        rejected_candidates=rejected_candidates,
        promotion_candidates=promotion_candidates,
        stale_applied=stale_applied,
        rejected_applied=rejected_applied,
        promotions_applied=promotions_applied,
    )

