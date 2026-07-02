# Crowley Version Log

Single source of truth for release history. Update this file at the end of every version.

**Current:** V3.9.1 (`Crowley V3.9.1 Repository & CI`)  
**Next planned:** V3.9.2 Memory Clarity, V3.9.3 Planning Workflow, V3.9.4 Agent Visibility, then V4 connectivity

| Version | Status   | Date       | Summary                                      |
|---------|----------|------------|----------------------------------------------|
| V1      | shipped  | 2026-06-30 | CLI + SQLite + Ollama + manual `/remember`   |
| V2      | shipped  | 2026-06-30 | Passive sparks, `/task`, auto episodic memory |
| V2.5    | shipped  | 2026-06-30 | UX, personality, spark filtering, streaming  |
| V2.6    | shipped  | 2026-07-01 | OpenAI/Ollama routing; default `llama3.1:8b` |
| V3.0    | shipped  | 2026-07-01 | World model Phase 1 — manual project state   |
| V3.1    | shipped  | 2026-07-01 | Diagnostics engine (read-only)               |
| V3.2    | shipped  | 2026-07-01 | Autonomous world model extraction              |
| V3.5    | shipped  | 2026-06-30 | Web workspace UI (FastAPI + static cockpit)  |
| V3.6.0  | shipped  | 2026-06-30 | Chat context window in `build_prompt()`        |
| V3.6    | shipped  | 2026-06-30 | Memory backend — items, embed, hybrid retrieval |
| V3.7    | shipped  | 2026-06-30 | Context bridge — API + inbox handoff scripts |
| V3.7.1  | shipped  | 2026-07-01 | QA patch — greeting, truth guard, UI gap       |
| V3.7.2  | shipped  | 2026-07-01 | Knowledge files + live UI sync               |
| V3.7.3  | shipped  | 2026-07-01 | V3.6 Phase 4 memory consolidation            |
| V3.8    | shipped  | 2026-07-01 | Memory Trail + multi-agent sync              |
| V3.8.1  | shipped  | 2026-07-01 | Agent parity — stop hook, shared verify, activity feed |
| V3.9    | shipped  | 2026-07-01 | Concurrent ticketing — unified agent work board |
| V3.9.1  | shipped  | 2026-07-01 | GitHub repo baseline + GitHub Actions CI |

---

## V1 — Foundation

**Files:** `crowley.py`, `requirements.txt`, `crowley.db`

- Interactive CLI (`exit` / `/exit`)
- SQLite: `messages`, `memories`, `tasks` tables
- Ollama integration (`ollama.chat`)
- Bag-of-words `search_memories()`
- Manual `/remember type | importance | content`
- Core functions: `connect_db`, `setup_db`, `save_message`, `save_memory`, `build_prompt`, `ask_crowley`, `main`

**Model:** `jaahas/qwen3.5-uncensored` (initial spec)

---

## V2 — Passive Memory

- Implicit trim sparks on user messages
- `create_spark()` episodic summarisation after N messages
- `maybe_create_spark()` + optional background timer (disabled by default)
- `/task add` and `/task list`
- Open tasks injected into `build_prompt()`
- Thread-safe `create_spark()` (fresh SQLite connection per call)
- Startup: `Crowley V2 online`

---

## V2.5 — UX & Memory Quality

**Theme:** Make Crowley feel worth using daily — not a chatbot.

- `should_create_implicit_spark()` — filter greetings, shell commands, noise
- `has_enough_signal_for_summary()` — skip low-value summary sparks
- Co-architect personality prompt (Mr. Go / D, no Jarvis-speak by default)
- Anti-hallucination rule in system prompt
- Startup banner: Go for Crowley / Morning, Mr. Go
- `Crowley: thinking...` + Ollama streaming
- `/remember` importance validated (1–5)
- Spark thread guard (`_spark_running`)
- Debug commands: `/debug memories`, `sparks`, `tasks`, `prompt`

**QA:** Approved as working MVP (2026-06-30)

---

## V2.6 — Swappable Brain

