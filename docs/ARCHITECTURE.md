# Crowley — System Architecture

**Document status:** Reverse-engineered from codebase  
**Last reviewed against code:** 2026-07-08
**Code version:** `CROWLEY_VERSION = "4.0.0"` (`Crowley V4.0 Cognitive Memory`)
**Scope:** Facts from code are stated plainly. Inferences are labeled **(inference)**.

---

## 1. Executive summary

Crowley is a **local-first persistent context layer** for a single user (“D”). It is not one AI model and not only the browser UI; it carries identity, memory, and coordination across reasoning surfaces. It combines:

1. **Conversation** — CLI REPL and web workspace; streaming LLM via OpenAI and/or Ollama.
2. **Episodic memory** — passive sparks + typed `memory_items` with hybrid retrieval.
3. **World model** — structured project state (phase, focus, risk, next action, decisions, open loops).
4. **Diagnostics** — read-only, fact-driven OS briefings.
5. **Autonomous extraction (V3.2)** — conservative background world-model updates from chat.
6. **Local memory bus (V3.7)** — HTTP API for external tools to read context, search memory, submit handoffs.
7. **Knowledge files (V3.7.2)** — query-scored markdown excerpts in prompts and `/api/context`.
8. **Live UI dashboard (V3.7.2)** — `build_world_dashboard()` powers polling browser UI.
9. **Memory consolidation (V3.7.3)** — merge, dedupe, stale marking, optional daily summary.
10. **Memory Trail (V3.8)** — truthful memory counts, canon read path, filtered memory API/UI.
11. **Multi-agent hub (V3.8)** — Codex/Cursor sync via `/api/agent/sync`; Crowley-only messaging.
12. **Agent parity (V3.8.1)** — `agent_activity` in context/sync bundles; stop hook; activity-based verify.
13. **Concurrent ticketing (V3.9)** — `tickets` board, sync mint/claim/close/cancel.
14. **Pre-V4 quality (2026-07)** — V3.9.5 conversation/model behavior **shipped** (#25–#30); V3.9.6 workspace polish **shipped** (#31–#36).
15. **V3.9.7 Experience & Reliability (2026-07)** — UI polish catch-up, embed/CI hardening, `diagnostics.py` + `tickets.py` extraction, operator metrics, preflight (#40–#49).
16. **V3.9.8 Runtime Hardening (2026-07)** — `CROWLEY_TEST_MODE`, model probe, `/api/health` runtime block, sqlite-vec safe fallback, fragile-startup suite (#50–#55).
17. **V3.9.9 Context That Feeds (2026-07)** — memory quality gate, inclusion reasons, slim agent sync, handoff-to-memory upgrade, feedback loop, UI/hygiene (#56–#63).
19. **V3.9.11 Live Wire (2026-07)** — activity pulses, compose wire UI, brain switcher API (#70–#75).
20. **V3.9.12 Portable Context Terminal (2026-07)** — local/manual packet export, structured writeback parse/ingest, staged spark candidates, CLI workflow (#76–#80).
22. **V3.9.14 Durable ChatGPT Bridge (2026-07)** — LaunchAgent service, API-only tunnel ingress, bridge verify tooling, hardened start script.
22. **V4.0 Cognitive Memory (shipped 2026-07-08)** — separate `sparks` / `spark_links` / `patterns` tables layered on `memory_items`; `/api/cognitive/*` namespace; deterministic context orchestration; lifecycle, sensitivity gates, sanitization, validation, rate limits, observability, and lineage ([V4.0_COGNITIVE_MEMORY_RELEASE_LOCK.md](./V4.0_COGNITIVE_MEMORY_RELEASE_LOCK.md)).

Persistence is local SQLite (`crowley.db`). No cloud sync, no MCP (yet). `/api/actions/*` uses bearer auth when `CROWLEY_ACTION_KEY` is set; full internal API remains localhost-first.

---

## 2. Repository layout

| Path | Role |
|------|------|
| `crowley.py` | Engine — CLI, memory, world model, extraction, memory bus (~5600 lines) |
| `diagnostics.py` | Diagnostics domain — gather, prompt, stream tokens (re-exported by engine) |
| `tickets.py` | Ticketing domain — CRUD, summaries, changes feed (re-exported by engine) |
| `chatgpt_actions.py` | Actions router — bearer-auth `/api/actions/*` (V3.9.13) |
| `app.py` | Web transport — FastAPI routes, SSE; no business logic |
| `sparks.py` | V4 spark schema, validation, embeddings, dedup, lineage |
| `spark_extraction.py` | V4 JSON-array spark extraction |
| `cognitive_ingest.py` | V4 cognitive ingest receipt + spark pipeline |
| `spark_retrieval.py` | V4 deterministic spark retrieval and canonical scoring |
| `spark_graph.py` | V4 spark links, graph expansion, pruning |
| `patterns.py` | V4 pattern detection and safety gates |
| `context_orchestration.py` | V4 cognitive context assembly and trace lineage |
| `spark_lifecycle.py` | V4 confidence decay and maintenance |
| `spark_security.py` | V4 sensitivity exposure gates |
| `spark_sanitize.py` | V4 context output sanitization |
| `static/` | Browser workspace UI (V3.5+) |
| `requirements-core.txt` | Core runtime deps (CI + slim installs) |
| `requirements-ml.txt` | Optional ML stack (embeddings, sqlite-vec) |
| `requirements.txt` | Full install (`-r` core + ml) |
| `crowley.db` | SQLite database (gitignored) |
| `.env` | Optional `OPENAI_API_KEY` (gitignored) |
| `docs/` | Engineering documentation |
| `VERSIONS.md` | Release log |

**(inference)** Monolith + thin transport layer: fast iteration, inspectable boundaries.

---

## 3. Runtime topology

```
┌──────────────────────┐     ┌──────────────────────┐
│  CLI main() loop     │     │  app.py (uvicorn)    │
│  crowley.py          │     │  127.0.0.1:8765      │
└──────────┬───────────┘     └──────────┬───────────┘
           │                            │
           │    chat_turn / ingest /    │
           │    build_context_bundle    │
           └────────────┬───────────────┘
                        ▼
              ┌─────────────────┐
              │   crowley.py    │
              │   engine layer  │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │   crowley.db    │
              └─────────────────┘
```

### 3.1 Entry points

| Entry | Path | Notes |
|-------|------|-------|
| CLI | `python crowley.py` | Full slash commands, debug |
| Web UI | `python app.py` | Chat SSE, diagnostics, memory bus |
| External tools | `curl` / scripts → `/api/*` | V3.7 bus |

### 3.2 Background threads

- Spark summarisation (`maybe_create_spark`)
- World-model extraction from chat (`maybe_extract_state`)
- Ingest extraction runs **synchronously** in request handler (Phase 3)

---

## 4. Layered architecture (logical)

| Layer | Responsibility | Key symbols |
|-------|----------------|-------------|
| **Transport** | HTTP, SSE, JSON | `app.py` routes |
| **CLI / commands** | Control surface | `_handle_command`, `main` |
| **Orchestration** | Chat, ingest, context, dashboard | `chat_turn`, `ingest_handoff`, `build_context_bundle`, `build_world_dashboard` |
| **Inference** | Provider routing | `call_model`, `get_model_provider` |
| **Prompting** | Context assembly | `build_prompt`, `list_chat_context_messages` |
| **Memory** | Items, retrieval, sparks | `save_memory_item`, `retrieve_memories`, `save_memory` |
| **Memory bus** | External read/write | `retrieve_memories_api`, `ingest_handoff` |
| **World model** | Projects, state | `get_active_world_context`, `apply_state_proposals` |
| **Diagnostics** | Read-only briefings | `diagnostics.py`: `gather_diagnostics_context`, `iter_diagnostics_tokens` |
| **Ticketing** | Agent work board | `tickets.py`: `create_ticket`, `build_tickets_summary`, `build_recent_changes_feed` |
| **Persistence** | SQLite | `connect_db`, `setup_db` |

---

## 5. Primary request flows

### 5.1 Chat (`chat_turn` / `POST /api/chat`)

```
save_message(user) → build_prompt() → call_model(stream) → save_message(assistant)
  → maybe_create_spark() [background]
  → maybe_extract_state() [background]
```

**`build_prompt()` includes:**

1. Personality + anti-hallucination + greeting rules
2. Source-of-truth knowledge files (`load_knowledge_files_context`)
3. World model (`get_active_world_context`)
4. Hybrid memory (`retrieve_memories`, top 8)
5. Open tasks (top 5)
6. Recent chat turns (last 8, capped 600 chars each)
7. Current user message

### 5.2 Live dashboard (`GET /api/world`)

`build_world_dashboard()` — read-only snapshot: project, state, `phase_progress`, version, counts, tasks, loops, decisions, `memory_items`, `synced_at`. Browser polls every 5s.

### 5.3 Memory bus — read context (`GET /api/context`)

`build_context_bundle()` — read-only aggregate: project, state, decisions, loops, tasks, `retrieve_memories(q)`, `knowledge_files`, `project_files`, system health, `recommended_next_action`.

### 5.4 Memory bus — retrieve (`GET /api/retrieve`)

`retrieve_memories_api()` → `retrieve_memories()` + `get_last_retrieval_mode()`.

### 5.5 Memory bus — ingest (`POST /api/ingest`)

```
validate → resolve project → save_memory_item() [no legacy memories]
  → optional: propose_state_updates() + apply_state_proposals() if gated
```

Additive only. External `source` values (`cursor`, `chatgpt`, etc.) stored on `memory_items`.

### 5.6 Diagnostics

`diagnostics.py`: SQL-only `gather_diagnostics_context()` → format prompt → `iter_diagnostics_tokens()`. Zero writes. Re-exported from `crowley.py` for CLI and `/api/diagnostics`.

---

## 6. Memory subsystem

### 6.1 Dual storage (transition)

| Store | Role | Writes |
|-------|------|--------|
| `memories` | Legacy sparks + `/remember` | Dual-write from `save_memory()` |
| `memory_items` | Canonical typed store | All new paths including ingest |

### 6.2 Retrieval (`retrieve_memories`)

Hybrid scoring: semantic (embedding cosine) + keyword + recency + importance + type inference + project match + pinned bonus.

- Embeddings: OpenAI `text-embedding-3-small` or local `all-MiniLM-L6-v2` @ 384d
- Provider gate: `CROWLEY_EMBED_PROVIDER` env (`off` | `auto` | `local` | `openai`); lazy backfill on retrieve (not at startup)
- Index: sqlite-vec `memory_vec` when loadable; else blob cosine; else keyword-only

`search_memories()` (bag-of-words) retained for legacy/debug.

### 6.3 Ingest path (V3.7)

Handoffs → `memory_items` only. No `messages` row. Extraction reuses V3.2 pipeline with `should_attempt_handoff_extract()` gate.

---

## 7. Model provider architecture

| Constant | Value |
|----------|-------|
| `MODEL_PROVIDER` | `"auto"` |
| `OPENAI_MODEL` | `"gpt-4.1-mini"` |
| `OLLAMA_MODEL` | `"llama3.1:8b"` |

`auto` → OpenAI if `OPENAI_API_KEY` set, else Ollama; one Ollama fallback on OpenAI failure.

---

## 8. World model & extraction

Unchanged core from V3.0–V3.2. Confidence ≥ 0.85, dedupe, no destructive actions.

Ingest uses same `apply_state_proposals()` with world context for resolved project slug.

---

## 9. Web API summary

See [PROJECT_STATE.md](./PROJECT_STATE.md#5-web-api-routes-apppy) for full route table.

---

## 10. SQLite persistence

- WAL mode, `sqlite3.Row` factory
- `setup_db()` creates tables + migrates `memories` → `memory_items`
- No versioned migration framework **(fact)**

---

## 11. Security (code-visible)

| Topic | Behaviour |
|-------|-----------|
| Bind | `127.0.0.1` only |
| API keys | `.env`, gitignored |
| Data | Local SQLite only |
| Destructive auto-actions | None |

---

## 12. Dependency graph (runtime)

```
crowley.py (+ diagnostics.py, tickets.py)
├── ollama
├── openai (lazy)
├── sentence_transformers (lazy, local embed — optional via requirements-ml.txt)
├── sqlite_vec (optional)
├── fastapi / uvicorn (via app.py only)
└── NOT USED at runtime: chromadb (listed in requirements-ml.txt only)
```

---

## 13. Version identifiers

| Symbol | Value (code) |
|--------|----------------|
| `CROWLEY_VERSION` | `"4.0.0"` |
| `CROWLEY_RELEASE_LABEL` | `"Crowley V4.0 Cognitive Memory"` |

---

## 14. Related documents

- [PROJECT_STATE.md](./PROJECT_STATE.md)
- [ENGINEERING_PRINCIPLES.md](./ENGINEERING_PRINCIPLES.md)
- [ROADMAP.md](./ROADMAP.md)
- [DECISION_LOG.md](./DECISION_LOG.md)
- [VERSIONS.md](../VERSIONS.md)
- [V3.6_MEMORY_BACKEND.md](./V3.6_MEMORY_BACKEND.md)
- [V3.8.1_AGENT_PARITY.md](./V3.8.1_AGENT_PARITY.md)
- [V3.8_MEMORY_TRAIL.md](./V3.8_MEMORY_TRAIL.md)
- [V3.7_CONTEXT_BRIDGE.md](./V3.7_CONTEXT_BRIDGE.md)

---

## 15. V3.7 Context Bridge

**Status:** Phases 1–6 shipped — see [V3.7_CONTEXT_BRIDGE.md](./V3.7_CONTEXT_BRIDGE.md).

| Endpoint | Role | Status |
|----------|------|--------|
| `GET /api/context` | Read working context + knowledge files | ✅ |
| `GET /api/retrieve` | Hybrid memory search | ✅ |
| `POST /api/ingest` | External handoffs | ✅ |
| `GET /api/bus/health` | Bus smoke check | ✅ |
| `GET /api/world` | Live UI dashboard | ✅ V3.7.2 |
| `POST /api/tasks/{id}/done` | Complete task | ✅ V3.7.2 |
| `POST /api/consolidate` | Memory consolidation | ✅ V3.7.3 |
| `GET /api/memory-items` | Filtered memory list | ✅ V3.8 |
| `GET /api/agent/sync` | Per-agent sync + canon | ✅ V3.8 |
| `GET/POST/PATCH /api/tickets` | Concurrent ticketing | ✅ V3.9 |
| `POST /api/tickets/{id}/done` | Close ticket | ✅ V3.9 |
| `POST /api/tickets/{id}/cancel` | Cancel superseded ticket | ✅ V3.9.3 |
| `GET /api/memory/hygiene` | Memory hygiene report | ✅ V3.9.2 |
| `GET /api/metrics/summary` | 24h operator metrics rollups | ✅ V3.9.7 |
