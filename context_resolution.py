"""V4 T14 — cross-source context resolution and depth modes."""

from __future__ import annotations

import re
from typing import Any

CONTEXT_DEPTHS = frozenset({"light", "medium", "deep"})

DEPTH_LIMITS: dict[str, dict[str, int | bool]] = {
    "light": {"resolved": 12, "matched_tickets": 0, "expand_related": False},
    "medium": {"resolved": 12, "matched_tickets": 5, "expand_related": False},
    "deep": {"resolved": 20, "matched_tickets": 10, "expand_related": True},
}

COGNITIVE_DEPTH_LIMITS: dict[str, dict[str, int]] = {
    "light": {"core": 12, "supporting": 0, "patterns": 5},
    "medium": {"core": 12, "supporting": 20, "patterns": 5},
    "deep": {"core": 12, "supporting": 20, "patterns": 5},
}

COLD_START_ACTIVE_SPARK_THRESHOLD = 10
CLUSTER_JACCARD_THRESHOLD = 0.55
SIGNATURE_PHRASE_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+)+\b")

_DOMINANCE_RANK = {"handoff": 3, "memory": 2, "ticket": 1}


def normalize_depth(depth: str | None, *, default: str | None = None) -> str | None:
    if depth is None:
        return default
    normalized = str(depth).strip().lower()
    if normalized not in CONTEXT_DEPTHS:
        raise ValueError(f"invalid depth: {depth}")
    return normalized


def count_active_sparks(
    conn: Any,
    *,
    project_id: int | None = None,
) -> int:
    if project_id is None:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM sparks
            WHERE trust_state IN ('active', 'pinned')
            """
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM sparks
            WHERE trust_state IN ('active', 'pinned')
              AND ((project_id IS NULL AND ? IS NULL) OR project_id = ?)
            """,
            (project_id, project_id),
        ).fetchone()
    return int(row["n"]) if row is not None else 0


def _tokenize(text: str) -> list[str]:
    tokens = re.split(r"[^a-z0-9]+", text.lower())
    return [token for token in tokens if len(token) >= 3]