- `MODEL_PROVIDER`: `ollama` | `openai` | `auto`
- `get_model_provider()`, `call_model()` unified inference layer
- OpenAI streaming + auto-mode Ollama fallback (once)
- `summarize_messages()` uses `call_model(stream=False, quiet=True)`
- `/debug brain` — provider config, no API key exposure
- Startup shows `Brain: Ollama / llama3.1:8b`

**Defaults (current code):**
```python
MODEL_PROVIDER = "auto"
OPENAI_MODEL = "gpt-4.1-mini"
OLLAMA_MODEL = "llama3.1:8b"
```

**Dependencies:** `ollama`, `openai`, `chromadb` (unused), `sentence-transformers` (used in V3.6 for local embeddings)

---

## V3.0 — World Model (Phase 1)

**Theme:** V2 remembers. V3 tracks reality (manual state layer).

- Tables: `projects`, `project_state`, `decisions`, `open_loops`
- Default seed: active project `Crowley` / `crowley`
- Commands: `/state`, `/state set <field>: <value>`, `/decisions`, `/loops`
- `get_active_world_context()` injected into `build_prompt()`
- No diagnostics mode, no auto extraction (Phase 2/3)

---

## V3.1 — Diagnostics (Phase 2)

**Theme:** Self-aware OS briefing — read-only, fact-driven.

- `gather_diagnostics_context()` — SQL-only facts
- `format_diagnostics_prompt()` — anti-hallucination formatting prompt
- `run_diagnostics()` — stream briefing, zero writes
- `/diagnostics` command
- Natural-language trigger: `diagnostics` + (`morning`/`mornin`/`good morning` OR message &lt; 60 chars)
- Web: `GET /api/diagnostics` (SSE)

---

## V3.2 — Autonomous World Model (Phase 3)

**Theme:** Conversation maintains project state — conservative, inspectable, non-destructive.

- `should_attempt_state_extract()` — keyword/signal gating on user messages only
- `propose_state_updates()` — strict JSON via model (`call_model` quiet)
- `apply_state_proposals()` — confidence ≥ 0.85, dedupe, no deletes/closes
- `maybe_extract_state()` — background thread after assistant reply
- `/debug extract <message>` — dry-run inspect
- `/world` and `/debug world` — read-only world summary
- `save_message()` returns message id for extraction grounding

---

## V3.5 — Chat UI (Web Workspace)

**Theme:** Cockpit for long-running thinking — workspace, not chatbot.

**Files:** `app.py`, `static/index.html`, `static/styles.css`, `static/app.js`

- FastAPI transport on `127.0.0.1:8765` — engine logic stays in `crowley.py`
- SSE streaming: `POST /api/chat`, `GET /api/diagnostics`
- Read APIs: messages, world, tasks, loops, decisions, sparks, health
- Workspace-first layout: document stream, integrated composer, project inspector
- Collapsible **Intelligence** drawer (tasks / loops / decisions / sparks)
- Current objective from world state (`focus` / `next_action`)
- Thinking orb during inference; hides on first streamed token
- Web slash commands rejected with CLI hint; diagnostics read-only in-chat
- CLI (`python crowley.py`) unchanged — parallel entry point

**Run:** `./venv/bin/python3 app.py` → http://127.0.0.1:8765

**QA:** Approved (2026-06-30)

---

## V3.6.0 — Chat Context Continuity

**Theme:** Mid-session continuity without waiting for memory retrieval.

- `build_prompt()` includes last 8 messages from `messages` table (`CHAT_CONTEXT_LIMIT`)
- Excludes current user message (`exclude_message_id` from `chat_turn`)
- Per-message cap via `CHAT_CONTEXT_MESSAGE_MAX_LEN` (600 chars)
- World model and hybrid memory retrieval unchanged in priority
- `/debug prompt` shows context turns

**No schema changes.**

---

## V3.6 — Memory Backend

**Theme:** Infrastructure for semantic memory — schema, migration, embeddings, hybrid retrieval.

