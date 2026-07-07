"""V4 T5 — cognitive ingest receipt + async extraction pipeline."""

from __future__ import annotations

import threading
import uuid
from typing import Any

import crowley
import spark_extraction
import sparks

COGNITIVE_INGEST_SOURCE = "cognitive_ingest"
COGNITIVE_MEMORY_TYPE = "event"


def _assign_trust_state(sensitivity: str) -> str:
    """Code-owned lifecycle default — LLM never sets trust_state."""
    _ = sensitivity
    return "candidate"


def _save_cognitive_receipt(
    content: str,
    *,
    project_id: int,
    source: str,
    metadata: dict[str, object] | None,
    extraction_status: str,
) -> int | None:
    merged_metadata: dict[str, object] = {
        "cognitive_ingest": True,
        "extraction_status": extraction_status,
    }
    if metadata:
        merged_metadata.update(metadata)
    return crowley.save_memory_item(
        COGNITIVE_MEMORY_TYPE,
        content.strip(),
        summary="Cognitive ingest receipt",
        source=source or COGNITIVE_INGEST_SOURCE,
        project_id=project_id,
        importance=3,
        confidence=0.85,
        pinned=False,
        status="active",
        metadata=merged_metadata,
        agent_id=source,
        write_action="cognitive.ingest",
    )


def _run_extraction_pipeline(
    memory_item_id: int,
    text: str,
    *,
    project_id: int | None,
) -> dict[str, object]:
    extraction_id = str(uuid.uuid4())
    result = spark_extraction.extract_sparks_from_text(text)

    conn = crowley.connect_db()
    try:
        if not result.ok:
            crowley.attach_memory_item_metadata(
                memory_item_id,
                {
                    "extraction_status": "failed",
                    "extraction_id": extraction_id,
                    "extraction_attempts": result.attempts,
                    "extraction_errors": list(result.errors),
                    "spark_count": 0,
                },
                conn=conn,
            )
            conn.commit()
            return {
                "ok": False,
                "spark_ids": [],
                "attempts": result.attempts,
                "errors": list(result.errors),
                "extraction_id": extraction_id,
            }

        spark_ids: list[int] = []
        conn.execute("BEGIN")
        try:
            for spark in result.sparks:
                upsert = sparks.upsert_spark_with_dedup(
                    conn,
                    spark,
                    source_memory_item_id=memory_item_id,
                    project_id=project_id,
                    trust_state=_assign_trust_state(str(spark.get("sensitivity") or "normal")),
                    lineage_json={
                        "memory_item_id": memory_item_id,
                        "extraction_id": extraction_id,
                        "extraction_attempts": result.attempts,
                    },
                )
                spark_ids.append(upsert.spark_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        crowley.attach_memory_item_metadata(
            memory_item_id,
            {
                "extraction_status": "complete",
                "extraction_id": extraction_id,
                "extraction_attempts": result.attempts,
                "spark_count": len(spark_ids),
                "spark_ids": spark_ids,
            },
            conn=conn,
        )
        conn.commit()
        return {
            "ok": True,
            "spark_ids": spark_ids,
            "attempts": result.attempts,
            "extraction_id": extraction_id,
        }
    except Exception as exc:
        conn.rollback()
        crowley.attach_memory_item_metadata(
            memory_item_id,
            {
                "extraction_status": "failed",
                "extraction_id": extraction_id,
                "extraction_attempts": result.attempts,
                "extraction_errors": [str(exc)],
                "spark_count": 0,
            },
            conn=conn,
        )
        conn.commit()
        return {
            "ok": False,
            "spark_ids": [],
            "attempts": result.attempts,
            "errors": [str(exc)],
            "extraction_id": extraction_id,
        }
    finally:
        conn.close()


def _worker_wrapper(memory_item_id: int, text: str, project_id: int | None) -> None:
    try:
        _run_extraction_pipeline(memory_item_id, text, project_id=project_id)
    except Exception as exc:
        conn = crowley.connect_db()
        try:
            crowley.attach_memory_item_metadata(
                memory_item_id,
                {
                    "extraction_status": "failed",
                    "extraction_errors": [f"worker_error: {exc}"],
                    "spark_count": 0,
                },
                conn=conn,
            )
            conn.commit()
        finally:
            conn.close()


def _spawn_extraction_worker(
    memory_item_id: int,
    text: str,
    *,
    project_id: int | None,
) -> None:
    thread = threading.Thread(
        target=_worker_wrapper,
        args=(memory_item_id, text, project_id),
        daemon=True,
    )
    thread.start()


def ingest_cognitive_content(
    content: str,
    *,
    project: str = crowley.DEFAULT_PROJECT_SLUG,
    source: str = "manual",
    metadata: dict[str, object] | None = None,
    sync: bool = False,
) -> dict[str, Any]:
    """Save cognitive receipt synchronously; extract sparks async or inline."""
    project_row = crowley.get_project_by_slug(project) if project else crowley.get_active_project()
    if project_row is None:
        raise ValueError(f"project not found: {project}")
    project_id = int(project_row["id"])

    memory_item_id = _save_cognitive_receipt(
        content,
        project_id=project_id,
        source=source,
        metadata=metadata,
        extraction_status="processing" if sync else "queued",
    )
    if memory_item_id is None:
        return {"status": "error", "error": "failed to save cognitive receipt"}

    if sync:
        extraction = _run_extraction_pipeline(
            int(memory_item_id),
            content,
            project_id=project_id,
        )
        return {
            "status": "ok",
            "memory_item_id": int(memory_item_id),
            "extraction": extraction,
        }

    _spawn_extraction_worker(int(memory_item_id), content, project_id=project_id)
    return {
        "status": "accepted",
        "memory_item_id": int(memory_item_id),
        "extraction": {"status": "queued"},
    }
