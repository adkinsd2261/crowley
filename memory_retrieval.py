"""Hybrid memory retrieval, scoring, and explainability."""

from __future__ import annotations

import json
import re
import struct
from datetime import datetime, timezone
from typing import Any


MEMORY_TYPE_INCLUSION_LABELS = {
    "constraint": "constraint memory",
    "decision": "decision memory",
    "preference": "preference memory",
    "lesson": "lesson memory",
    "qa_result": "QA memory",
    "project_update": "project update memory",
    "summary": "summary memory",
    "event": "event memory",
    "bug": "bug memory",
}


def memory_item_excluded_from_retrieval(metadata_json: str | None) -> bool:
    """Skip audit-only cognitive receipts from hybrid retrieval and context paths."""
    if not metadata_json:
        return False
    try:
        meta = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(meta, dict):
        return False
    if meta.get("non_retrieval") is True:
        return True
    intent = str(meta.get("intent") or "").strip().lower()
    return intent in {"ignore", "temporary"}


def get_last_retrieval_mode(rt: Any) -> str:
    """Return mode used by the most recent retrieve_memories() call."""
    return rt._last_retrieval_mode


def unpack_embedding(blob: bytes | None) -> list[float] | None:
    if not blob or len(blob) % 4 != 0:
        return None
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, dot))


def parse_memory_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def recency_score(rt: Any, created_at: str) -> float:
    ts = parse_memory_timestamp(created_at)
    if ts is None:
        return 0.5
    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    if age_days <= rt.MEMORY_RECENCY_HIGH_DAYS:
        return 1.0
    if age_days >= rt.MEMORY_RECENCY_LOW_DAYS:
        return 0.15
    span = rt.MEMORY_RECENCY_LOW_DAYS - rt.MEMORY_RECENCY_HIGH_DAYS
    decay = (age_days - rt.MEMORY_RECENCY_HIGH_DAYS) / span
    return max(0.15, 1.0 - 0.85 * decay)


def importance_score(importance: int) -> float:
    return max(0.0, min(1.0, (int(importance) - 1) / 4))


def project_match_score(item_project_id: int | None, active_project_id: int | None) -> float:
    if active_project_id is None:
        return 0.5 if item_project_id is None else 0.0
    if item_project_id == active_project_id:
        return 1.0
    if item_project_id is None:
        return 0.5
    return 0.0


def infer_query_memory_types(query: str) -> set[str]:
    lower = query.lower()
    types: set[str] = set()
    if any(w in lower for w in ("decision", "decided", "approved", "why did we", "why we")):
        types.add("decision")
    if any(w in lower for w in ("bug", "error", "broke", "broken", "fail", "failed", "failure")):
        types.add("bug")
    if any(w in lower for w in ("qa", "test", "passed", "pass", "regression")):
        types.add("qa_result")
    if any(w in lower for w in ("prefer", "preference", "like", "always", "never")):
        types.add("preference")
    if any(w in lower for w in ("risk", "constraint", "must", "cannot", "can't", "required")):
        types.add("constraint")
    if any(
        w in lower
        for w in ("what happened", "recently", "recent", "session", "last time", "summary")
    ):
        types.update({"summary", "event", "project_update"})
    if any(w in lower for w in ("lesson", "learned", "takeaway")):
        types.add("lesson")
    return types


def type_match_score(memory_type: str, inferred_types: set[str]) -> float:
    if not inferred_types:
        return 0.0
    return 1.0 if memory_type in inferred_types else 0.0


def keyword_score_for_item(tokens: list[str], content: str, summary: str | None) -> float:
    if not tokens:
        return 0.0
    haystack = f"{content} {summary or ''}".lower()
    hits = sum(1 for token in tokens if token in haystack)
    return hits / len(tokens)


