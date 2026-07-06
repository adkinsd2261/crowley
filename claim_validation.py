"""#176 — minimal claim metadata and conflict marking on memory writes."""

from __future__ import annotations

import json

CLAIM_MEMORY_TYPES = frozenset({"decision", "constraint"})
CLAIM_STATUSES = frozenset({"active", "contested", "stale"})


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {t for t in left.lower().split() if len(t) > 2}
    right_tokens = {t for t in right.lower().split() if len(t) > 2}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def enrich_claim_write(
    conn,
    memory_type: str,
    content: str,
    metadata: dict[str, object] | None,
    *,
    project_id: int | None,
) -> tuple[dict[str, object], str]:
    """
    Attach claim_status to metadata and downgrade stale contested peers.
    Returns (metadata, status).
    """
    import crowley

    merged: dict[str, object] = dict(metadata or {})
    normalized = memory_type.strip().lower()
    if normalized not in CLAIM_MEMORY_TYPES:
        return merged, "active"

    merged["claim_status"] = "active"
    merged["claim_topic"] = crowley._truncate(content.strip(), 120)

    contested_ids: list[int] = []
    if project_id is not None:
        rows = conn.execute(
            """
            SELECT id, content, metadata_json FROM memory_items
            WHERE project_id = ? AND memory_type = ? AND status = 'active'
            ORDER BY id DESC LIMIT 40
            """,
            (int(project_id), normalized),
        ).fetchall()
        for row in rows:
            other_id = int(row["id"])
            other_content = str(row["content"] or "")
            if _token_overlap(content, other_content) < 0.45:
                continue
            import memory_quality

            if normalized == "constraint" and memory_quality._constraints_are_conflicting(  # noqa: SLF001
                content, other_content
            ):
                contested_ids.append(other_id)
                merged["claim_status"] = "contested"
            elif normalized == "decision" and _token_overlap(content, other_content) >= 0.55:
                contested_ids.append(other_id)

    for peer_id in contested_ids:
        peer = conn.execute(
            "SELECT metadata_json FROM memory_items WHERE id = ?",
            (peer_id,),
        ).fetchone()
        if peer is None:
            continue
        try:
            peer_meta = json.loads(str(peer["metadata_json"] or "{}"))
        except json.JSONDecodeError:
            peer_meta = {}
        if not isinstance(peer_meta, dict):
            peer_meta = {}
        peer_meta["claim_status"] = "contested"
        conn.execute(
            """
            UPDATE memory_items
            SET metadata_json = ?, updated_at = ?, status = 'active'
            WHERE id = ?
            """,
            (
                json.dumps(peer_meta, sort_keys=True, ensure_ascii=False),
                crowley._now_iso(),
                peer_id,
            ),
        )

    status = "contested" if merged.get("claim_status") == "contested" else "active"
    return merged, status