def _token_jaccard(left: str, right: str) -> float:
    left_tokens = set(_tokenize(left))
    right_tokens = set(_tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def signature_phrases(*texts: str) -> set[str]:
    phrases: set[str] = set()
    for text in texts:
        for match in SIGNATURE_PHRASE_RE.findall(text or ""):
            phrases.add(match.upper())
    return phrases


def query_matches_ticket(query: str, ticket: dict[str, Any]) -> bool:
    """True when query explicitly relates to a ticket title or shared signature phrase."""
    title = str(ticket.get("title") or "")
    description = str(ticket.get("description") or "")
    ticket_text = f"{title} {description}".strip()
    if not query.strip() or not ticket_text:
        return False
    query_signatures = signature_phrases(query)
    ticket_signatures = signature_phrases(ticket_text)
    if query_signatures & ticket_signatures:
        return True
    title_upper = title.upper()
    for phrase in query_signatures:
        for part in phrase.split("-"):
            if len(part) >= 3 and part in title_upper:
                return True
    query_tokens = set(_tokenize(query))
    title_tokens = set(_tokenize(title))
    if not query_tokens or not title_tokens:
        return False
    overlap = query_tokens & title_tokens
    if len(overlap) >= 2:
        return True
    return bool(overlap) and len(overlap) / len(query_tokens) >= 0.34


def _memory_signal_kind(memory: dict[str, Any]) -> str:
    import crowley

    memory_type = str(memory.get("memory_type") or "")
    source = str(memory.get("source") or "")
    if memory_type in ("project_update", "summary") and source in crowley.INGEST_SOURCES:
        return "handoff"
    if source in crowley.INGEST_SOURCES and memory_type in crowley.INGEST_TYPES:
        return "handoff"
    return "memory"


def _memory_text(memory: dict[str, Any]) -> str:
    source_text = memory.get("source_text")
    if source_text:
        return str(source_text)
    content = str(memory.get("content") or "")
    summary = str(memory.get("summary") or "")
    return f"{content} {summary}".strip()


def memory_signals_related(left: str, right: str) -> bool:
    """Cluster memories only on direct overlap, not query-bridged similarity."""
    if signature_phrases(left) & signature_phrases(right):
        return True
    return _token_jaccard(left, right) >= CLUSTER_JACCARD_THRESHOLD


def _cluster_memories(
    memories: list[dict[str, Any]],
    query: str,
) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for memory in memories:
        text = _memory_text(memory)
        placed = False
        for cluster in clusters:
            if memory_signals_related(text, _memory_text(cluster[0])):
                cluster.append(memory)
                placed = True
                break
        if not placed:
            clusters.append([memory])
    return clusters


def _ticket_relates_to_cluster(
    ticket: dict[str, Any],
    cluster_texts: list[str],
    query: str,
) -> bool:
    if not query_matches_ticket(query, ticket):
        return False
    ticket_text = f"{ticket.get('title', '')} {ticket.get('description', '')}"
    query_signatures = signature_phrases(query)
    for text in cluster_texts:
        if memory_signals_related(ticket_text, text):
            return True
        if query_signatures and query_signatures & signature_phrases(text):
            return True
    return False


def _dominance_key(kind: str, score: float, item_id: int) -> tuple[int, float, int]:
    return (_DOMINANCE_RANK.get(kind, 0), score, item_id)


def _merge_inclusion_reason(
    primary: dict[str, Any],
    suppressed: list[dict[str, Any]],
    tickets: list[dict[str, Any]],
) -> str:
    base = str(primary.get("inclusion_reason") or "Pulled because: hybrid score rank")
    if not suppressed and not tickets:
        return base
    parts: list[str] = []
    if suppressed:
        parts.append(f"merged {len(suppressed)} duplicate signal(s)")
    if tickets:
        parts.append(f"{len(tickets)} linked ticket(s)")
    return f"{base}; dominant — {'; '.join(parts)}"


def cross_source_resolve(
    memories: list[dict[str, Any]],
    *,
    matched_tickets: list[dict[str, Any]] | None = None,
    query: str = "",
    depth: str = "medium",
    debug: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Cluster cross-system signals and return one dominant item per topic cluster."""
    limits = DEPTH_LIMITS[depth]
    tickets = list(matched_tickets or [])
    clusters = _cluster_memories(memories, query)

    resolved: list[dict[str, Any]] = []
    used_ticket_ids: set[int] = set()
    suppressed_count = 0
    clusters_formed = 0

    for cluster in clusters:
        cluster_texts = [_memory_text(memory) for memory in cluster]
        cluster_tickets = [
            ticket
            for ticket in tickets
            if int(ticket.get("id") or 0) not in used_ticket_ids
            and _ticket_relates_to_cluster(ticket, cluster_texts, query)
        ]
        if len(cluster) > 1 or cluster_tickets:
            clusters_formed += 1

        candidates: list[tuple[str, dict[str, Any], str, float, int]] = []
        for memory in cluster:
            kind = _memory_signal_kind(memory)
            score = float(memory.get("score") or 0.0)
            candidates.append(
                ("memory", memory, kind, score, int(memory.get("id") or 0))
            )
        if not candidates:
            continue

        candidates.sort(
            key=lambda item: _dominance_key(item[2], item[3], item[4]),
            reverse=True,
        )
        dominant = dict(candidates[0][1])
        dominant_id = int(dominant.get("id") or 0)
        suppressed = [
            memory for memory in cluster if int(memory.get("id") or 0) != dominant_id
        ]
        suppressed_count += len(suppressed)

        related_signals: list[dict[str, Any]] = []
        for memory in suppressed:
            related_signals.append(
                {
                    "kind": _memory_signal_kind(memory),
                    "id": int(memory.get("id") or 0),
                    "role": "suppressed_duplicate",
                    "score": memory.get("score"),
                }
            )
        for ticket in cluster_tickets:
            ticket_id = int(ticket.get("id") or 0)
            used_ticket_ids.add(ticket_id)
            related_signals.append(
                {
                    "kind": "ticket",
                    "id": ticket_id,
                    "role": "topic_match",
                    "title": ticket.get("title"),
                }
            )

        if len(cluster) > 1 or related_signals:
            dominant["resolved"] = True
            dominant["dominant_source"] = _memory_signal_kind(dominant)
            dominant["related_signals"] = related_signals
            dominant["inclusion_reason"] = _merge_inclusion_reason(
                dominant,
                suppressed,
                cluster_tickets,
            )
            if debug and suppressed:
                dominant["suppressed_raw"] = suppressed
        else:
            dominant["resolved"] = False

        resolved.append(dominant)

    resolved.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    resolved_limit = int(limits["resolved"])
    resolved = resolved[:resolved_limit]

    matched_out: list[dict[str, Any]] = []
    matched_limit = int(limits["matched_tickets"])
    if matched_limit > 0:
        for ticket in tickets:
            ticket_id = int(ticket.get("id") or 0)
            if ticket_id in used_ticket_ids:
                continue
            if not query_matches_ticket(query, ticket):
                continue
            matched_out.append(
                {
                    "id": ticket_id,
                    "title": ticket.get("title"),
                    "status": ticket.get("status"),
                    "assignee": ticket.get("assignee"),
                    "priority": ticket.get("priority"),
                    "linked_memory_id": ticket.get("linked_memory_id"),
                    "role": "query_matched",
                }
            )
            if len(matched_out) >= matched_limit:
                break

    trace = {
        "depth": depth,
        "lanes_used": ["memory", "ticket"],
        "clusters_formed": clusters_formed,
        "suppressed_count": suppressed_count,
        "resolved_count": len(resolved),
        "matched_ticket_count": len(matched_out),
        "selection_reason": (
            "cross-source resolver: handoff > memory > ticket per topic cluster"
        ),
        "score_basis": "hybrid retrieval score with dominance tie-break",
        "lineage": [],
        "fallback_used": False,
    }
    return resolved, matched_out, trace


def apply_memory_fallback_trace(
    trace: dict[str, Any],
    *,
    active_spark_count: int,
    fallback_used: bool,
) -> dict[str, Any]:
    updated = dict(trace)
    updated["active_spark_count"] = active_spark_count
    updated["fallback_used"] = fallback_used
    if fallback_used:
        updated["selection_reason"] = (
            f"{updated.get('selection_reason', '')}; memory_items fallback (active sparks "
            f"< {COLD_START_ACTIVE_SPARK_THRESHOLD})"
        ).strip("; ")
    return updated
