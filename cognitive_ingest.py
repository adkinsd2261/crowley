"""V4 T5 — cognitive ingest receipt + async extraction pipeline."""

from __future__ import annotations

import threading
import uuid
from typing import Any

import cognitive_chunking
import cognitive_intent
import crowley
import spark_extraction
import spark_lifecycle
import sparks
from cognitive_intent import MemoryIntentResult

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


def _intent_metadata(intent: MemoryIntentResult) -> dict[str, object]:
    return {
        "intent": intent.intent,
        "intent_confidence": intent.confidence,
        "intent_reason": intent.reason,
    }


def _apply_intent_certainty(
    spark: dict[str, object],
    intent: MemoryIntentResult,
) -> dict[str, object]:
    updated = dict(spark)
    if intent.confidence < cognitive_intent.LOW_CONFIDENCE_THRESHOLD:
        updated["certainty"] = "tentative"
    elif intent.intent == "store":
        current = str(updated.get("certainty") or sparks.SPARK_CERTAINTY_DEFAULT)
        if current == sparks.SPARK_CERTAINTY_DEFAULT:
            updated["certainty"] = "confirmed"
    return updated


def _auto_promote_sparks(
    conn: Any,
    spark_ids: list[int],
) -> dict[str, object]:
    if not spark_ids:
        return {"attempted": 0, "promoted": 0, "skipped": []}
    results = spark_lifecycle.promote_sparks_batch(
        conn,
        spark_ids,
        dry_run=False,
        manual=False,
        promoted_by="system",
        promotion_source="auto_ingest",
    )
    return spark_lifecycle.promotion_summary(results)


def _record_intent_skip(
    memory_item_id: int,
    intent: MemoryIntentResult,
    *,
    temporary: bool,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        **_intent_metadata(intent),
        "extraction_status": "skipped_intent",
        "spark_count": 0,
        "non_retrieval": True,
    }
    if temporary:
        metadata["retention"] = "audit_only"
    conn = crowley.connect_db()
    try:
        crowley.attach_memory_item_metadata(memory_item_id, metadata, conn=conn)
        conn.commit()
    finally:
        conn.close()
    return {
        "status": "skipped",
        "reason": intent.reason,
        "spark_ids": [],
    }


def _persist_sparks_from_extraction(
    conn: Any,
    *,
    memory_item_id: int,
    project_id: int | None,
    result: spark_extraction.SparkExtractionResult,
    extraction_id: str,
    intent: MemoryIntentResult | None,
    lineage_extra: dict[str, object] | None = None,
) -> list[int]:
    spark_ids: list[int] = []
    for spark in result.sparks:
        spark_payload = (
            _apply_intent_certainty(spark, intent) if intent is not None else spark
        )
        lineage_json: dict[str, object] = {
            "memory_item_id": memory_item_id,
            "extraction_id": extraction_id,
            "extraction_attempts": result.attempts,
        }
        if lineage_extra:
            lineage_json.update(lineage_extra)
        upsert = sparks.upsert_spark_with_dedup(
            conn,
            spark_payload,
            source_memory_item_id=memory_item_id,
            project_id=project_id,
            trust_state=_assign_trust_state(
                str(spark_payload.get("sensitivity") or "normal")
            ),
            lineage_json=lineage_json,
        )
        spark_ids.append(upsert.spark_id)
    return spark_ids


