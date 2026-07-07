"""V4 T9/T10 — spark graph links, bounded expansion, and pruning."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

import sparks

SPARK_LINK_MIN_SIM = 0.75
SPARK_MAX_LINKS = 15
SPARK_LINK_DAILY_RATE = 10
SPARK_LINK_TYPES = frozenset({sparks.SPARK_LINK_TYPE_REINFORCES})
SPARK_GRAPH_MAX_NODES = 50
SPARK_EXPANSION_HOPS_LIGHT = 0
SPARK_EXPANSION_HOPS_MEDIUM = 1
SPARK_EXPANSION_HOPS_DEEP = 2
SPARK_EXPANSION_HOP_DECAY = 0.85
SPARK_EXPANSION_HOPS_BY_DEPTH = {
    "light": SPARK_EXPANSION_HOPS_LIGHT,
    "medium": SPARK_EXPANSION_HOPS_MEDIUM,
    "deep": SPARK_EXPANSION_HOPS_DEEP,
}
SPARK_LINK_PRUNE_CONFIDENCE = 0.3
SPARK_LINK_PRUNE_AGE_DAYS = 30


@dataclass(frozen=True)
class SparkLinkResult:
    ok: bool
    action: Literal["created", "updated", "rejected"] = "rejected"
    link_id: int | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SparkExpansionResult:
    graph_boost: dict[int, float]
    hop_distance: dict[int, int]
    visited_count: int


@dataclass(frozen=True)
class SparkLinkPruneCandidate:
    link_id: int
    from_spark_id: int
    to_spark_id: int
    confidence: float
    updated_at: str


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _resolve_link_confidence(
    confidence: float | None,
    similarity: float | None,
) -> float:
    if confidence is not None:
        final = confidence
    elif similarity is not None:
        final = similarity
    else:
        final = 0.5
    return _clamp01(float(final))


def _load_spark_row(conn: sqlite3.Connection, spark_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sparks WHERE id = ?", (spark_id,)).fetchone()


def _spark_in_scope(
    row: sqlite3.Row,
    *,
    project_id: int | None,
    lanes: frozenset[str] | None,
) -> bool:
    if str(row["trust_state"]) == "rejected":
        return False
    if lanes is not None and str(row["lane"]) not in lanes:
        return False
    row_project = row["project_id"]
    if project_id is None:
        return row_project is None
    return row_project is not None and int(row_project) == project_id


def _incoming_reinforcement(conn: sqlite3.Connection, spark_id: int) -> float:
    row = conn.execute(
        """
        SELECT MAX(confidence) AS max_conf
        FROM spark_links
        WHERE to_spark_id = ? AND link_type = ?
        """,
        (spark_id, sparks.SPARK_LINK_TYPE_REINFORCES),
    ).fetchone()
    if row is None or row["max_conf"] is None:
        return 0.0
    return _clamp01(float(row["max_conf"]))


def _spark_pair_similarity(
    conn: sqlite3.Connection, from_spark_id: int, to_spark_id: int
) -> float | None:
    """Blob cosine only — no runtime embedding."""
    import crowley

    rows = conn.execute(
        """
        SELECT id, embedding_blob FROM sparks
        WHERE id IN (?, ?)
        """,
        (from_spark_id, to_spark_id),
    ).fetchall()
    blobs: dict[int, bytes | None] = {int(row["id"]): row["embedding_blob"] for row in rows}
    left = blobs.get(from_spark_id)
    right = blobs.get(to_spark_id)
    if not left or not right:
        return None
    left_vec = crowley._unpack_embedding(left)
    right_vec = crowley._unpack_embedding(right)
    if not left_vec or not right_vec:
        return None
    return _clamp01(crowley._cosine_similarity(left_vec, right_vec))


def _outgoing_link_count(conn: sqlite3.Connection, from_spark_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM spark_links WHERE from_spark_id = ?",
        (from_spark_id,),
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def _daily_new_link_count(conn: sqlite3.Connection, from_spark_id: int) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM spark_links
        WHERE from_spark_id = ?
          AND datetime(created_at) >= datetime(?)
        """,
        (from_spark_id, cutoff),
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def _find_existing_link(
    conn: sqlite3.Connection,
    from_spark_id: int,
    to_spark_id: int,
    link_type: str,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, confidence FROM spark_links
        WHERE from_spark_id = ? AND to_spark_id = ? AND link_type = ?
        """,
        (from_spark_id, to_spark_id, link_type),
    ).fetchone()


def create_spark_link(
    conn: sqlite3.Connection,
    from_spark_id: int,
    to_spark_id: int,
    link_type: str,
    *,
    confidence: float | None = None,
    explicit_reinforcement: bool = False,
    similarity: float | None = None,
) -> SparkLinkResult:
    """Governed link create/upsert with similarity gate and rate limits."""
    import crowley

    if link_type not in SPARK_LINK_TYPES:
        return SparkLinkResult(ok=False, errors=[f"invalid link_type: {link_type}"])
    if from_spark_id == to_spark_id:
        return SparkLinkResult(ok=False, errors=["self-links are not allowed"])

    from_row = _load_spark_row(conn, from_spark_id)
    to_row = _load_spark_row(conn, to_spark_id)
    if from_row is None or to_row is None:
        return SparkLinkResult(ok=False, errors=["spark not found"])
    if str(from_row["trust_state"]) == "rejected" or str(to_row["trust_state"]) == "rejected":
        return SparkLinkResult(ok=False, errors=["rejected sparks cannot be linked"])

    existing = _find_existing_link(conn, from_spark_id, to_spark_id, link_type)
    incoming_conf = _resolve_link_confidence(confidence, similarity)
    now = crowley._now_iso()

    if existing is not None:
        boosted = min(
            1.0,
            float(existing["confidence"]) + sparks.SPARK_MERGE_CONFIDENCE_BOOST,
        )
        new_conf = max(boosted, incoming_conf)
        conn.execute(
            """
            UPDATE spark_links
            SET confidence = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_conf, now, int(existing["id"])),
        )
        return SparkLinkResult(
            ok=True,
            action="updated",
            link_id=int(existing["id"]),
        )

    resolved_sim = similarity
    if resolved_sim is None and not explicit_reinforcement:
        resolved_sim = _spark_pair_similarity(conn, from_spark_id, to_spark_id)
    if not explicit_reinforcement:
        if resolved_sim is None or resolved_sim < SPARK_LINK_MIN_SIM:
            return SparkLinkResult(
                ok=False,
                errors=[f"similarity below minimum ({SPARK_LINK_MIN_SIM})"],
            )

    if _outgoing_link_count(conn, from_spark_id) >= SPARK_MAX_LINKS:
        return SparkLinkResult(ok=False, errors=["max outgoing links reached"])
    if _daily_new_link_count(conn, from_spark_id) >= SPARK_LINK_DAILY_RATE:
        return SparkLinkResult(ok=False, errors=["daily link rate limit reached"])

    cur = conn.execute(
        """
        INSERT INTO spark_links (
            from_spark_id, to_spark_id, link_type, confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            from_spark_id,
            to_spark_id,
            link_type,
            incoming_conf,
            now,
            now,
        ),
    )
    return SparkLinkResult(
        ok=True,
        action="created",
        link_id=int(cur.lastrowid),
    )


def get_spark_links(
    conn: sqlite3.Connection,
    spark_id: int,
    *,
    direction: Literal["from", "to", "both"] = "both",
    link_type: str | None = None,
) -> list[dict[str, object]]:
    clauses: list[str] = []
    params: list[object] = []
    if direction == "from":
        clauses.append("from_spark_id = ?")
        params.append(spark_id)
    elif direction == "to":
        clauses.append("to_spark_id = ?")
        params.append(spark_id)
    else:
        clauses.append("(from_spark_id = ? OR to_spark_id = ?)")
        params.extend([spark_id, spark_id])
    if link_type is not None:
        clauses.append("link_type = ?")
        params.append(link_type)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT id, from_spark_id, to_spark_id, link_type, confidence,
               created_at, updated_at
        FROM spark_links
        WHERE {where}
        ORDER BY id ASC
        """,
        params,
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "from_spark_id": int(row["from_spark_id"]),
            "to_spark_id": int(row["to_spark_id"]),
            "link_type": str(row["link_type"]),
            "confidence": float(row["confidence"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def _scoped_seed_ids(
    conn: sqlite3.Connection,
    seed_spark_ids: list[int],
    *,
    max_nodes: int,
    project_id: int | None,
    lanes: frozenset[str] | None,
) -> list[int]:
    seed_ids: list[int] = []
    seen: set[int] = set()
    for raw_id in seed_spark_ids:
        if len(seed_ids) >= max_nodes:
            break
        spark_id = int(raw_id)
        if spark_id in seen:
            continue
        row = _load_spark_row(conn, spark_id)
        if row is None or not _spark_in_scope(row, project_id=project_id, lanes=lanes):
            continue
        seen.add(spark_id)
        seed_ids.append(spark_id)
    return seed_ids


def _neighbor_candidates(
    conn: sqlite3.Connection,
    spark_id: int,
    *,
    project_id: int | None,
    lanes: frozenset[str] | None,
    link_type: str,
) -> list[tuple[int, float]]:
    rows = conn.execute(
        """
        SELECT from_spark_id, to_spark_id, confidence
        FROM spark_links
        WHERE (from_spark_id = ? OR to_spark_id = ?)
          AND link_type = ?
        """,
        (spark_id, spark_id, link_type),
    ).fetchall()
    candidates: list[tuple[int, float]] = []
    for row in rows:
        from_id = int(row["from_spark_id"])
        to_id = int(row["to_spark_id"])
        neighbor_id = to_id if from_id == spark_id else from_id
        neighbor = _load_spark_row(conn, neighbor_id)
        if neighbor is None or not _spark_in_scope(
            neighbor, project_id=project_id, lanes=lanes
        ):
            continue
        candidates.append((neighbor_id, _clamp01(float(row["confidence"]))))
    candidates.sort(key=lambda item: (-item[1], item[0]))
    return candidates


def expand_spark_graph(
    conn: sqlite3.Connection,
    seed_spark_ids: list[int],
    *,
    max_hops: int = SPARK_EXPANSION_HOPS_MEDIUM,
    max_nodes: int = SPARK_GRAPH_MAX_NODES,
    project_id: int | None = None,
    lanes: frozenset[str] | None = None,
    link_type: str = sparks.SPARK_LINK_TYPE_REINFORCES,
) -> SparkExpansionResult:
    """Bounded seed-only graph expansion for scored retrieval hits."""
    if max_nodes <= 0 or max_hops < 0 or link_type not in SPARK_LINK_TYPES:
        return SparkExpansionResult(graph_boost={}, hop_distance={}, visited_count=0)

    seed_ids = _scoped_seed_ids(
        conn,
        seed_spark_ids,
        max_nodes=max_nodes,
        project_id=project_id,
        lanes=lanes,
    )
    visited: set[int] = set(seed_ids)
    hop_distance: dict[int, int] = {spark_id: 0 for spark_id in seed_ids}
    graph_boost: dict[int, float] = {
        spark_id: _incoming_reinforcement(conn, spark_id) for spark_id in seed_ids
    }
    queue: list[tuple[int, int]] = [(spark_id, 0) for spark_id in seed_ids]
    cursor = 0

    while cursor < len(queue) and len(visited) < max_nodes:
        current_id, current_hop = queue[cursor]
        cursor += 1
        if current_hop >= max_hops:
            continue

        next_hop = current_hop + 1
        for neighbor_id, confidence in _neighbor_candidates(
            conn,
            current_id,
            project_id=project_id,
            lanes=lanes,
            link_type=link_type,
        ):
            if len(visited) >= max_nodes:
                break
            if neighbor_id in visited:
                continue
            attenuated = _clamp01(confidence * (SPARK_EXPANSION_HOP_DECAY**next_hop))
            graph_boost[neighbor_id] = max(
                graph_boost.get(neighbor_id, 0.0),
                attenuated,
            )
            visited.add(neighbor_id)
            hop_distance[neighbor_id] = next_hop
            queue.append((neighbor_id, next_hop))

    return SparkExpansionResult(
        graph_boost=graph_boost,
        hop_distance=hop_distance,
        visited_count=len(visited),
    )


def prune_spark_links_dry_run(
    conn: sqlite3.Connection,
    *,
    as_of: datetime | None = None,
) -> list[SparkLinkPruneCandidate]:
    """Report weak stale links without deleting rows."""
    now = as_of or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=SPARK_LINK_PRUNE_AGE_DAYS)).isoformat()
    rows = conn.execute(
        """
        SELECT id, from_spark_id, to_spark_id, confidence, updated_at
        FROM spark_links
        WHERE confidence < ?
          AND datetime(updated_at) < datetime(?)
        ORDER BY id ASC
        """,
        (SPARK_LINK_PRUNE_CONFIDENCE, cutoff),
    ).fetchall()
    return [
        SparkLinkPruneCandidate(
            link_id=int(row["id"]),
            from_spark_id=int(row["from_spark_id"]),
            to_spark_id=int(row["to_spark_id"]),
            confidence=float(row["confidence"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]


def update_spark_link_confidence(
    conn: sqlite3.Connection,
    link_id: int,
    confidence: float,
) -> SparkLinkResult:
    import crowley

    if not 0.0 <= confidence <= 1.0:
        return SparkLinkResult(ok=False, errors=["confidence must be between 0 and 1"])
    row = conn.execute("SELECT id FROM spark_links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        return SparkLinkResult(ok=False, errors=["link not found"])
    conn.execute(
        """
        UPDATE spark_links
        SET confidence = ?, updated_at = ?
        WHERE id = ?
        """,
        (_clamp01(confidence), crowley._now_iso(), link_id),
    )
    return SparkLinkResult(ok=True, action="updated", link_id=link_id)