**Approved plan:** [docs/V3.6_MEMORY_BACKEND.md](docs/V3.6_MEMORY_BACKEND.md)

**Phase 1 shipped:**

- `memory_items` table (typed episodic store; migrates from `memories`)
- Idempotent `migrate_memories_to_memory_items()` on `setup_db()`
- `embed_text()` — local `all-MiniLM-L6-v2` or OpenAI `text-embedding-3-small` @ 384d
- `embedding_blob` on every embedded item; `memory_vec` sqlite-vec index when extensions load
- Graceful degrade when SQLite extensions unavailable (blob cosine fallback)

**Phase 2 shipped:**

- `retrieve_memories()` — hybrid semantic + keyword + recency + importance + type + project + pinned scoring
- `build_prompt()` uses `memory_items` via hybrid retrieval (`Relevant long-term memory` section)
- `/debug retrieve <query>` — score breakdown + retrieval mode
- `search_memories()` retained for legacy/debug paths

**Phase 3 shipped:**

- `save_memory_item()` — insert, dedupe (24h), embed, index
- `save_memory()` dual-writes legacy `memories` + `memory_items`
- `/remember`, implicit sparks, and summary sparks land in `memory_items`
- `/debug memory-items` — inspect recent memory_items

**Not yet:** external collectors

**Phase 4 shipped (V3.7.3):** session implicit merge, duplicate detection, stale marking, optional daily summary, `memory_consolidation_runs` audit table

**UI:** Memory tab reads `memory_items` via `GET /api/memory-items` (V3.7.2)

**Dependencies added:** `sqlite-vec`, `fastapi`, `uvicorn`

---

## V3.7 — Context Bridge

**Theme:** Crowley as shared external brain for Cursor, ChatGPT, Codex, and browser UI.

**Plan:** [docs/V3.7_CONTEXT_BRIDGE.md](docs/V3.7_CONTEXT_BRIDGE.md)

**Shipped:**

| Component | Description |
|-----------|-------------|
| `GET /api/context` | Read-only world + memory bundle |
| `GET /api/retrieve` | Hybrid memory search |
| `POST /api/ingest` | Handoff → `memory_items` + optional extraction |
| `GET /api/bus/health` | Bus health check |
| `.crowley/inbox/` | Handoff drop folder |
| `.crowley/processed/` | Post-ingest archive |
| `scripts/ingest_inbox.py` | Inbox → engine or `--via-http` |
| `scripts/crowley_handoff.py` | Handoff template generator |
| `/debug bus` | CLI bus health |

**Version:** `CROWLEY_VERSION = "3.7"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.7 Context Bridge"`

**QA:** Approved (2026-06-30)

---

## V3.7.1 — QA Patch

**Theme:** Reliability and truthfulness without new major features.

**Shipped:**

| Fix | Description |
|-----|-------------|
| Greeting repetition | No repeated "Morning, Mr. Go" mid-session |
| UI bottom gap | CSS spacing flush below chat/composer |
| Project files context | Capped `VERSIONS.md` + `PROJECT_STATE.md` in prompt |
| Response depth | Concise default, expand for architecture/QA/planning |
| State extraction guard | Skip version claims conflicting with constants/docs |

**Version:** `CROWLEY_VERSION = "3.7.1"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.7.1 QA Patch"`

---

## V3.7.2 — Knowledge Files Context

**Theme:** Read-only markdown knowledge layer for version/docs/architecture truth.

**Shipped:**

| Component | Description |
|-----------|-------------|
| `KNOWLEDGE_FILES` | Whitelisted markdown paths (7 files) |
| `load_knowledge_files_context()` | Query-scored capped excerpts |
| `build_prompt()` | Source-of-truth project files section |
| `/api/context` | `knowledge_files` key |
| `/debug knowledge <query>` | CLI debug for file selection |
| Extraction guard | `conflicts with source-of-truth files` skip reason |
| UI Memory tab | `/api/memory-items` shows recent `memory_items` |
| Cursor rule | `.cursor/rules/crowley-memory.mdc` — handoff hygiene |

