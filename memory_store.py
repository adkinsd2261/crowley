"""Memory item store, API rendering, quality gate, and save helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class MemoryGateOutcome:
    allowed: bool
    memory_type: str
    content: str
    summary: str | None
    importance: int
    confidence: float
    reason: str


def list_recent_memory_items(rt: Any, limit: int = 10) -> list[Any]:
    """Return recent active memory_items for UI and read-only APIs."""
    conn = rt.connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE status = 'active'
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return list(rows)
    finally:
        conn.close()


def count_memory_items_by_status(rt: Any) -> dict[str, int]:
    """Return memory_items counts grouped by status."""
    conn = rt.connect_db()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM memory_items GROUP BY status"
        ).fetchall()
        return {str(row["status"]): int(row["n"]) for row in rows}
    finally:
        conn.close()


def list_memory_items(
    rt: Any,
    *,
    q: str | None = None,
    source: str | None = None,
    agent_id: str | None = None,
    memory_tier: str | None = None,
    memory_type: str | None = None,
    status: str | None = "active",
    limit: int = 10,
    offset: int = 0,
) -> tuple[list[Any], int]:
    """Return filtered memory_items plus total count before pagination."""
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))

    clauses: list[str] = []
    params: list[object] = []
    if status and status != "all":
        clauses.append("status = ?")
        params.append(status)
    if source:
        clauses.append("LOWER(source) = LOWER(?)")
        params.append(source)
    if agent_id and str(agent_id).strip():
        clauses.append(
            "LOWER(json_extract(metadata_json, '$.write_attribution.agent_id')) = LOWER(?)"
        )
        params.append(str(agent_id).strip())
    if memory_tier and str(memory_tier).strip():
        clauses.append(
            "LOWER(json_extract(metadata_json, '$.memory_tier')) = LOWER(?)"
        )
        params.append(str(memory_tier).strip())
    if memory_type:
        clauses.append("LOWER(memory_type) = LOWER(?)")
        params.append(memory_type)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        clauses.append("(LOWER(content) LIKE ? OR LOWER(COALESCE(summary, '')) LIKE ?)")
        params.extend([needle, needle])

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    conn = rt.connect_db()
    try:
        total = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM memory_items {where}",
                params,
            ).fetchone()["n"]
        )
        rows = conn.execute(
            f"""
            SELECT * FROM memory_items
            {where}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return list(rows), total
    finally:
        conn.close()


