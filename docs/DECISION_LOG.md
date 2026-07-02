# Crowley — Decision Log

**Purpose:** Record significant architectural and product decisions — what was chosen, what was rejected, and evidence from code or release history.  
**Format:** ADR-inspired entries.  
Inferences marked **(inference)**.

---

## How to read this log

| Field | Meaning |
|-------|---------|
| **Status** | Accepted = reflected in shipped code |
| **Evidence** | File/function or VERSIONS.md reference |
| **Alternatives** | Options considered or implied by omissions |

New decisions should append entries at the top (newest first) when shipping versions.

---

## ADR-036 — V3.9.7 Workspace Experience & Reliability shipped

**Date:** 2026-07-02
**Status:** Accepted
**Evidence:** `crowley.py` version `3.9.7`, `diagnostics.py`, `tickets.py`, `docs/V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md`, tickets `#40–#49`, **157 tests**, `scripts/preflight.py`, `/api/health` embed flags

### Context

External review: backend depth outran daily UX. V3.9.6 established the right direction; V3.9.7 closes the experience gap while hardening startup and CI underneath.

### Decision

- Bump to `CROWLEY_VERSION = "3.9.7"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.7 Workspace Experience & Reliability"`
- Ship experience polish (drawer, chat readability, cohesion, work surfaces) and reliability (embed fallback, CI slim deps)
- Extract first monolith slices: `diagnostics.py`, `tickets.py`
- Add operator metrics foundation and `scripts/preflight.py`
- Pause V4 connectivity until Mr. Go browser QA approves polished workspace

### Rejected

- Deferring UI polish behind monolith extraction
- Requiring Torch/sentence-transformers for CI or test runs
- New chat personality or backend features in this release

---

## ADR-035 — V3.9.6 Workspace Polish shipped (Pre-V4 quality plan complete)

**Date:** 2026-07-02
**Status:** Accepted
**Evidence:** `crowley.py` version `3.9.6`, `docs/V3.9.6_WORKSPACE_POLISH.md`, tickets `#31–#36`, **147 tests**, bus restart QA on `127.0.0.1:8765`

### Context

Pre-V4 quality plan required a livable browser workspace before V4 connectivity.

### Decision

- Bump to `CROWLEY_VERSION = "3.9.6"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.6 Workspace Polish"`
- Ship panel states, streaming polish, navigation flow, what-changed feed, livability pass, and onboarding doc lock
- Declare Pre-V4 quality plan (V3.9.5 + V3.9.6) complete; V4 connectivity is the next initiative

### Rejected

- Visual redesign in V3.9.6
- V4 collectors before quality plan completion
- Deduplicating closeout events in Changes feed (deferred polish)

---

## ADR-034 — V3.9.5 Conversation + Model Behavior shipped

**Date:** 2026-07-02
**Status:** Accepted
**Evidence:** `crowley.py` version `3.9.5`, `docs/V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md`, tickets `#25–#30`, **140 tests**

### Context

Pre-V4 quality plan required deterministic prompt/controller behavior before workspace polish and V4 connectivity.

### Decision

- Bump to `CROWLEY_VERSION = "3.9.5"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.5 Conversation + Model Behavior"`
- Ship mode classifier, depth controller, co-founder personality trim, diagnostics tone separation, regression fixtures, and confirmed chat UX fixes
- Lock onboarding docs to reflect V3.9.5 shipped; active initiative becomes V3.9.6

### Rejected

- Visible conversation-mode UI toggle
- Live model-quality regression tests
- Broad chat redesign in V3.9.5

---

## ADR-033 — V4 doc lock at V3.9.4 (Pre-V4 ladder complete)