**Version:** `CROWLEY_VERSION = "3.7.2"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.7.2 Knowledge Files Context"`

**Live UI sync (same version constant, 2026-07-01):**

| Component | Description |
|-----------|-------------|
| `build_world_dashboard()` | Unified `/api/world` snapshot for live UI |
| Live polling | Browser refreshes every 5s + on tab focus |
| Phase progress bar | Parses `Phase N/M` from `project_state.phase` |
| Intelligence polish | Tab badges, live sync pill, panel meta, P1 loop colors |
| `/task done <id>` | CLI + `POST /api/tasks/{id}/done` + UI ✓ button |
| Backlog scripts | `scripts/sync_backlog.py`, `scripts/finalize_live_ui_backlog.py` |
| Tests | `tests/test_qa_v371.py`, `test_qa_v372.py`, `test_live_ui.py`, `test_task_done.py` |

---

## V3.7.3 — Memory Consolidation

**Theme:** Complete V3.6 Phase 4 — memory grows sublinearly with chat volume.

**Shipped:**

| Component | Description |
|-----------|-------------|
| Session merge | `merge_implicit_since_session_summary()` after `create_spark()` |
| Duplicate merge | Cosine ≥ 0.92, same project, compatible types → `status=merged` |
| Stale marking | Low importance, zero access, age > 90d → `status=stale` (never deleted) |
| Daily summary | Opt-in via `MEMORY_DAILY_SUMMARY=1` or `--consolidate daily` |
| Audit table | `memory_consolidation_runs` |
| CLI | `python crowley.py --consolidate [type] [--dry-run]` |
| Debug | `/debug consolidate <type> [dry]` |
| API | `POST /api/consolidate` |
| Script | `scripts/consolidate_memories.py` |
| Retrieval | `access_count` bumped on retrieve; merged/stale excluded |
| Tests | `tests/test_memory_consolidation.py` |

**Version:** `CROWLEY_VERSION = "3.7.3"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.7.3 Memory Consolidation"`

---

## V3.8 — Memory Trail

**Theme:** Truthful memory UI, canonical memory trail, multi-agent hub sync.

**Shipped:**

| Component | Description |
|-----------|-------------|
| Truthful counts | `build_world_dashboard()` reports `memory_active`, `memory_total`, `memory_displayed`, `memory_by_status` |
| Memory API | `GET /api/memory-items` — `q`, `source`, `memory_type`, `status`, `limit`, `offset` |
| Memory tab UI | Search + source/type/status filters; count line `N active / M total · showing K` |
| Canon read path | `list_canon_memory_items()` — active pinned `source='crowley'` rows starting with `Canon:` |
| Prompt injection | `build_prompt()` — "Canonical memory trail:" after knowledge files, before hybrid retrieval |
| Agent sync | `GET /api/agent/sync?agent=cursor\|codex` — top-level `canon` separate from `events_from_other_agents` |
| Canon synthesis | `scripts/synthesize_canon.py` — dry-run default, `--write`, `--show-packet`, six layers, archive-old |
| Codex sync | `scripts/codex_sync.py`, `CODEX.md` — `--before` / `--after` / `--note`, placeholder guards |
| Cursor sync | `scripts/cursor_sync.py` — mirror of Codex guards; `beforeSubmitPrompt` + `sessionStart` hooks |
| Bus automation | `scripts/ensure_crowley_bus.sh` — auto-start on `127.0.0.1:8765` |
| Tests | `tests/test_memory_trail.py` (8 tests); full suite 37 tests |

**Canon precedence:** project_state + knowledge files > canon > hybrid retrieval > recent chat.

**Version:** `CROWLEY_VERSION = "3.8"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.8 Memory Trail"`

Plan: [docs/V3.8_MEMORY_TRAIL.md](./docs/V3.8_MEMORY_TRAIL.md)

---

## V3.8.1 — Agent Parity

**Theme:** Close multi-agent wiring gaps from V3.8 — session-end enforcement, API parity, trustworthy verify.

**Shipped:**