def semantic_candidate_scores(
    rt: Any, conn: Any, query_embedding: list[float] | None, limit: int
) -> dict[int, float]:
    if not query_embedding:
        return {}

    if rt._ensure_memory_vec_table(conn):
        try:
            rows = conn.execute(
                """
                SELECT memory_id, distance
                FROM memory_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
                """,
                (rt._vec_bind(query_embedding), limit),
            ).fetchall()
            if rows:
                return {
                    int(row["memory_id"]): max(
                        0.0, min(1.0, 1.0 - float(row["distance"]))
                    )
                    for row in rows
                }
        except Exception:
            pass

    rows = conn.execute(
        """
        SELECT id, embedding_blob, metadata_json
        FROM memory_items
        WHERE status = 'active' AND embedding_blob IS NOT NULL
        """
    ).fetchall()
    scored: list[tuple[int, float]] = []
    for row in rows:
        if memory_item_excluded_from_retrieval(
            str(row["metadata_json"]) if row["metadata_json"] else None
        ):
            continue
        vector = unpack_embedding(row["embedding_blob"])
        if not vector:
            continue
        scored.append((int(row["id"]), cosine_similarity(query_embedding, vector)))
    scored.sort(key=lambda item: item[1], reverse=True)
    return dict(scored[:limit])


def keyword_candidate_scores(rt: Any, conn: Any, query: str, limit: int) -> dict[int, float]:
    tokens = rt._tokenize(query)
    rows = conn.execute(
        "SELECT * FROM memory_items WHERE status = 'active'"
    ).fetchall()
    scored: list[tuple[int, float, int, str]] = []
    for row in rows:
        if memory_item_excluded_from_retrieval(
            str(row["metadata_json"]) if row["metadata_json"] else None
        ):
            continue
        kw = keyword_score_for_item(tokens, str(row["content"]), row["summary"])
        scored.append(
            (int(row["id"]), kw, int(row["importance"]), str(row["created_at"]))
        )
    scored.sort(key=lambda item: (item[1], item[2], item[3]), reverse=True)
    return {item[0]: item[1] for item in scored[:limit]}


def load_active_memory_item(conn: Any, memory_id: int) -> Any | None:
    return conn.execute(
        "SELECT * FROM memory_items WHERE id = ? AND status = 'active'",
        (memory_id,),
    ).fetchone()


def is_canon_memory_row(row: Any) -> bool:
    return (
        str(row["status"]) == "active"
        and str(row["source"]) == "crowley"
        and int(row["pinned"]) == 1
        and str(row["memory_type"]) == "summary"
        and str(row["content"]).startswith("Canon:")
    )


def memory_provenance_ids(row: Any) -> dict[str, int | None]:
    provenance: dict[str, int | None] = {"memory_item_id": int(row["id"])}
    for key in ("message_id", "decision_id", "merged_into_id", "legacy_memory_id"):
        raw = row[key] if key in row.keys() else None
        provenance[key] = int(raw) if raw is not None else None
    return provenance


def available_provenance_ids(provenance: dict[str, int | None]) -> dict[str, int]:
    return {key: value for key, value in provenance.items() if value is not None}


def extract_ticket_refs_from_query(query: str) -> set[int]:
    refs: set[int] = set()
    for match in re.finditer(r"#(\d+)", query):
        refs.add(int(match.group(1)))
    for match in re.finditer(r"\bticket\s+(\d+)\b", query, re.IGNORECASE):
        refs.add(int(match.group(1)))
    return refs


def query_relates_to_ticket(rt: Any, query: str, ticket_row: Any) -> bool:
    ticket_id = int(ticket_row["id"])
    if ticket_id in extract_ticket_refs_from_query(query):
        return True
    title = str(ticket_row["title"])
    query_tokens = set(rt._tokenize(query))
    title_tokens = set(rt._tokenize(title))
    if not query_tokens:
        return False
    overlap = query_tokens & title_tokens
    if len(overlap) >= 2:
        return True
    return bool(overlap) and len(overlap) / len(query_tokens) >= 0.34


def memory_relates_to_ticket(rt: Any, row: Any, ticket_row: Any) -> bool:
    """True when memory content references a ticket, not just the retrieval query."""
    ticket_id = int(ticket_row["id"])
    summary = row["summary"] if "summary" in row.keys() else None
    content = f"{row['content']} {summary or ''}"
    lower = content.lower()
    if re.search(rf"#\s*{ticket_id}\b", content):
        return True
    if f"ticket #{ticket_id}" in lower:
        return True
    title = str(ticket_row["title"])
    stop = {
        "and",
        "or",
        "the",
        "for",
        "to",
        "a",
        "v3",
        "9",
        "context",
        "cursor",
        "codex",
    }
    content_tokens = set(rt._tokenize(content)) - stop
    title_tokens = set(rt._tokenize(title)) - stop
    overlap = content_tokens & title_tokens
    if len(overlap) >= 3:
        return True
    return len(overlap) >= 2 and len(title_tokens) >= 4


