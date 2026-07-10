# Crowley Memory Hierarchy

**Status:** V3.9.2 Memory Clarity  
**Principle:** Crowley should feel natural in conversation, but auditable on demand.

This document is the single reference for how truth layers rank. **Canon does not override filesystem docs, tickets, agent activity, or live project state.**

---

## 1. Authority order (facts)

When answering factual questions — version, what shipped, what is open, who last posted — use this order (highest → lowest):

1. **Filesystem truth** — `VERSIONS.md`, `docs/WHERE_WE_ARE.md`, `docs/PROJECT_STATE.md`, phase docs
2. **Tickets** — `/api/tickets`, sync bundle `tickets` (agent work board)
3. **Agent activity** — `last_by_source` on `/api/agent/sync` (handoff timestamps)
4. **Live DB state** — SQLite `project_state`, decisions, open loops (may lag docs slightly)
5. **Canon** — pinned `Canon:` rows in `memory_items` (always-on continuity, not override)
6. **Hybrid retrieval** — `/api/retrieve` (supporting context only)
7. **Recent chat** — current thread window

On conflict: higher layers win. If a canon row disagrees with `VERSIONS.md` or an open ticket, trust the filesystem and tickets first.

---

## 2. Prompt injection order (what Crowley sees in chat)

`build_prompt()` injects layers in this order:

```
Filesystem truth (knowledge files)
  → Live DB state
  → Agent activity
  → Tickets
  → Canon
  → Supporting memory (hybrid retrieval)
  → Recent chat history
```

Canon sits **above hybrid retrieval** in the prompt, but **below** filesystem truth, tickets, agent activity, and live DB state for factual authority.

---

## 3. Work board surfaces (Intelligence drawer)

Crowley tracks three related but distinct lists. Only **tickets** are the agent work board.

| Surface | Table | Purpose | Agent board? |
|---------|-------|---------|--------------|
| **Tickets** | `tickets` | Assigned, prioritized work for Codex/Cursor — mint, claim, ship, close | **Yes** |
| **Tasks** | `tasks` | Lightweight legacy todos with optional due dates | No |
| **Open loops** | `open_loops` | Unresolved questions, risks, and follow-ups from extraction or planning | No |

**Rules:**

- Codex mints **tickets**; Cursor claims and closes them via sync (`--claim-ticket`, `--after --ticket`).
- **Tasks** remain for quick personal todos — do not treat them as the Cursor backlog.
- **Open loops** track uncertainty — they are not substitutes for ticket slices.

Prompt and sync bundles treat **tickets** as authoritative for assigned work (`build_tickets_summary`, agent sync `tickets` block).

---

## 4. UI labels (Memory tab)

| Label | Meaning |
|-------|---------|
| **Canon** | Pinned `Canon:` summary rows — continuity layer, not top authority |
| **Pinned** | Other pinned `memory_items` — elevated but not canon |
| **Memory** | Ordinary stored rows — browse/filter only; chat may also pull via hybrid retrieval |

The Memory tab lists stored rows. Hybrid retrieval matches (used in chat) are labeled **Supporting memory** in prompts and may not appear in the tab list.

---

## 5. Related surfaces

| Surface | Role |
|---------|------|
| Memory tab | Inspect stored rows with layer badges |
| `/api/memory-items` | Filterable list; includes `is_canon`, `memory_layer` |
| `/api/retrieve` | Hybrid search with read-only `explanation` metadata |
| `/api/context`, `/api/agent/sync` | Bundles with top-level `canon` separate from agent events |

---

## 6. Operator docs

- [V3.9.2_CANON_SYNTHESIS_WORKFLOW.md](./V3.9.2_CANON_SYNTHESIS_WORKFLOW.md) — manual canon write path
- [V3.8_MEMORY_TRAIL.md](./V3.8_MEMORY_TRAIL.md) — memory trail API and canon model
- [WHERE_WE_ARE.md](./WHERE_WE_ARE.md) — onboarding summary

---

## 7. V4 cognitive memory (shipped)

**Status:** V4.0 shipped T1–T24 (#203–#226). See [V4.0_COGNITIVE_MEMORY_RELEASE_LOCK.md](./V4.0_COGNITIVE_MEMORY_RELEASE_LOCK.md).

V4 adds a parallel stack **on top of** `memory_items` — it does not replace them.

| Layer | Table / API | Role |
|-------|-------------|------|
| Raw receipt | `memory_items` | Ingest receipt from `POST /api/cognitive/ingest` |
| Sparks | `sparks` | Durable lane-scoped units (max 300 chars); `trust_state` on spark |
| Graph | `spark_links` | Reinforcement edges between sparks |
| Patterns | `patterns` | Cluster summaries from sparks; T12 promotes to `active` only |
| Context bundle | `GET /api/cognitive/context`, `cognitive.context` Actions tool | Read-only orchestration — core/supporting sparks + attached patterns + trace lineage |

**Safeguards:** Cognitive ingest is capped at 32KB and 10/min per source. Spark content is capped at 300 chars. `validate_spark()` rejects instruction-like content, secret patterns, prompt wrappers, raw `MEMORY_DATA` delimiter smuggling, and spark-shaped hallucinated structures. Context output sanitizes returned memory text with neutralization, redaction, and idempotent `MEMORY_DATA` wrapping.

**Sensitivity:** `sensitive` and `high` sparks are exposure-gated by lane. `high` also requires non-light depth and score > 0.7.

**Lineage:** Created sparks store `lineage_json` with `memory_item_id`/`source_memory_item_id`, extraction or seed/writeback metadata, and `dedup_action`; context trace exposes this lineage without changing content authority.

**Authority:** For version and ship status, filesystem docs still win. V4 cognitive tables provide structured recall and context, not canon.

**Legacy note:** CLI trim sparks still use `memories` / implicit spark path. V4 `sparks` table is the new cognitive unit.

**V4.3.2 spark-first (corpus expansion):** After migration + promotion review, `sparks` are the living cognitive log. `memory_items` remain receipts/audit; rows may be marked `archived`/`stale` (never deleted) when represented by sparks or classified as Tier D noise. Cold-start `memory_items` fallback in `build_cognitive_context` remains available but is **exceptional** once active/pinned spark coverage exists — see [V4.3.2_SPARK_CORPUS_EXPANSION_PLAN.md](./V4.3.2_SPARK_CORPUS_EXPANSION_PLAN.md). `retrieve_memories` API is unchanged.