| Component | Description |
|-----------|-------------|
| `agent_activity` in bundles | `build_context_bundle()` and `build_agent_sync_bundle()` expose `last_by_source` timestamps |
| Prompt grounding | `build_prompt()` Agent activity block answers "when did you last hear from Cursor/Codex" |
| Shared sync lib | `scripts/agent_sync_lib.py` — display helpers, `verify_agent_handoff()` via activity feed |
| Handoff verify | `codex_sync.py` / `cursor_sync.py` verify ingest via `agent_activity`, not fuzzy `/api/retrieve` |
| Cursor stop hook | `.cursor/hooks.json` `stop` → `session-stop.sh` → `--session-end` warns if no handoff |
| Session markers | `--session-start` on sessionStart; marker cleared after successful `--after` / `--note` |
| Cursor `--before` parity | Own events, last contact, decisions, loops, retrieved memories (matches Codex richness) |
| Display fix | Event lines no longer prefix with `None \|` when title fields are empty |
| Tests | `tests/test_agent_sync_lib.py`; bundle assertions in `test_memory_trail.py`; **46 tests** total |

**Version:** `CROWLEY_VERSION = "3.8.1"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.8.1 Agent Parity"`

Plan: [docs/V3.8.1_AGENT_PARITY.md](./docs/V3.8.1_AGENT_PARITY.md)

---

## V3.9 — Concurrent Ticketing

**Theme:** One work board for Codex, Cursor, and Crowley — mint, claim, ship, close through the hub.

**Shipped:**

| Component | Description |
|-----------|-------------|
| Schema | `tickets` + `ticket_events` tables |
| Engine | `create_ticket`, `update_ticket`, `complete_ticket`, `claim_ticket`, `build_tickets_summary` |
| HTTP API | `GET/POST/PATCH /api/tickets`, `POST /api/tickets/{id}/done` |
| Sync bundles | `tickets` on `/api/context`, `/api/agent/sync`, `/api/world` |
| Codex CLI | `--create-ticket`, `--create-tickets <file>` |
| Cursor CLI | `--claim-ticket`, `--ticket` on `--after` |
| UI | Intelligence **Tickets** tab with done button |
| Prompt | Tickets block in `build_prompt()` |
| Tests | `tests/test_tickets.py`; **52 tests** total |

**Version:** `CROWLEY_VERSION = "3.9"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9 Concurrent Ticketing"`

Plan: [docs/V3.9_CONCURRENT_TICKETING.md](./docs/V3.9_CONCURRENT_TICKETING.md)

---

## V3.9.1 — Repository & CI

**Theme:** Version-control baseline on GitHub and automated regression on every push to `main`.

**Shipped:**

| Component | Description |
|-----------|-------------|
| Git remote | [github.com/adkinsd2261/crowley](https://github.com/adkinsd2261/crowley) on `main` |
| `.gitignore` | Secrets, DB, venv, processed handoffs excluded |
| Handoffs | `--from-git` file lists in `crowley_handoff.py` / `cursor_sync --after` |
| CI | `.github/workflows/tests.yml` — `unittest discover` on push/PR |
| Docs | Full sweep; `docs/V3.9.1_REPOSITORY_AND_CI.md` |
| Tests | **52 tests** (unchanged count; now gated in CI) |

**Version:** `CROWLEY_VERSION = "3.9.1"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.1 Repository & CI"`

Plan: [docs/V3.9.1_REPOSITORY_AND_CI.md](./docs/V3.9.1_REPOSITORY_AND_CI.md)

---

## V3+ — Planned

- External collectors (Git, calendar) writing to `memory_items`
- Multi-project commands
- `propose_handoff_updates()` tuned extraction prompt

---

## Conventions

1. Bump `CROWLEY_VERSION` and `CROWLEY_RELEASE_LABEL` in `crowley.py` when marking a version shipped.
2. Append a section to this file before marking a version shipped.
3. Keep SQLite schema changes rare; document any migration here.
4. QA sign-off note optional but recommended per minor release.