def build_inclusion_reason(
    rt: Any,
    row: Any,
    *,
    query: str,
    score_breakdown: dict[str, float],
    linked_ticket_ids: list[int],
    open_tickets_by_id: dict[int, Any],
) -> str:
    """Human-readable reason this memory was included in retrieval."""
    factors: list[str] = []
    memory_type = str(row["memory_type"])
    source = str(row["source"])

    for ticket_id in linked_ticket_ids:
        ticket = open_tickets_by_id.get(ticket_id)
        if ticket is None:
            factors.append(f"linked to ticket #{ticket_id}")
            continue
        if ticket_id in open_tickets_by_id:
            factors.append(f"linked to open ticket #{ticket_id}")
        else:
            factors.append(f"linked to ticket #{ticket_id}")

    if not any("ticket #" in factor for factor in factors):
        for ticket_id, ticket in open_tickets_by_id.items():
            if memory_relates_to_ticket(rt, row, ticket):
                factors.append(f"matches open ticket #{ticket_id}")
                break

    if source in rt.INGEST_SOURCES:
        if linked_ticket_ids:
            factors.append("handoff link")
        else:
            factors.append("agent handoff")

    type_score = float(score_breakdown.get("type_match", 0.0))
    type_label = MEMORY_TYPE_INCLUSION_LABELS.get(memory_type, f"{memory_type} memory")
    if type_score >= 1.0 or memory_type in {
        "constraint",
        "decision",
        "lesson",
        "qa_result",
        "preference",
    }:
        factors.append(type_label)

    if float(score_breakdown.get("recency", 0.0)) >= 0.85:
        factors.append("recent")

    keyword = float(score_breakdown.get("keyword", 0.0))
    semantic = float(score_breakdown.get("semantic", 0.0))
    if keyword >= 0.25:
        factors.append("keyword match")
    elif semantic >= 0.25:
        factors.append("semantic match")

    if int(row["pinned"]):
        factors.append("pinned")

    if is_canon_memory_row(row):
        factors.append("canon memory")

    deduped: list[str] = []
    for factor in factors:
        if factor not in deduped:
            deduped.append(factor)

    if not deduped:
        deduped.append("hybrid score rank")

    return "Pulled because: " + " + ".join(deduped[:4])


def build_retrieval_explanation(
    rt: Any,
    row: Any,
    *,
    score: float,
    score_breakdown: dict[str, float],
    retrieval_mode: str,
    query: str = "",
    linked_ticket_ids: list[int] | None = None,
    open_tickets_by_id: dict[int, Any] | None = None,
) -> dict[str, object]:
    provenance = memory_provenance_ids(row)
    linked = list(linked_ticket_ids or [])
    open_map = open_tickets_by_id or {}
    inclusion_reason = build_inclusion_reason(
        rt,
        row,
        query=query,
        score_breakdown=score_breakdown,
        linked_ticket_ids=linked,
        open_tickets_by_id=open_map,
    )
    return {
        "source": str(row["source"]),
        "memory_type": str(row["memory_type"]),
        "status": str(row["status"]),
        "pinned": bool(int(row["pinned"])),
        "is_canon": is_canon_memory_row(row),
        "score": score,
        "score_breakdown": score_breakdown,
        "retrieval_mode": retrieval_mode,
        "provenance": provenance,
        "provenance_available": available_provenance_ids(provenance),
        "inclusion_reason": inclusion_reason,
        "attribution": rt._memory_item_attribution(row),
    }


def score_memory_item(
    rt: Any,
    row: Any,
    *,
    semantic: float,
    keyword: float,
    active_project_id: int | None,
    inferred_types: set[str],
) -> tuple[float, dict[str, float]]:
    recency = recency_score(rt, str(row["created_at"]))
    importance = importance_score(int(row["importance"]))
    type_match = type_match_score(str(row["memory_type"]), inferred_types)
    project_match = project_match_score(
        int(row["project_id"]) if row["project_id"] is not None else None,
        active_project_id,
    )
    pinned_bonus = rt.W_SCORE_PINNED_BONUS if int(row["pinned"]) else 0.0
    import memory_tiers

    tier_bonus = memory_tiers.retrieval_tier_boost(
        str(row["metadata_json"]) if row["metadata_json"] else None,
        pinned=bool(int(row["pinned"])),
    )
    breakdown = {
        "semantic": round(semantic, 4),
        "keyword": round(keyword, 4),
        "recency": round(recency, 4),
        "importance": round(importance, 4),
        "type_match": round(type_match, 4),
        "project_match": round(project_match, 4),
        "pinned_bonus": round(pinned_bonus, 4),
        "tier_bonus": round(tier_bonus, 4),
    }
    score = (
        rt.W_SCORE_SEMANTIC * semantic
        + rt.W_SCORE_KEYWORD * keyword
        + rt.W_SCORE_RECENCY * recency
        + rt.W_SCORE_IMPORTANCE * importance
        + rt.W_SCORE_TYPE * type_match
        + rt.W_SCORE_PROJECT * project_match
        + pinned_bonus
        + tier_bonus
    )
    return round(score, 4), breakdown