def _run_extraction_pipeline(
    memory_item_id: int,
    text: str,
    *,
    project_id: int | None,
    intent: MemoryIntentResult | None = None,
) -> dict[str, object]:
    extraction_id = str(uuid.uuid4())
    result = spark_extraction.extract_sparks_from_text(text)

    conn = crowley.connect_db()
    try:
        if not result.ok:
            failure_metadata: dict[str, object] = {
                "extraction_status": "failed",
                "extraction_id": extraction_id,
                "extraction_attempts": result.attempts,
                "extraction_errors": list(result.errors),
                "spark_count": 0,
            }
            if intent is not None:
                failure_metadata.update(_intent_metadata(intent))
            crowley.attach_memory_item_metadata(
                memory_item_id,
                failure_metadata,
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
        promotion: dict[str, object] = {"attempted": 0, "promoted": 0, "skipped": []}
        conn.execute("BEGIN")
        try:
            spark_ids = _persist_sparks_from_extraction(
                conn,
                memory_item_id=memory_item_id,
                project_id=project_id,
                result=result,
                extraction_id=extraction_id,
                intent=intent,
            )
            promotion = _auto_promote_sparks(conn, spark_ids)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        complete_metadata: dict[str, object] = {
            "extraction_status": "complete",
            "extraction_id": extraction_id,
            "extraction_attempts": result.attempts,
            "spark_count": len(spark_ids),
            "spark_ids": spark_ids,
            "promotion": promotion,
        }
        if intent is not None:
            complete_metadata.update(_intent_metadata(intent))
            if intent.confidence < cognitive_intent.LOW_CONFIDENCE_THRESHOLD:
                complete_metadata["intent_certainty_hint"] = "tentative"
        crowley.attach_memory_item_metadata(
            memory_item_id,
            complete_metadata,
            conn=conn,
        )
        conn.commit()
        return {
            "ok": True,
            "spark_ids": spark_ids,
            "attempts": result.attempts,
            "extraction_id": extraction_id,
            "promotion": promotion,
        }
    except Exception as exc:
        conn.rollback()
        error_metadata: dict[str, object] = {
            "extraction_status": "failed",
            "extraction_id": extraction_id,
            "extraction_attempts": result.attempts,
            "extraction_errors": [str(exc)],
            "spark_count": 0,
        }
        if intent is not None:
            error_metadata.update(_intent_metadata(intent))
        crowley.attach_memory_item_metadata(
            memory_item_id,
            error_metadata,
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


def _run_chunked_extraction_pipeline(
    memory_item_id: int,
    text: str,
    *,
    project_id: int | None,
) -> dict[str, object]:
    chunking = cognitive_chunking.chunk_cognitive_text(text)
    extraction_id = str(uuid.uuid4())
    chunk_manifest: list[dict[str, object]] = []
    chunk_failures: list[dict[str, object]] = []
    spark_ids: list[int] = []
    chunks_processed = 0
    chunks_skipped_intent = 0
    total_attempts = 0
    any_extracted = False

    conn = crowley.connect_db()
    try:
        for chunk in chunking.chunks:
            chunk_intent = cognitive_intent.classify_memory_intent(chunk.text)
            if chunk_intent.intent in {"ignore", "temporary"}:
                chunks_skipped_intent += 1
                chunk_manifest.append(
                    {
                        "index": chunk.index,
                        "intent": chunk_intent.intent,
                        "reason": chunk_intent.reason,
                        "spark_count": 0,
                        "status": "skipped_intent",
                    }
                )
                continue

            result = spark_extraction.extract_sparks_from_text(chunk.text)
            total_attempts = max(total_attempts, result.attempts)
            if not result.ok:
                chunk_failures.append(
                    {
                        "index": chunk.index,
                        "errors": list(result.errors),
                        "attempts": result.attempts,
                    }
                )
                chunk_manifest.append(
                    {
                        "index": chunk.index,
                        "intent": chunk_intent.intent,
                        "reason": chunk_intent.reason,
                        "spark_count": 0,
                        "status": "failed",
                    }
                )
                continue

            conn.execute("BEGIN")
            try:
                chunk_spark_ids = _persist_sparks_from_extraction(
                    conn,
                    memory_item_id=memory_item_id,
                    project_id=project_id,
                    result=result,
                    extraction_id=extraction_id,
                    intent=chunk_intent,
                    lineage_extra={
                        "chunk_index": chunk.index,
                        "chunk_count": len(chunking.chunks),
                        "chunk_break_reason": chunk.break_reason,
                    },
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                chunk_failures.append(
                    {"index": chunk.index, "errors": [str(exc)], "attempts": result.attempts}
                )
                chunk_manifest.append(
                    {
                        "index": chunk.index,
                        "intent": chunk_intent.intent,
                        "reason": chunk_intent.reason,
                        "spark_count": 0,
                        "status": "failed",
                    }
                )
                continue

            chunks_processed += 1
            any_extracted = any_extracted or bool(chunk_spark_ids)
            spark_ids.extend(chunk_spark_ids)
            chunk_manifest.append(
                {
                    "index": chunk.index,
                    "intent": chunk_intent.intent,
                    "reason": chunk_intent.reason,
                    "spark_count": len(chunk_spark_ids),
                    "status": "complete",
                }
            )

        if chunk_failures and any_extracted:
            extraction_status = "partial"
            ok = True
        elif chunk_failures:
            extraction_status = "failed"
            ok = False
        elif any_extracted:
            extraction_status = "complete"
            ok = True
        else:
            extraction_status = "skipped_intent"
            ok = True

        promotion = _auto_promote_sparks(conn, spark_ids)

        complete_metadata: dict[str, object] = {
            "extraction_status": extraction_status,
            "extraction_id": extraction_id,
            "extraction_attempts": total_attempts,
            "spark_count": len(spark_ids),
            "spark_ids": spark_ids,
            "promotion": promotion,
            "chunking": {
                "chunk_count": len(chunking.chunks),
                "truncated": chunking.truncated,
                "omitted_chunk_count": chunking.omitted_chunk_count,
                "chunks_processed": chunks_processed,
                "chunks_skipped_intent": chunks_skipped_intent,
            },
            "chunk_manifest": chunk_manifest,
            **_intent_metadata(cognitive_intent.CHUNKED_INGEST_INTENT),
        }
        if chunk_failures:
            complete_metadata["chunk_failures"] = chunk_failures
        if not any_extracted and chunks_skipped_intent == len(chunking.chunks):
            complete_metadata["non_retrieval"] = True
            complete_metadata["retention"] = "audit_only"

        crowley.attach_memory_item_metadata(
            memory_item_id,
            complete_metadata,
            conn=conn,
        )
        conn.commit()
        response: dict[str, object] = {
            "ok": ok,
            "spark_ids": spark_ids,
            "attempts": total_attempts,
            "extraction_id": extraction_id,
            "chunking": complete_metadata["chunking"],
            "promotion": promotion,
        }
        if chunk_failures:
            response["errors"] = [
                f"chunk {item['index']}: {'; '.join(item['errors'])}"  # type: ignore[index]
                for item in chunk_failures
            ]
        return response
    finally:
        conn.close()


def _worker_wrapper(
    memory_item_id: int,
    text: str,
    project_id: int | None,
    intent: MemoryIntentResult,
) -> None:
    try:
        _run_extraction_pipeline(
            memory_item_id,
            text,
            project_id=project_id,
            intent=intent,
        )
    except Exception as exc:
        conn = crowley.connect_db()
        try:
            crowley.attach_memory_item_metadata(
                memory_item_id,
                {
                    "extraction_status": "failed",
                    "extraction_errors": [f"worker_error: {exc}"],
                    "spark_count": 0,
                    **_intent_metadata(intent),
                },
                conn=conn,
            )
            conn.commit()
        finally:
            conn.close()


def _chunked_worker_wrapper(
    memory_item_id: int,
    text: str,
    project_id: int | None,
) -> None:
    try:
        _run_chunked_extraction_pipeline(
            memory_item_id,
            text,
            project_id=project_id,
        )
    except Exception as exc:
        conn = crowley.connect_db()
        try:
            crowley.attach_memory_item_metadata(
                memory_item_id,
                {
                    "extraction_status": "failed",
                    "extraction_errors": [f"worker_error: {exc}"],
                    "spark_count": 0,
                    **_intent_metadata(cognitive_intent.CHUNKED_INGEST_INTENT),
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
    intent: MemoryIntentResult,
) -> None:
    thread = threading.Thread(
        target=_worker_wrapper,
        args=(memory_item_id, text, project_id, intent),
        daemon=True,
    )
    thread.start()


def _spawn_chunked_extraction_worker(
    memory_item_id: int,
    text: str,
    *,
    project_id: int | None,
) -> None:
    thread = threading.Thread(
        target=_chunked_worker_wrapper,
        args=(memory_item_id, text, project_id),
        daemon=True,
    )
    thread.start()


def _ingest_long_content(
    content: str,
    *,
    memory_item_id: int,
    project_id: int,
    sync: bool,
) -> dict[str, Any]:
    precheck = cognitive_intent.classify_ingest_precheck(content)
    response: dict[str, Any] = {
        "memory_item_id": int(memory_item_id),
        "intent": (
            precheck.as_dict()
            if precheck is not None
            else cognitive_intent.CHUNKED_INGEST_INTENT.as_dict()
        ),
    }
    if precheck is not None and precheck.intent == "ignore":
        extraction = _record_intent_skip(int(memory_item_id), precheck, temporary=False)
        response["status"] = "ok" if sync else "accepted"
        response["extraction"] = extraction
        return response

    if sync:
        extraction = _run_chunked_extraction_pipeline(
            int(memory_item_id),
            content,
            project_id=project_id,
        )
        response["status"] = "ok"
        response["extraction"] = extraction
        return response

    _spawn_chunked_extraction_worker(int(memory_item_id), content, project_id=project_id)
    response["status"] = "accepted"
    response["extraction"] = {"status": "queued"}
    return response


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

    if len(content) > cognitive_chunking.CHUNK_THRESHOLD_CHARS:
        return _ingest_long_content(
            content,
            memory_item_id=int(memory_item_id),
            project_id=project_id,
            sync=sync,
        )

    intent = cognitive_intent.classify_memory_intent(content)
    response: dict[str, Any] = {
        "memory_item_id": int(memory_item_id),
        "intent": intent.as_dict(),
    }

    if intent.intent == "ignore":
        extraction = _record_intent_skip(int(memory_item_id), intent, temporary=False)
        response["status"] = "ok" if sync else "accepted"
        response["extraction"] = extraction
        return response

    if intent.intent == "temporary":
        extraction = _record_intent_skip(int(memory_item_id), intent, temporary=True)
        response["status"] = "ok" if sync else "accepted"
        response["extraction"] = extraction
        return response

    if sync:
        extraction = _run_extraction_pipeline(
            int(memory_item_id),
            content,
            project_id=project_id,
            intent=intent,
        )
        response["status"] = "ok"
        response["extraction"] = extraction
        return response

    _spawn_extraction_worker(
        int(memory_item_id),
        content,
        project_id=project_id,
        intent=intent,
    )
    response["status"] = "accepted"
    response["extraction"] = {"status": "queued"}
    return response