def get_memory_item_api_by_id(rt: Any, memory_id: int) -> dict[str, object] | None:
    """Return one memory item for read APIs, any status."""
    conn = rt.connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (int(memory_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return memory_item_api_dict(rt, row)


def list_recent_memory_updates(rt: Any, *, limit: int = 20) -> list[dict[str, object]]:
    """Recent memory_items ordered by updated_at for inspect.recent_updates."""
    limit = max(1, min(int(limit), 50))
    conn = rt.connect_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            ORDER BY datetime(updated_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [memory_item_api_dict(rt, row) for row in rows]
    finally:
        conn.close()


def build_memory_lineage(rt: Any, memory_id: int) -> dict[str, object] | None:
    """Lineage for a memory item: merged_into, metadata promotion fields."""
    item = get_memory_item_api_by_id(rt, memory_id)
    if item is None:
        return None
    lineage: dict[str, object] = {"memory": item}
    merged_into = item.get("merged_into_id")
    if merged_into is not None:
        parent = get_memory_item_api_by_id(rt, int(merged_into))
        if parent is not None:
            lineage["merged_into"] = parent
    meta_raw = item.get("metadata_json")
    if isinstance(meta_raw, str) and meta_raw.strip():
        try:
            meta = json.loads(meta_raw)
            if isinstance(meta, dict):
                lineage["metadata"] = meta
                session_id = meta.get("session_receipt_id")
                if session_id is not None:
                    session = rt.get_portable_session_api(int(session_id))
                    if session is not None:
                        lineage["source_session"] = session
        except json.JSONDecodeError:
            pass
    return lineage


def explain_memory_in_retrieval(
    rt: Any, memory_id: int, *, q: str | None = None
) -> dict[str, object] | None:
    """Explain why a memory appears in retrieval for a query."""
    item = get_memory_item_api_by_id(rt, memory_id)
    if item is None:
        return None
    query = (q or rt.CONTEXT_DEFAULT_QUERY).strip()
    payload = rt.retrieve_memories_api(q=query, limit=50)
    results = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(results, list):
        for entry in results:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if entry_id is not None and int(entry_id) == int(memory_id):
                return {
                    "memory_id": int(memory_id),
                    "query": query,
                    "in_retrieval": True,
                    "explanation": entry,
                }
    return {
        "memory_id": int(memory_id),
        "query": query,
        "in_retrieval": False,
        "memory": item,
        "message": "Memory exists but was not in top retrieval results for this query.",
    }


def memory_item_attribution(rt: Any, row: Any) -> dict[str, object] | None:
    import agent_identity

    meta_raw = row["metadata_json"] if "metadata_json" in row.keys() else None
    attr = agent_identity.attribution_for_memory_row(
        str(meta_raw) if meta_raw is not None else None
    )
    if attr is not None:
        return attr
    return {
        "agent_id": agent_identity.normalize_agent_id(
            None, fallback_source=str(row["source"])
        ),
        "source": str(row["source"]),
        "timestamp": str(row["created_at"]),
        "inferred": True,
    }


def memory_item_layer(rt: Any, row: Any) -> str:
    if rt._is_canon_memory_row(row):
        return "canon"
    if int(row["pinned"]) == 1:
        return "pinned"
    return "memory"


def memory_item_api_dict(rt: Any, row: Any) -> dict[str, object]:
    import agent_identity
    import memory_tiers

    item = rt.row_to_dict(row)
    item.pop("embedding_blob", None)
    item["display"] = rt._memory_display_text(row)
    item["is_canon"] = rt._is_canon_memory_row(row)
    item["is_pinned"] = bool(int(row["pinned"]))
    item["memory_layer"] = memory_item_layer(rt, row)
    meta_raw = row["metadata_json"] if "metadata_json" in row.keys() else None
    attr = agent_identity.attribution_for_memory_row(
        str(meta_raw) if meta_raw is not None else None
    )
    if attr is not None:
        item["attribution"] = attr
        item["agent_id"] = attr.get("agent_id")
    else:
        item["agent_id"] = agent_identity.normalize_agent_id(
            None, fallback_source=str(row["source"])
        )
    item["memory_tier"] = memory_tiers.tier_from_metadata_json(
        str(meta_raw) if meta_raw is not None else None
    )
    if int(row["pinned"]):
        item["memory_tier"] = "canonical"
    return item


def memory_item_metadata(row: Any) -> dict[str, object]:
    raw = row["metadata_json"] if "metadata_json" in row.keys() else None
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def active_project_id(conn: Any) -> int | None:
    project = conn.execute(
        "SELECT id FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    return int(project["id"]) if project else None


def resolve_memory_item_fields(
    rt: Any,
    legacy_type: str,
    importance: int,
    *,
    source: str | None,
    pinned: bool | None,
    confidence: float | None,
) -> tuple[str, str, bool, float]:
    if legacy_type == "spark":
        item_type = (
            "summary" if importance >= rt.SPARK_IMPORTANCE_SUMMARY else "event"
        )
        resolved_source = source or (
            "session_summary"
            if importance >= rt.SPARK_IMPORTANCE_SUMMARY
            else "implicit"
        )
        resolved_pinned = False if pinned is None else pinned
        if confidence is not None:
            resolved_confidence = confidence
        elif resolved_source == "session_summary":
            resolved_confidence = 0.85
        else:
            resolved_confidence = 0.75
    else:
        item_type = legacy_type if legacy_type in rt.ALLOWED_MEMORY_ITEM_TYPES else "event"
        resolved_source = source or "manual"
        resolved_pinned = True if pinned is None else pinned
        resolved_confidence = 1.0 if confidence is None else confidence
    return item_type, resolved_source, resolved_pinned, resolved_confidence


def find_recent_duplicate_memory_item(
    rt: Any,
    conn: Any,
    memory_type: str,
    content: str,
    project_id: int | None,
) -> int | None:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=rt.MEMORY_ITEM_DEDUPE_HOURS)
    ).isoformat()
    norm = rt._normalize_memory_dedupe_key(content)
    if project_id is None:
        rows = conn.execute(
            """
            SELECT id, content FROM memory_items
            WHERE memory_type = ? AND status = 'active' AND created_at >= ?
              AND project_id IS NULL
            """,
            (memory_type, cutoff),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, content FROM memory_items
            WHERE memory_type = ? AND status = 'active' AND created_at >= ?
              AND project_id = ?
            """,
            (memory_type, cutoff, project_id),
        ).fetchall()
    for row in rows:
        if rt._normalize_memory_dedupe_key(str(row["content"])) == norm:
            return int(row["id"])
    return None


def clamp_memory_importance(importance: int) -> int:
    try:
        value = int(importance)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, value))


def clamp_memory_confidence(confidence: float) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, value))


def memory_gate_section_text(rt: Any, content: str, heading: str) -> str | None:
    bullets = parse_handoff_section_bullets(content, heading)
    if not bullets:
        return None
    return rt._truncate(" | ".join(bullets[:3]), 240)


def parse_handoff_section_bullets(content: str, heading: str) -> list[str]:
    pattern = re.compile(
        rf"^##\s*{re.escape(heading)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(content)
    if match is None:
        return []
    section = content[match.end() :]
    next_hdr = re.search(r"\n##\s+", section)
    if next_hdr:
        section = section[: next_hdr.start()]
    bullets: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            text = stripped[2:].strip()
            if text:
                bullets.append(text)
        elif stripped and not stripped.startswith("#"):
            bullets.append(stripped)
    return bullets


def extract_why_it_matters(rt: Any, content: str, summary: str | None = None) -> str | None:
    if summary and len(rt._normalize_text(summary)) >= rt.MEMORY_GATE_WHY_MIN_LEN:
        return rt._truncate(summary.strip(), 240)
    for heading in ("Summary", "QA Result", "QA", "Decisions", "Constraints", "Lessons"):
        section = memory_gate_section_text(rt, content, heading)
        if section and len(rt._normalize_text(section)) >= rt.MEMORY_GATE_WHY_MIN_LEN:
            return section
    trimmed = rt._normalize_text(content)
    if rt.MEMORY_GATE_WHY_MIN_LEN <= len(trimmed) <= 280:
        return rt._truncate(trimmed, 240)
    return None


def is_noisy_memory_content(rt: Any, content: str, *, memory_type: str) -> bool:
    trimmed = rt._normalize_text(content)
    if not trimmed:
        return True
    if memory_type != "event":
        return False
    if len(trimmed) < rt.MEMORY_GATE_WHY_MIN_LEN:
        return True
    if rt._normalize_dedupe_key(trimmed) in rt._GENERIC_EXTRACT_VALUES:
        return True
    lower = trimmed.lower()
    if len(trimmed) < 120 and not any(kw in lower for kw in rt._SIGNAL_KEYWORDS):
        return True
    return False


def evaluate_memory_quality_gate(
    rt: Any,
    memory_type: str,
    content: str,
    *,
    summary: str | None = None,
    source: str = "implicit",
    importance: int = 3,
    confidence: float = 1.0,
    project_id: int | None = None,
) -> MemoryGateOutcome:
    """Return gate decision for a memory_items save."""
    resolved_type = memory_type if memory_type in rt.ALLOWED_MEMORY_ITEM_TYPES else "event"
    resolved_content = content.strip()
    resolved_importance = clamp_memory_importance(importance)
    resolved_confidence = clamp_memory_confidence(confidence)

    if source in rt.MEMORY_GATE_BYPASS_SOURCES or resolved_type in rt.MEMORY_GATE_BYPASS_TYPES:
        return MemoryGateOutcome(
            True, resolved_type, resolved_content, summary,
            resolved_importance, resolved_confidence, "gate bypass",
        )

    if resolved_type == "event" and source == "implicit":
        return MemoryGateOutcome(
            False, resolved_type, resolved_content, summary,
            resolved_importance, resolved_confidence, "implicit event noise rejected",
        )

    if resolved_type == "event" and source in rt.INGEST_SOURCES:
        why = extract_why_it_matters(rt, resolved_content, summary)
        if not why or rt._is_generic_extract_value(why):
            return MemoryGateOutcome(
                False, resolved_type, resolved_content, summary,
                resolved_importance, resolved_confidence,
                "handoff event rejected: missing why_it_matters",
            )
        return MemoryGateOutcome(
            True, "lesson", why, why,
            max(2, resolved_importance), resolved_confidence,
            "handoff event promoted to lesson",
        )

    if resolved_type == "event":
        if is_noisy_memory_content(rt, resolved_content, memory_type=resolved_type):
            return MemoryGateOutcome(
                False, resolved_type, resolved_content, summary,
                resolved_importance, resolved_confidence, "noisy event rejected",
            )
        why = extract_why_it_matters(rt, resolved_content, summary)
        if not why:
            return MemoryGateOutcome(
                False, resolved_type, resolved_content, summary,
                resolved_importance, resolved_confidence, "event missing why_it_matters",
            )
        return MemoryGateOutcome(
            True, resolved_type, resolved_content, why,
            resolved_importance, resolved_confidence,
            "event allowed with why_it_matters",
        )

    if resolved_type not in rt.MEMORY_GATE_PROMOTED_TYPES:
        return MemoryGateOutcome(
            False, resolved_type, resolved_content, summary,
            resolved_importance, resolved_confidence,
            f"type not promoted: {resolved_type}",
        )

    why = extract_why_it_matters(rt, resolved_content, summary)
    if not why or rt._is_generic_extract_value(why):
        return MemoryGateOutcome(
            False, resolved_type, resolved_content, summary,
            resolved_importance, resolved_confidence,
            "promoted type missing why_it_matters",
        )

    if resolved_confidence < rt.MEMORY_GATE_CONFIDENCE_MIN:
        return MemoryGateOutcome(
            False, resolved_type, resolved_content, why,
            resolved_importance, resolved_confidence,
            "confidence below gate minimum",
        )

    if project_id is None:
        return MemoryGateOutcome(
            False, resolved_type, resolved_content, why,
            resolved_importance, resolved_confidence,
            "promoted memory missing project scope",
        )

    return MemoryGateOutcome(
        True, resolved_type, resolved_content, why,
        resolved_importance, resolved_confidence,
        "promoted memory accepted",
    )


def save_memory_item(
    rt: Any,
    memory_type: str,
    content: str,
    summary: str | None = None,
    source: str = "implicit",
    project_id: int | None = None,
    message_id: int | None = None,
    decision_id: int | None = None,
    importance: int = 3,
    confidence: float = 1.0,
    pinned: bool = False,
    status: str = "active",
    *,
    metadata: dict[str, object] | None = None,
    agent_id: str | None = None,
    write_action: str | None = None,
    conn: Any | None = None,
    legacy_memory_id: int | None = None,
) -> int | None:
    """Insert into memory_items and attempt embedding/indexing."""
    own_conn = conn is None
    if own_conn:
        conn = rt.connect_db()
    try:
        if project_id is None:
            project_id = active_project_id(conn)

        gate = evaluate_memory_quality_gate(
            rt,
            memory_type,
            content,
            summary=summary,
            source=source,
            importance=importance,
            confidence=confidence,
            project_id=project_id,
        )
        if not gate.allowed:
            return None

        memory_type = gate.memory_type
        content = gate.content
        summary = gate.summary
        importance = gate.importance
        confidence = gate.confidence

        import memory_quality

        semantic_dup, _reason = memory_quality.find_ingest_duplicate(
            conn, memory_type, content, project_id
        )
        if semantic_dup is not None:
            return semantic_dup

        if pinned:
            import agent_identity

            resolved_agent = agent_identity.normalize_agent_id(
                agent_id, fallback_source=source
            )
            allowed, _message = agent_identity.check_domain_permission(
                resolved_agent, "memory.pin"
            )
            if not allowed:
                return None

        now = rt._now_iso()
        import agent_identity

        resolved_agent = agent_identity.normalize_agent_id(agent_id, fallback_source=source)
        attribution = agent_identity.build_write_attribution(
            resolved_agent,
            source,
            timestamp=now,
            action=write_action,
            content_hint=content,
        )
        merged_metadata = agent_identity.merge_attribution_into_metadata(
            metadata, attribution
        )
        import memory_tiers

        tier = memory_tiers.infer_tier(
            memory_type=memory_type,
            pinned=pinned,
            source=source,
            write_action=write_action,
        )
        merged_metadata = memory_tiers.apply_tier_to_metadata(merged_metadata, tier)
        import claim_validation

        merged_metadata, claim_status = claim_validation.enrich_claim_write(
            conn,
            memory_type,
            content,
            merged_metadata,
            project_id=project_id,
        )
        if claim_status == "contested" and status == "active":
            merged_metadata["claim_status"] = "contested"
        metadata_json = json.dumps(
            merged_metadata, sort_keys=True, ensure_ascii=False
        )
        cur = conn.execute(
            """
            INSERT INTO memory_items (
                created_at, updated_at, project_id, memory_type, content, summary,
                importance, source, message_id, decision_id, pinned, status,
                confidence, legacy_memory_id, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                now,
                project_id,
                memory_type,
                content,
                summary,
                importance,
                source,
                message_id,
                decision_id,
                1 if pinned else 0,
                status,
                confidence,
                legacy_memory_id,
                metadata_json,
            ),
        )
        item_id = int(cur.lastrowid)

        try:
            vector = rt.embed_text(content)
            if vector and len(vector) == rt.EMBED_DIM:
                provider = rt._memory_embed_provider()
                model_name = (
                    "text-embedding-3-small"
                    if provider == "openai"
                    else rt.EMBED_MODEL_LOCAL
                )
                rt.index_memory_embedding(conn, item_id, vector, model_name)
        except Exception:
            pass

        saved_row = conn.execute(
            "SELECT * FROM memory_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if saved_row is not None:
            import write_audit

            audit_entity = (
                "handoff"
                if write_action and str(write_action).startswith("handoff.")
                else "memory_item"
            )
            write_audit.record_write_audit(
                agent_id=resolved_agent,
                action=str(write_action or "memory.save"),
                entity_type=audit_entity,
                entity_id=item_id,
                before=None,
                after=write_audit.memory_row_snapshot(saved_row),
                conn=conn,
            )

        if own_conn:
            conn.commit()
        return item_id
    except Exception:
        return None
    finally:
        if own_conn and conn is not None:
            conn.close()


def attach_memory_item_metadata(
    rt: Any,
    memory_item_id: int,
    metadata: dict[str, object],
    *,
    conn: Any | None = None,
) -> bool:
    """Merge metadata onto an existing memory_items row."""
    if not metadata:
        return False
    own_conn = conn is None
    if own_conn:
        conn = rt.connect_db()
    try:
        row = conn.execute(
            "SELECT metadata_json FROM memory_items WHERE id = ?",
            (memory_item_id,),
        ).fetchone()
        if row is None:
            return False
        existing = memory_item_metadata(row) if row else {}
        merged = {**existing, **metadata}
        conn.execute(
            """
            UPDATE memory_items
            SET metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(merged, sort_keys=True, ensure_ascii=False),
                rt._now_iso(),
                memory_item_id,
            ),
        )
        if own_conn:
            conn.commit()
        return True
    finally:
        if own_conn and conn is not None:
            conn.close()