def retrieve_memories(
    rt: Any,
    query: str,
    limit: int,
    project_id: int | None = None,
    conn: Any | None = None,
) -> list[dict[str, object]]:
    """
    Hybrid retrieval over memory_items.
    Returns scored dicts with explanation metadata and stable ranking behavior.
    """
    owns_conn = conn is None
    conn = conn or rt.connect_db()
    try:
        rt._lazy_backfill_embeddings(conn)
        active_project_id = project_id
        if active_project_id is None:
            project = conn.execute(
                "SELECT id FROM projects WHERE status = 'active' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            active_project_id = int(project["id"]) if project else None

        query_embedding = rt.embed_text(query)
        semantic_scores = semantic_candidate_scores(
            rt, conn, query_embedding, rt.MEMORY_RETRIEVE_VECTOR_CANDIDATES
        )
        keyword_scores = keyword_candidate_scores(
            rt, conn, query, rt.MEMORY_RETRIEVE_KEYWORD_CANDIDATES
        )

        candidate_ids: set[int] = set(semantic_scores) | set(keyword_scores)

        pinned_rows = conn.execute(
            "SELECT id FROM memory_items WHERE status = 'active' AND pinned = 1"
        ).fetchall()
        for row in pinned_rows:
            candidate_ids.add(int(row["id"]))

        summary_rows = conn.execute(
            """
            SELECT id FROM memory_items
            WHERE status = 'active' AND memory_type = 'summary'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (rt.MEMORY_RETRIEVE_SUMMARY_CANDIDATES,),
        ).fetchall()
        for row in summary_rows:
            candidate_ids.add(int(row["id"]))

        inferred_types = infer_query_memory_types(query)
        open_tickets_by_id: dict[int, Any] = {}
        if active_project_id is not None:
            for ticket_row in rt.list_tickets(
                project_id=active_project_id, open_only=True, limit=50
            ):
                open_tickets_by_id[int(ticket_row["id"])] = ticket_row
        open_ticket_ids = set(open_tickets_by_id.keys())
        linked_by_mem = rt._tickets_by_linked_memory_ids(list(candidate_ids))
        import memory_ticket_linkage

        max_ticket_id = memory_ticket_linkage.max_ticket_id(conn)
        query_ticket_ids: set[int] = set()
        import handoff_ticket_bridge

        for ticket_id in handoff_ticket_bridge.extract_referenced_ticket_ids(query):
            if 1 <= ticket_id <= max_ticket_id:
                query_ticket_ids.add(ticket_id)
        query_ticket_rows: dict[int, Any] = {}
        for ticket_id in query_ticket_ids:
            ticket_row = conn.execute(
                "SELECT * FROM tickets WHERE id = ?",
                (ticket_id,),
            ).fetchone()
            if ticket_row is not None:
                query_ticket_rows[ticket_id] = ticket_row
        results: list[dict[str, object]] = []
        semantic_used = bool(query_embedding and semantic_scores)

        for memory_id in candidate_ids:
            row = load_active_memory_item(conn, memory_id)
            if row is None:
                continue
            if memory_item_excluded_from_retrieval(
                str(row["metadata_json"]) if row["metadata_json"] else None
            ):
                continue
            score, breakdown = score_memory_item(
                rt,
                row,
                semantic=semantic_scores.get(memory_id, 0.0),
                keyword=keyword_scores.get(memory_id, 0.0),
                active_project_id=active_project_id,
                inferred_types=inferred_types,
            )
            linked_ticket_ids = linked_by_mem.get(memory_id, [])
            ticket_boost = 0.0
            if query_ticket_ids and any(
                ticket_id in query_ticket_ids for ticket_id in linked_ticket_ids
            ):
                ticket_boost = rt.W_SCORE_OPEN_TICKET_BOOST
            elif open_ticket_ids and any(
                ticket_id in open_ticket_ids for ticket_id in linked_ticket_ids
            ):
                ticket_boost = rt.W_SCORE_OPEN_TICKET_BOOST
            elif query_ticket_rows:
                for ticket_row in query_ticket_rows.values():
                    if memory_relates_to_ticket(rt, row, ticket_row):
                        ticket_boost = rt.W_SCORE_OPEN_TICKET_BOOST * 0.85
                        break
            elif open_ticket_ids:
                for ticket_id in open_ticket_ids:
                    ticket_row = open_tickets_by_id[ticket_id]
                    if memory_relates_to_ticket(rt, row, ticket_row):
                        ticket_boost = rt.W_SCORE_OPEN_TICKET_BOOST * 0.75
                        break
            if ticket_boost:
                score = round(float(score) + ticket_boost, 4)
                breakdown = dict(breakdown)
                breakdown["open_ticket_boost"] = round(ticket_boost, 4)
            display = rt._memory_display_text(row)
            row_summary = str(row["summary"]) if row["summary"] else ""
            source_text = f"{row['content']} {row_summary}".strip()
            row_confidence = row["confidence"] if "confidence" in row.keys() else 1.0
            results.append(
                {
                    "id": memory_id,
                    "memory_type": str(row["memory_type"]),
                    "content": display,
                    "source_text": source_text,
                    "importance": int(row["importance"]),
                    "confidence": round(float(row_confidence), 4),
                    "source": str(row["source"]),
                    "created_at": str(row["created_at"]),
                    "project_id": int(row["project_id"])
                    if row["project_id"] is not None
                    else None,
                    "pinned": bool(int(row["pinned"])),
                    "score": score,
                    "score_breakdown": breakdown,
                    "_row": row,
                }
            )

        results.sort(
            key=lambda item: (
                float(item["score"]),
                int(item["importance"]),
                str(item["created_at"]),
            ),
            reverse=True,
        )

        if semantic_used:
            rt._last_retrieval_mode = "vector+keyword"
        else:
            rt._last_retrieval_mode = "keyword-only fallback"

        rt.record_system_metric(
            "retrieval",
            label=rt._last_retrieval_mode,
            payload={"count": len(results[:limit])},
        )

        mode = rt._last_retrieval_mode
        memory_ids = [int(item["id"]) for item in results]
        linked_map = rt._tickets_by_linked_memory_ids(memory_ids)
        if not open_tickets_by_id and active_project_id is not None:
            for ticket_row in rt.list_tickets(
                project_id=active_project_id, open_only=True, limit=50
            ):
                open_tickets_by_id[int(ticket_row["id"])] = ticket_row

        finalized: list[dict[str, object]] = []
        for item in results:
            row = item.pop("_row")  # type: ignore[misc]
            memory_id = int(item["id"])
            explanation = build_retrieval_explanation(
                rt,
                row,
                score=float(item["score"]),
                score_breakdown=dict(item["score_breakdown"]),  # type: ignore[arg-type]
                retrieval_mode=mode,
                query=query,
                linked_ticket_ids=linked_map.get(memory_id, []),
                open_tickets_by_id=open_tickets_by_id,
            )
            item["status"] = explanation["status"]
            item["is_canon"] = explanation["is_canon"]
            item["provenance"] = explanation["provenance"]
            item["provenance_available"] = explanation["provenance_available"]
            item["inclusion_reason"] = explanation["inclusion_reason"]
            item["explanation"] = explanation
            import memory_tiers

            item["memory_tier"] = memory_tiers.tier_from_metadata_json(
                str(row["metadata_json"]) if row["metadata_json"] else None
            )
            if int(row["pinned"]):
                item["memory_tier"] = "canonical"
            finalized.append(item)
        results = finalized

        top = results[:limit]
        if top:
            now = rt._now_iso()
            for item in top:
                conn.execute(
                    """
                    UPDATE memory_items
                    SET access_count = access_count + 1, last_accessed_at = ?
                    WHERE id = ?
                    """,
                    (now, int(item["id"])),
                )
            conn.commit()
        return top
    finally:
        if owns_conn:
            conn.close()
