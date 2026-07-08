"""V4 T16 — cognitive spark maintenance and manual seeding."""

from __future__ import annotations

from typing import Any

import crowley
import spark_lifecycle
import sparks

COGNITIVE_SEED_SOURCE = "cognitive_seed"
COGNITIVE_SEED_MEMORY_TYPE = "event"


def _resolve_project_id(project: str | None) -> tuple[int, str]:
    if project:
        project_row = crowley.get_project_by_slug(project)
        if project_row is None:
            raise ValueError(f"project not found: {project}")
    else:
        project_row = crowley.get_active_project()
        if project_row is None:
            raise ValueError("no active project")
    return int(project_row["id"]), str(project_row["slug"])


def _save_seed_receipt(
    spark: dict[str, object],
    *,
    project_id: int,
    source: str,
    metadata: dict[str, object] | None,
) -> int | None:
    merged_metadata: dict[str, object] = {
        "cognitive_seed": True,
        "spark_lane": str(spark["lane"]),
    }
    if metadata:
        merged_metadata.update(metadata)
    return crowley.save_memory_item(
        COGNITIVE_SEED_MEMORY_TYPE,
        str(spark["content"]),
        summary="Cognitive manual spark seed",
        source=source or COGNITIVE_SEED_SOURCE,
        project_id=project_id,
        importance=3,
        confidence=float(spark["confidence"]),
        pinned=False,
        status="active",
        metadata=merged_metadata,
        agent_id=source,
        write_action="cognitive.spark_seed",
    )


def run_cognitive_maintenance(
    *,
    dry_run: bool = True,
    project: str | None = None,
) -> dict[str, object]:
    project_id, project_slug = _resolve_project_id(project)
    conn = crowley.connect_db()
    try:
        result = spark_lifecycle.run_spark_lifecycle_maintenance(
            conn,
            dry_run=dry_run,
            project_id=project_id,
        )
        if not dry_run:
            conn.commit()
        return {
            "status": "ok",
            "project": project_slug,
            "project_id": project_id,
            "dry_run": result.dry_run,
            "stale_candidates": result.stale_candidates,
            "rejected_candidates": result.rejected_candidates,
            "stale_applied": result.stale_applied,
            "rejected_applied": result.rejected_applied,
        }
    finally:
        conn.close()


def seed_manual_spark(
    raw_spark: dict[str, object],
    *,
    project: str | None = None,
    source: str = "manual",
    metadata: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Validate and seed a spark via dedup path with a memory_item receipt."""
    validation = sparks.validate_spark(raw_spark)
    if not validation.ok or validation.spark is None:
        raise ValueError("; ".join(validation.errors))

    spark = dict(validation.spark)
    project_id, project_slug = _resolve_project_id(project)
    memory_item_id = _save_seed_receipt(
        spark,
        project_id=project_id,
        source=source,
        metadata=metadata,
    )
    if memory_item_id is None:
        return {"status": "error", "error": "failed to save seed receipt"}

    lineage = {
        "seed": "manual",
        "source": source,
        "memory_item_id": int(memory_item_id),
    }
    conn = crowley.connect_db()
    try:
        upsert = sparks.upsert_spark_with_dedup(
            conn,
            spark,
            source_memory_item_id=int(memory_item_id),
            project_id=project_id,
            trust_state=spark_lifecycle.SPARK_SEED_TRUST_STATE,
            lineage_json=lineage,
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "project": project_slug,
        "project_id": project_id,
        "memory_item_id": int(memory_item_id),
        "trust_state": spark_lifecycle.SPARK_SEED_TRUST_STATE,
        "action": upsert.action,
        "spark_id": upsert.spark_id,
        "keeper_id": upsert.keeper_id,
        "similarity": upsert.similarity,
    }