**Date:** 2026-07-02
**Status:** Accepted
**Evidence:** `crowley.py` version constants, `docs/V3.9.4_AGENT_VISIBILITY.md`, onboarding doc sweep (#23)

### Context

V3.9.2–V3.9.4 shipped on `main` under version constant `3.9.1` per ADR-032. Ticket `#23` required a single shipped label and locked onboarding docs before V4 external collectors.

### Decision

- Bump to `CROWLEY_VERSION = "3.9.4"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.4 Agent Visibility"`
- Mark Pre-V4 release ladder complete in `WHERE_WE_ARE`, `PROJECT_STATE`, `ROADMAP`, `TICKETS`, `VERSIONS`, `PRE_V4_RELEASE_PLAN`
- Declare V4 readiness gate satisfied; V4 connectivity begins when Codex mints implementation tickets
- Add `docs/V3.9.4_AGENT_VISIBILITY.md` as the release spec

### Rejected

- Bumping to `4.0.0` before any V4 connectivity ships
- Per-slice version bumps (3.9.2, 3.9.3, 3.9.4 as separate constants mid-ladder)

---

## ADR-032 — Pre-V4 release ladder is memory-led

**Date:** 2026-07-01
**Status:** Accepted
**Evidence:** `docs/PRE_V4_RELEASE_PLAN.md`, `tickets/pre_v4_release_plan.json`

### Context

Crowley reached a stable V3.9.1 baseline with memory backend, canon path, agent sync, tickets, git, and CI. Before adding V4 external collectors, memory behavior and planning flow need to be trustworthy enough that additional inputs do not create confusion.

### Decision

- Ship three focused pre-V4 releases: V3.9.2 Memory Clarity, V3.9.3 Planning Workflow, V3.9.4 Agent Visibility
- Keep the product principle: Crowley should feel natural in conversation, but auditable on demand
- Treat draft tickets `#4-#8` as superseded planning artifacts and replace them with Cursor tickets `#9-#23`
- Defer V4 connectivity until canon, retrieval inspection, planning packets, agent visibility, and test isolation are in place

### Rejected

- Jumping directly to V4 collectors
- One giant Cursor prompt for all pre-V4 work
- Making memory overly rigid or destructive

---

## ADR-031 — GitHub repository baseline and Actions CI (V3.9.1)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `.github/workflows/tests.yml`, `.gitignore`, remote `github.com/adkinsd2261/crowley`, `docs/V3.9.1_REPOSITORY_AND_CI.md`

### Context

V3.9 shipped concurrent ticketing but the workspace lacked version control and automated regression. Handoff `Files Changed` sections depended on git; fifty-two unit tests only ran manually.

### Decision

- Initialize git with secrets/DB/venv excluded; push baseline to GitHub `main`
- Add GitHub Actions workflow running `python -m unittest discover -s tests -q` on push/PR
- Use Python 3.12 on `ubuntu-latest`; 20-minute timeout for cold embedding-model cache
- Defer agent feed UI tab and automated canon synthesis to post-V3.9.1

### Alternatives

- Local-only git without remote — rejected; no backup or CI trigger surface
- Skip heavy deps in CI — rejected; would not gate embedding/memory tests
- CircleCI / self-hosted runner — rejected; GitHub Actions matches repo host

---

## ADR-030 — Unified tickets for multi-agent work (V3.9)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `tickets` / `ticket_events` tables, `/api/tickets`, `scripts/codex_sync.py --create-ticket`, `scripts/cursor_sync.py --ticket`, `tests/test_tickets.py`

### Context

V3.8 multi-agent sync moved memory and handoffs through Crowley, but work assignment remained fragmented across `tasks`, `open_loops`, and markdown. Codex plans could not mint queryable builder work; Cursor could not claim or close tickets via the bus.

### Decision (planned)

- Add `tickets` + `ticket_events` as the agent work board
- Codex creates via `--create-ticket(s)`; Cursor closes via `--after --ticket ID`
- Expose tickets on sync bundles and in `build_prompt()`
- Keep legacy `tasks` / `open_loops`; do not delete

### Rejected

- Markdown `TICKETS.md` as source of truth
- Direct Codex → Cursor assignment outside Crowley
- Auto-ticket from every chat line

---

## ADR-029 — Agent activity feed and activity-based verify (V3.8.1)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `_agent_activity_summary()`, `build_context_bundle()`, `build_agent_sync_bundle()`, `scripts/agent_sync_lib.py`, `.cursor/hooks/session-stop.sh`

### Context

V3.8 multi-agent sync existed but Crowley chat could not answer "when did you last hear from Cursor?" reliably. Post-ingest verify used fuzzy `/api/retrieve`. `/api/context` lacked the same agent timestamps injected into chat prompts. Cursor sessions could end without handoffs.

### Decision

- `_agent_activity_summary()` computes `last_by_source` from recent `memory_items` events
- Inject **Agent activity** into every `build_prompt()`; expose same object on `/api/context` and `/api/agent/sync`
- `verify_agent_handoff()` in `agent_sync_lib` confirms ingest via `last_by_source`, not retrieve
- Cursor `stop` hook runs `--session-end`; session marker cleared only after successful verify
- Shared `agent_sync_lib` for display + verify across `codex_sync.py` and `cursor_sync.py`

### Rejected

- Fuzzy retrieve as post-ingest verify (unreliable ranking)
- Auto-posting handoffs on session end (warn only; builder still runs `--after`)

---

## ADR-028 — Multi-agent hub via Crowley only (V3.8)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `scripts/codex_sync.py`, `scripts/cursor_sync.py`, `GET /api/agent/sync`, `CODEX.md`, `.cursor/rules/crowley-memory.mdc`

### Context

Codex (planning) and Cursor (building) needed shared context without manual relay. Direct agent-to-agent messaging would bypass Crowley's world model and memory governance.

### Decision

- Crowley is the **only** hub; agents read each other via `events_from_other_agents` in `/api/agent/sync`
- Codex posts `architect_handoff` / `builder_handoff` / `note`; Cursor posts `builder_handoff` / `note`
- Sync scripts refuse placeholder/empty scaffolds at ingest
- Cursor hooks (`sessionStart`, `beforeSubmitPrompt`, `stop`) auto-pull before prompts and warn on session end without handoff
- `scripts/ensure_crowley_bus.sh` auto-starts bus on `127.0.0.1:8765`

### Rejected

- Direct Codex ↔ Cursor communication
- Turn-by-turn sync (handoff granularity only)

---

## ADR-027 — Canonical memory trail (V3.8)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `list_canon_memory_items()`, `build_prompt()` canon block, `scripts/synthesize_canon.py`, `tests/test_memory_trail.py`

### Context

Memory grew large and noisy; UI showed misleading counts; agents needed a stable distilled layer without mixing handoffs into canon.

### Decision

- Canon stored as pinned `memory_items` with `Canon:` prefix — no new table
- Canon exposed as top-level `canon` in context/sync bundles, excluded from agent event feeds
- Precedence: project_state + knowledge files > canon > hybrid retrieval > chat
- Synthesis manual-first via `synthesize_canon.py --write`; six layers; archive old canon on write
- Memory UI/API report real `memory_active` / `memory_total` with filters

### Rejected

- Auto canon synthesis on every ingest
- Canon overriding project_state or knowledge files
- Treating displayed row count as total memory

---

## ADR-026 — Memory consolidation pipeline (V3.6 Phase 4 / V3.7.3)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `consolidate_memories()`, `memory_consolidation_runs`, `merge_implicit_since_session_summary`, `POST /api/consolidate`

### Context

`memory_items` grew linearly with trim sparks and duplicates; no merge, stale, or rollup jobs existed.

### Decision

- Session summaries supersede implicit trim events in-window (`status=merged`)
- Nightly-style duplicate merge via cosine ≥ 0.92 (same project, compatible types)
- Stale marking for old low-importance never-accessed items — never auto-delete
- Daily summary opt-in via `MEMORY_DAILY_SUMMARY=1`
- Audit runs in `memory_consolidation_runs`
- Bump retrieval `access_count` on use

### Rejected

- Auto-delete stale memories
- LLM merge of duplicate content in Phase 4 (deferred)

---

## ADR-025 — Live UI dashboard polling (V3.7.2)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `build_world_dashboard()`, `parse_phase_progress()`, `GET /api/world`, `static/app.js` live poll, `POST /api/tasks/{id}/done`

### Context

Browser UI only refreshed on page load or after chat — external work (Cursor, CLI, ingest) left panels stale.

### Decision

- Single `build_world_dashboard()` snapshot for `/api/world` (state + all intelligence panels + counts + `synced_at`)
- Browser polls every 5s and on tab focus
- Parse `Phase N/M` from `project_state.phase` for progress bar
- Task completion via CLI `/task done`, API, and UI ✓ button

### Rejected

- WebSocket push (overkill for local single-user)
- Schema fields for structured phase progress (parse from existing `phase` text)

---

## ADR-024 — Knowledge files context layer (V3.7.2)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `KNOWLEDGE_FILES`, `load_knowledge_files_context()`, `build_prompt()` source-of-truth section, `/api/context` `knowledge_files` key

### Context

Crowley invented version history or gave stale answers when markdown docs disagreed with memory.

### Decision

- Whitelist 7 markdown paths; query-scored capped excerpts
- Prefer `CROWLEY_VERSION` + knowledge files over user claims
- Extraction skips state updates on `conflicts with source-of-truth files`

### Rejected

- Full repo RAG / indexing all source files

---

## ADR-023 — Local memory bus, ingest without legacy dual-write (V3.7)

**Date:** 2026-06-30  
**Status:** Accepted (Phases 1–6 complete at V3.7.2)  
**Evidence:** `build_context_bundle`, `retrieve_memories_api`, `ingest_handoff`, `bus_health`; inbox scripts; VERSIONS.md V3.7

### Context

Cursor, ChatGPT, and Codex need read/write access to Crowley's brain without MCP or copy-paste.

### Decision

Expose localhost HTTP bus on `127.0.0.1:8765`. Engine functions in `crowley.py`; `app.py` transport only.

- **Read:** `GET /api/context`, `GET /api/retrieve`
- **Write:** `POST /api/ingest` → `save_memory_item()` only (no legacy `memories`, no `messages`)
- Optional extraction via existing `propose_state_updates()` + `should_attempt_handoff_extract()` gate
- `metadata` accepted but not persisted in Phase 3

### Rejected

- MCP server, auth, cloud sync (V3.7 MVP boundaries)
- Dual-write ingest to legacy `memories`
- Creating chat `messages` rows for handoffs

---

## ADR-022 — memory_items + hybrid retrieval (V3.6)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `memory_items` table, `retrieve_memories()`, `save_memory_item()`, `embed_text()`; VERSIONS.md V3.6

### Context

Bag-of-words `search_memories()` missed paraphrases; sparks lacked structure and embeddings.

### Decision

- New `memory_items` table with typed `memory_type`, embeddings, project scope
- sqlite-vec index with blob cosine fallback
- Hybrid scoring in `retrieve_memories()` wired into `build_prompt()`
- Dual-write from `save_memory()` for chat paths; ingest path writes `memory_items` only

### Supersedes (partially)

ADR-013 bag-of-words as primary retrieval — retained for debug only.

---

## ADR-021 — Web transport layer separate from engine (V3.5)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `app.py`, `static/`, `chat_turn()`; VERSIONS.md V3.5

### Context

Browser workspace needed without duplicating business logic.

### Decision

FastAPI + static files on `127.0.0.1:8765`. All logic in `crowley.py`. SSE for chat and diagnostics. Slash commands rejected in web with CLI hint.

### Rejected

- Business logic in `app.py` or frontend JS
- Public bind / auth layer

---

## ADR-020 — Autonomous world-model extraction (V3.2)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `maybe_extract_state`, `propose_state_updates`, `apply_state_proposals`; VERSIONS.md V3.2

### Context

V3.0 added manual world model. V3.1 added read-only diagnostics. Users should not need `/state set` for every conversational shift in focus.

### Decision

After each assistant reply, optionally run background extraction from the **user message** when `should_attempt_state_extract()` passes. Model proposes JSON; code applies only high-confidence, non-destructive updates.

### Rules encoded

- Confidence ≥ 0.85
- Additive only (decisions, loops, state fields)
- Dedupe decisions (24h), open loops (normalized)
- `updated_by = "extract"`
- Quiet by default; `/debug extract` for dry-run

### Rejected

- Auto-delete, auto-close loops, auto-archive, auto project switch
- Confirmation UX in this phase (uncertain → skip)
- Extracting from assistant messages alone

---

## ADR-019 — Diagnostics as read-only SQL → format pipeline (V3.1)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `gather_diagnostics_context`, `run_diagnostics`, `is_diagnostics_request`

### Context

User wants morning-style OS briefings without Crowley inventing project status.

### Decision

Diagnostics gathers facts from SQLite only, serializes to ground-truth text, asks model to **format** a fixed-section report. No `ask_crowley`, no message save, no sparks.

### Rejected

- Diagnostics updating world model
- Diagnostics using episodic memory inference for missing fields

---

## ADR-018 — World model as first-class prompt context (V3.0)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `projects`, `project_state`, `decisions`, `open_loops`; `get_active_world_context`

### Context

Sparks are unstructured; project phase/focus/risk need authoritative structured state.

### Decision

Add relational world model tables. Inject `Current project state` section into `build_prompt()`. Manual commands for inspection and override.

### Rejected **(inference)**

- Storing phase/focus only in free-text sparks
- Multi-active projects in UX (schema allows multiple rows; runtime picks first active)

---

## ADR-017 — Unified `call_model()` provider layer (V2.6)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `call_model`, `get_model_provider`, `_call_openai`, `_call_ollama`

### Context

Ollama-only brain limits quality; OpenAI available via API key.

### Decision

Single inference function with `MODEL_PROVIDER` = `ollama` | `openai` | `auto`. Auto prefers OpenAI when `OPENAI_API_KEY` set; one Ollama fallback on OpenAI failure.

### Notes

- Current code default: `MODEL_PROVIDER = "auto"` **(fact)**
- VERSIONS.md V2.6 still documents default `"ollama"` — documentation drift **(fact)**

### Rejected

- Separate code paths per feature for providers
- Exposing API key in `/debug brain`

---

## ADR-016 — Co-architect personality with anti-hallucination (V2.5)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `_personality_prompt()`, VERSIONS.md V2.5

### Context

Generic chatbot tone and invented user facts reduce trust.

### Decision

Mr. Go / D addressing; calm systems-minded voice; explicit rule to say “I don't have that stored yet” when facts absent from retrieved context.

### Rejected

- Default Jarvis theatrical mode (reserved for future `/mode jarvis` per VERSIONS.md)

---

## ADR-015 — Passive spark filtering (V2.5)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `should_create_implicit_spark`, `has_enough_signal_for_summary`

### Context

V2 created sparks on all user messages → noise in memory.

### Decision

Gate trim sparks with keyword lists, length thresholds, shell/greeting/skip-phrase filters. Gate summary sparks with signal check on batch.

### Rejected

- Prompting user “Save to memory?” on each message **(inference)**

---

## ADR-014 — Background spark creation with thread-safe DB (V2)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `create_spark`, `maybe_create_spark`, `_spark_lock`

### Context

Summarisation calls slow model; must not block REPL.

### Decision

Daemon thread after threshold; fresh SQLite connection per spark; non-blocking lock.

### Rejected

- Synchronous summarisation in `ask_crowley` **(inference)**

---

## ADR-013 — Bag-of-words memory retrieval (V1)

**Date:** 2026-06-30  
**Status:** Accepted (interim)  
**Evidence:** `search_memories`, `_tokenize`

### Context

Need memory retrieval without heavy ML stack at bootstrap.

### Decision

Token overlap scoring with importance and recency tie-breakers.

### Future

Vector search planned (chromadb in requirements, unused) — see ADR-009.

---

## ADR-012 — SQLite as sole datastore (V1)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `setup_db`, `DB_PATH`, WAL pragma

### Context

Local single-user assistant; minimal ops burden.

### Decision

File-based SQLite alongside script; WAL mode; no ORM.

### Rejected **(inference)**

- Postgres, cloud DB, separate memory service

---

## ADR-011 — Monolithic single-file application (V1)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** entire app in `crowley.py` (~4000 lines)

### Context

Fast iteration for personal tool; small scope.

### Decision

One Python file until complexity forces split.

### Rejected **(inference)**

- Early package structure (`crowley/` package with submodules)

---

## ADR-010 — Commands as control surfaces, not primary UX (V3)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** V3 phase specs; `main()` flow; autonomous hooks on `ask_crowley`

### Context

Risk of “CLI command bot” vs natural assistant.

### Decision

Default path is conversation. Commands for override, inspection, diagnostics. World model updates from chat in V3.2.

---

## ADR-009 — Vector retrieval via sqlite-vec, not ChromaDB (V3.6)

**Date:** 2026-07-01 (updated 2026-06-30)  
**Status:** Accepted — ChromaDB still unused  
**Evidence:** `embed_text()`, `sqlite_vec`, `memory_items`; `chromadb` not imported

### Context

Vector retrieval planned since V2.6; Chroma listed in requirements but never wired.

### Decision (V3.6)

Use sqlite-vec + `embedding_blob` in same `crowley.db`. Local `sentence-transformers` or OpenAI embeddings. Chroma remains unused optional dep.

### Rationale

Single-file local-first; no second persistence layer.

---

## ADR-008 — Default Ollama model `llama3.1:8b` (V2.6)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `OLLAMA_MODEL = "llama3.1:8b"`; VERSIONS.md notes Qwen instability

### Context

Initial spec used `jaahas/qwen3.5-uncensored`; operational instability.

### Decision

Switch default to `llama3.1:8b`.

---

## ADR-007 — `.env` for secrets, never committed (V2.6)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `_load_local_env`, `.gitignore`, `.env.example`

### Context

OpenAI key needed in dev; must not land in git.

### Decision

Load `.env` at import; gitignore `.env`; example template only.

---

## ADR-006 — Prompt context: retrieval + sliding chat window (V1+ / V3.6.0)

**Date:** 2026-06-30 (updated V3.6.0)  
**Status:** Accepted  
**Evidence:** `build_prompt` injects `retrieve_memories`, world model, tasks, and last 8 `messages` via `list_chat_context_messages`

### Context

Unbounded chat history blows token limits.

### Decision

Rely on hybrid retrieval + world model + last 8 chat turns for context; store full log in `messages` for sparks/extraction/debug.

### Tradeoff **(inference)**

Very long sessions still depend on summary sparks and world model for facts not in the recent window.

---

## ADR-005 — Extraction errors fail silently (V3.2)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `_run_extraction` `except Exception: pass`

### Context

Background maintenance must not break chat or print scary tracebacks.

### Decision

Swallow extraction exceptions; rely on `/debug extract` for investigation.

### Tradeoff

Silent failures may leave stale world model without user awareness.

---

## ADR-004 — `save_message` returns row id (V3.2)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `save_message` → `int`; `message_id` on `save_decision` from extract

### Context

Decisions should link to grounding user message for audit.

### Decision

Return inserted id; pass to `apply_state_proposals` as `message_id` when source is extract.

---

## ADR-003 — Natural-language diagnostics trigger (V3.1)

**Date:** 2026-07-01  
**Status:** Accepted  
**Evidence:** `is_diagnostics_request` in `main()` before `ask_crowley`

### Context

“Morning diagnostics” should work without slash command.

### Decision

Trigger `run_diagnostics()` when message contains `diagnostics` and (short message OR morning words).

### Caveat

Also excluded from extraction via `is_diagnostics_request` in `should_attempt_state_extract`.

---

## ADR-002 — Importance scale 1–5 for memories (V2.5)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `/remember` validation; spark importance 1 and 2

### Context

Need priority without complex schema.

### Decision

Integer 1–5; sparks use 1 (trim) and 2+ (summary threshold).

---

## ADR-001 — Passive episodic memory (“sparks”) (V2)

**Date:** 2026-06-30  
**Status:** Accepted  
**Evidence:** `create_spark`, `memories.type = 'spark'`

### Context

Manual `/remember` alone misses conversational facts.

### Decision

Automatic episodic capture: trim on signal, summary after N messages.

### Rejected **(inference)**

- Full always-on conversation RAG without filtering

---

## Open decisions (not yet resolved)

| ID | Question | Options | Notes |
|----|----------|---------|-------|
| OD-01 | Task done status value | `done` vs `closed` | Tasks only have `open` today |
| OD-02 | Vector index scope | memories only vs sparks + decisions | Deps unused |
| OD-03 | Extraction audit log | new table vs file log | Silent failures today |
| OD-04 | Multi-project UX | commands vs auto-detect project | Schema ready |
| OD-05 | Module split trigger | LOC threshold vs contributor count | Monolith at ~4000 LOC |
| OD-06 | Medium-confidence extraction | queue vs inline ask | Deferred from V3.2 |
| OD-07 | Normalize `tasks.project` | FK to `projects.slug` vs keep free text | No join today |
| OD-08 | Version constant vs V3.7 APIs | bump at Phase 6 vs now | **Resolved** — `3.7.2` |

---

## Rejected decisions (explicit non-goals)

| Item | Reason | Source |
|------|--------|--------|
| Web UI | Scope was CLI-only through V3.2; **shipped V3.5** | Superseded |
| Auto-delete/archive | Safety | V3.2 spec |
| Auto project switch | Safety | V3.2 spec |
| Vector search in V3.2 | Phase boundary | V3.2 spec — **shipped V3.6** |
| External collectors in V3.2 | Phase boundary | V3.2 spec |
| Confirmation UX in V3.2 | Phase boundary | V3.2 spec |
| Extract on assistant-only text | Grounding rule | V3.2 spec |

---

## Related documents

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [PROJECT_STATE.md](./PROJECT_STATE.md)
- [ENGINEERING_PRINCIPLES.md](./ENGINEERING_PRINCIPLES.md)
- [ROADMAP.md](./ROADMAP.md)
- [VERSIONS.md](../VERSIONS.md)
