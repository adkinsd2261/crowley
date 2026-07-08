"""V4 T17 — portable terminal writeback bridge into sparks table."""

from __future__ import annotations

import sqlite3

import crowley
import sparks


def portable_spark_to_v4(spark: dict[str, object]) -> dict[str, object]:
    """Map a normalized portable writeback spark into V4 validate_spark input."""
    why_keep = str(spark.get("why_keep") or "").strip()
    worth_reason = str(spark.get("worth_reason") or why_keep).strip()
    return {
        "content": str(spark["content"]),
        "lane": str(spark["lane"]),
        "why_keep": why_keep,
        "worth_reason": worth_reason,
        "confidence": float(spark["confidence"]),
        "sensitivity": str(spark.get("sensitivity") or "normal"),
    }


def upsert_portable_spark_to_v4(
    conn: sqlite3.Connection,
    spark: dict[str, object],
    *,
    source_memory_item_id: int,
    project_id: int,
    session_receipt_id: int,
    session: dict[str, object],
) -> sparks.SparkUpsertResult:
    """Dual-write one portable spark into the V4 sparks table."""
    validation = sparks.validate_spark(portable_spark_to_v4(spark))
    if not validation.ok or validation.spark is None:
        raise ValueError("; ".join(validation.errors))

    lineage = {
        "portable_writeback": True,
        "writeback_format": crowley.PORTABLE_WRITEBACK_FORMAT,
        "session_receipt_id": session_receipt_id,
        "memory_item_id": source_memory_item_id,
        "surface": session.get("surface"),
        "model": session.get("model"),
        "provider": session.get("provider"),
    }
    return sparks.upsert_spark_with_dedup(
        conn,
        validation.spark,
        source_memory_item_id=source_memory_item_id,
        project_id=project_id,
        trust_state="candidate",
        lineage_json=lineage,
    )
