# Crowley Version Log

Single source of truth for release history. Update this file at the end of every version.

**Current:** V3.9.20 (`Crowley V3.9.20 Ticket Memory Linkage`)
**Next planned:** V4.0 Cognitive Memory (mid-lock — final bump at T24 #226)

**North star:** Crowley is the persistent context layer that follows D across reasoning surfaces. Models and UIs are swappable terminals; sparks are the memory unit.

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
| V3.9.4  | shipped  | 2026-07-02 | Pre-V4 ladder complete — memory clarity, planning workflow, agent visibility, doc lock |
| V3.9.5  | shipped  | 2026-07-02 | Conversation + Model Behavior — mode classifier, depth, co-founder voice, diagnostics separation, chat UX |
| V3.9.6  | shipped  | 2026-07-02 | Workspace Polish — panel states, streaming, navigation, what-changed feed, livability, docs lock |
| V3.9.7  | shipped  | 2026-07-02 | Workspace Experience & Reliability — UI polish, embed fallback, CI slim deps, module extraction, metrics |
| V3.9.8  | shipped  | 2026-07-02 | Runtime Hardening — test mode, model probe, runtime health, sqlite-vec fallback, fragile-startup suite |
| V3.9.9  | shipped  | 2026-07-02 | Context That Feeds — quality gate, inclusion reasons, slim sync, handoff upgrade, feedback loop, UI/hygiene |
| V3.9.10 | shipped  | 2026-07-02 | Task-Frame Context — task frame API, ticket-narrative retrieval, sync/UI/prompt brief |
| V3.9.11 | shipped  | 2026-07-03 | Live Wire — activity pulses, compose wire UI, brain switcher, agent feed fixes (#70–#75) |
| V3.9.12 | shipped  | 2026-07-03 | Portable Context Terminal — packet export, writeback parse/ingest, CLI (#76–#80); #81 codex_sync `--known-issue` parity |
| V3.9.13 | shipped  | 2026-07-03 | Secure ChatGPT Actions API — bearer `/api/actions/*`, bridge scripts, Custom GPT setup |
| V3.9.15 | shipped  | 2026-07-05 | GPT Toolbelt — hybrid gateway, tool registry, Codex-parity writes, GitHub read proxy (#94–#100) |
| V3.9.16 | shipped  | 2026-07-06 | Workflow Enforcement — boot gate, truth hierarchy, core tools, QA pipeline (#101–#111) |
| V3.9.17 | shipped  | 2026-07-06 | Trust Control and Clarity — attribution, audit, tiers, conflicts, agent behavior (#112–#130) |
| V3.9.19 | shipped  | 2026-07-06 | Memory Quality — ingest dedup, lifecycle cleanup, validation runtime wiring (#152–#157, #162–#166) |
| V3.9.20 | shipped  | 2026-07-08 | Ticket lineage + memory linkage — full arc query, bidirectional index, audit/backfill (#264, #225) |
| V3.9.18 | shipped  | 2026-07-06 | Agent Retrieval Enforcement — handoff tickets, gating, integrity patch (#131–#151) |
| V3.9.14 | shipped  | 2026-07-05 | Durable ChatGPT Bridge — LaunchAgent, API-only tunnel, verify tooling (#82–#86) |
| V4.0    | in progress | 2026-07-07 | Cognitive Memory mid-lock T1–T13; Part 1 ASE/GitHub + bridge E2E; bump at T24 |

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

## V3.9.4 — Agent Visibility / Pre-V4 Readiness

**Shipped:** 2026-07-02 · Tickets `#19–#23`

| Area | Detail |
|------|--------|
| Agent Feed | Intelligence drawer tab from `agent_activity.recent` |
| Ticket detail | Row click → `GET /api/tickets/{id}` + event timeline |
| Handoff links | `handoff_linked` events; `linked_handoff` on detail API |
| Work-board clarity | Panel role notes; tickets vs tasks vs open loops in docs/UI |
| Doc lock | Version bump to `3.9.4`; onboarding docs locked for V4 readiness |
| Tests | **90 tests** (GitHub Actions on `main`) |

**Version:** `CROWLEY_VERSION = "3.9.4"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.4 Agent Visibility"`

Plan: [docs/V3.9.4_AGENT_VISIBILITY.md](./docs/V3.9.4_AGENT_VISIBILITY.md)

---

## V3.9.5 — Conversation + Model Behavior

**Shipped:** 2026-07-02 · Tickets `#25–#30`

| Area | Detail |
|------|--------|
| Mode classifier | Deterministic inferred modes in `build_prompt()` with answer shapes |
| Depth controller | `brief` / `standard` / `deep` from phrasing and mode |
| Personality | Co-founder voice; order-neutral mode/depth honor line |
| Diagnostics separation | `_diagnostics_system_prompt()` — factual, no chat persona |
| Regression fixtures | `tests/fixtures/v3_9_5_model_behavior.json` |
| Chat UX sweep | Empty/slash/model-error copy; streaming finalize/abort helpers |
| Tests | **140 tests** (GitHub Actions on `main`) |

**Version:** `CROWLEY_VERSION = "3.9.5"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.5 Conversation + Model Behavior"`

Plan: [docs/V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md](./docs/V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md)

---

## V3.9.6 — Workspace Polish

**Shipped:** 2026-07-02 · Tickets `#31–#36`

| Area | Detail |
|------|--------|
| Panel states | Loading/error/empty across chat, panels, ticket detail, Memory |
| Streaming | RAF-batched updates, stick-to-bottom scroll, writing indicator, safe Refresh |
| Navigation | Session tab/ticket persistence; fingerprint-gated re-renders; stable ticket detail |
| What changed | `build_recent_changes_feed()` + Changes tab; agent-feed fallback for stale bus |
| Livability | Overflow/wrap, drawer heights, mobile-ish tab layout |
| Tests | **147 tests** (GitHub Actions on `main`) |

**Version:** `CROWLEY_VERSION = "3.9.6"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.6 Workspace Polish"`

Plan: [docs/V3.9.6_WORKSPACE_POLISH.md](./docs/V3.9.6_WORKSPACE_POLISH.md)

---

## V3.9.16 — Workflow Enforcement

**Version:** `CROWLEY_VERSION = "3.9.16"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.16 Workflow Enforcement"`

Plan: [docs/V3.9.16_WORKFLOW_ENFORCEMENT.md](./docs/V3.9.16_WORKFLOW_ENFORCEMENT.md) · Tickets `#101–#111`

| Area | Detail |
|------|--------|
| Boot gate | Actions `428 boot_required` until `agent.sync`; `X-Crowley-Session` tracking |
| Truth hierarchy | Prompt order: tickets → agent activity → project state; activity beats memory for what changed |
| Core tools | `tier: core\|secondary` in `/api/actions/catalog` |
| Canonical loop | `sync → read → decide → write → state_update` in workflow payload |
| QA pipeline | Builder handoffs: Context Basis, Build Complete, Approval; `--confidence` flags |
| Noise gate | `note.ingest` rejects low-signal content |
| E2E | `scripts/validate_workflow_e2e.py` |
| Codex templates | `tickets/codex_grade_ticket.template.json` |
| Tests | **389 tests** with `CROWLEY_TEST_MODE=1` |

Also: `github_read.py` certifi SSL fix for macOS Python 3.14.

---

## V3.9.17 — Trust Control and Clarity

**Version:** `CROWLEY_VERSION = "3.9.17"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.17 Trust Control and Clarity"`

Plan: [docs/V3.9.17_TRUST_CONTROL_CLARITY.md](./docs/V3.9.17_TRUST_CONTROL_CLARITY.md) · Tickets `#112–#130`

| Area | Detail |
|------|--------|
| Attribution | `agent_identity.py` — agent_id, source, signature on writes |
| Permissions | read_only / writer / architect; Actions write gate |
| Audit | `write_audit.py` — append-only log; `inspect.audit_list`, `audit.rollback` |
| Memory tiers | ephemeral / working / canonical; promotion, decay, retrieval boost |
| Conflicts | `conflict_engine.py` — detect + deterministic resolve with trace |
| Agent behavior | `agent_behavior.py` — sync policy, retrieval policy, chaining, validation |
| Observability | `inspect.retrieval_observability` per-session tool log |
| QA | `crowley_context_validation` in QA pipeline schema |
| Tests | **424 tests** with `CROWLEY_TEST_MODE=1` |

---

## V3.9.19 — Memory Quality

**Version:** `CROWLEY_VERSION = "3.9.19"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.19 Memory Quality"`

Plan: [docs/V3.9.19_MEMORY_QUALITY.md](./docs/V3.9.19_MEMORY_QUALITY.md) · Tickets `#152–#157` · follow-up `#162–#166`

| Area | Detail |
|------|--------|
| Ingest dedup | `memory_quality.find_ingest_duplicate()` — constraint + semantic-type similarity |
| Retrieval strength | `assess_retrieval_strength()` on `/api/retrieve`; rebalanced hybrid weights |
| Lifecycle | `run_minimal_lifecycle_cleanup()` + `memory.lifecycle_cleanup` tool + metrics |
| Backfill | `scripts/backfill_constraint_deduplication.py` |
| Validation | Observability-backed checklist (#162); runtime wiring on Actions + `/api/agent/sync` (#166) |
| Tests | **471 tests** with `CROWLEY_TEST_MODE=1` |

---

## V3.9.20 — Ticket Lineage & Memory Linkage

**Version:** `CROWLEY_VERSION = "3.9.20"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.20 Ticket Memory Linkage"`

Plan: [docs/V3.9.20_TICKET_MEMORY_LINKAGE.md](./docs/V3.9.20_TICKET_MEMORY_LINKAGE.md) · Tickets `#264`, `#225`

| Area | Detail |
|------|--------|
| Ticket lineage | `sort=oldest`, `tickets.lineage` in `agent.sync`, `agent.deep_sync scope=history`, audit script |
| Memory linkage | `memory_ticket_linkage.py`, `linked_ticket_ids_json`, backfill + audit scripts |
| Ticket detail | `ticket.get` / REST `include_memories` — grouped linked memories |
| Retrieval | Query-ticket boost; persisted memory→ticket links |
| Handoff bridge | Next Action `#N` excluded from false ticket close |
| Tests | `test_ticket_lineage`, `test_memory_ticket_linkage` |

### Post-3.9.19 integrity hardening (folded into 3.9.20 release)

Tickets `#167`, `#171–#193` (ChatGPT-minted; #185–#188/#191–#192 closed as duplicates of #171–#184).

| Area | Detail |
|------|--------|
| Ingest parity | `ensure_handoff_ticket_link()` + `require_handoff_memory_parity()` — every persisted handoff gets exactly one ticket (#167/#177/#179) |
| Observability persistence | `observability_store.py` — `observability_logs` + `session_state` tables; wired into `record_tool_call` (#171/#173) |
| Dispatch enforcement | `run_enforcement_gates` blocks on error-severity invariants; `dispatch_blocked` metric on block (#172/#185/#190) |
| Planner | Refinement retry + fallback retrieval plan (#174/#175) |
| Claim validation | `claim_validation.py` — claim_status metadata, contested-peer marking (#176) |
| Link hardening | `linked_memory_id` immutable on tickets; metadata-first `resolve_work_ticket_link` (#178/#182) |
| Invariants | `observability_truth` DB comparison in qa/sync contexts (#189); fail-safe blocks dispatch when invariant system errors (#193) |
| Parity metrics | `handoff_ticket_bridge.parity_metrics()` counters (#184) |
| Tests | **492 tests** with `CROWLEY_TEST_MODE=1` |

---

## V3.9.18 — Agent Retrieval Enforcement

**Version:** `CROWLEY_VERSION = "3.9.18"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.18 Agent Retrieval Enforcement"`

Plan: [docs/V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md](./docs/V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md) · Tickets `#131–#135` · patch `#142–#151`

| Area | Detail |
|------|--------|
| Handoff bridge | `handoff_ticket_bridge.py` — idempotent handoff → done ticket; parity reconcile |
| Pre-response gate | `428 context_not_ready` with `retry_path` |
| Domain triggers | `428 domain_retrieval_required` with `required_tools` |
| Proactive chaining | Complex-query heuristics require multi-step retrieval |
| Observability | Structured log: `tool_called`, `reason_for_call`, `triggering_rule` |
| Integrity patch | `system_integrity.py` — invariants, gates, planner, guardrails (#142–#150) |
| Parity reconcile | `scripts/reconcile_handoff_ticket_parity.py` — unique `linked_memory_id` (#151) |
| Backfill | `scripts/backfill_handoff_tickets.py` |
| Tests | **453 tests** with `CROWLEY_TEST_MODE=1` |

---

## V3.9.13 — Secure ChatGPT Actions API

**Version:** `CROWLEY_VERSION = "3.9.13"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.13 Secure ChatGPT Actions API"`

Plan: [docs/V3.9.13_SECURE_CHATGPT_ACTIONS_API.md](./docs/V3.9.13_SECURE_CHATGPT_ACTIONS_API.md) · [docs/CHATGPT_SETUP.md](./docs/CHATGPT_SETUP.md)

- Narrow bearer-authenticated `/api/actions/*` for Custom GPT Actions
- `CROWLEY_ACTION_KEY` env gate — 503 when unset, 401 on bad bearer
- OpenAPI: `openapi-chatgpt.json` (template); `openapi-chatgpt.deployed.json` at bridge start
- Reuses portable context packet + writeback parse/ingest; does not expose full internal API
- Localhost bind unchanged; `scripts/start_chatgpt_bridge.sh` — cloudflared quick/named or ngrok, HTTPS verify
- `cloudflared/config.yml.example`, `docs/CHATGPT_SETUP.md` for Custom GPT operator path
- **Patch (2026-07-03):** OpenAPI schema fix — `ContextBundle` explicit properties + `LooseObject` for ChatGPT Actions validator; bridge `--named`/`--ngrok` mode parse fix
- **338 tests** with `CROWLEY_TEST_MODE=1`

---

## V3.9.12 — Portable Context Terminal

**Version:** `CROWLEY_VERSION = "3.9.12"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.12 Portable Context Terminal"`

Plan: [docs/V3.9.12_PORTABLE_CONTEXT_TERMINAL.md](./docs/V3.9.12_PORTABLE_CONTEXT_TERMINAL.md)

Post-lock cleanup: ticket **#81** — `codex_sync.py --after` accepts repeatable `--known-issue` (parity with `cursor_sync.py`). **320 tests** with `CROWLEY_TEST_MODE=1`.

---

## V3.9.11 — Live Wire

**Version:** `CROWLEY_VERSION = "3.9.11"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.11 Live Wire"`

Plan: [docs/V3.9.11_LIVE_WIRE.md](./docs/V3.9.11_LIVE_WIRE.md)

---

## V3.9.10 — Task-Frame Context

**Version:** `CROWLEY_VERSION = "3.9.10"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.10 Task-Frame Context"`

Plan: [docs/V3.9.10_TASK_FRAME_CONTEXT.md](./docs/V3.9.10_TASK_FRAME_CONTEXT.md)

---

## V3.9.9 — Context That Feeds

**Version:** `CROWLEY_VERSION = "3.9.9"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.9 Context That Feeds"`

Plan: [docs/V3.9.9_CONTEXT_THAT_FEEDS.md](./docs/V3.9.9_CONTEXT_THAT_FEEDS.md)

---

## V4.0 Cognitive Memory — mid-lock (batch 1)

**Version constant:** still `3.9.19` until T24 (#226)

Lock: [docs/V4.0_COGNITIVE_MEMORY_MID_LOCK.md](./docs/V4.0_COGNITIVE_MEMORY_MID_LOCK.md) — T1–T13 (#203–#215). **674 tests** at mid-lock.

---

## V4.0 Part 1 patch — ASE + GitHub

Lock: [docs/V4.0_PART1_PATCH_AGENT_GITHUB.md](./docs/V4.0_PART1_PATCH_AGENT_GITHUB.md) — agent.sync ASE (#229–#231), GitHub read envelope. **686 tests** at patch lock.

---

## V4.0 Part 1 — bridge & ChatGPT E2E

Lock: [docs/V4.0_PART1_BRIDGE_E2E_LOCK.md](./docs/V4.0_PART1_BRIDGE_E2E_LOCK.md) — sqlite-vec per-connection, Actions auto-promote, retrieve hardening, bridge verify. **705 tests** collected at lock.

---

## Pre-V4 ladder (shipped on `main`, 2026-07-02)

The three-release pre-V4 arc shipped under version constant `3.9.4` after ticket `#23` doc lock.

| Theme | Tickets | Highlights | Tests (cumulative) |
|-------|---------|------------|-------------------|
| V3.9.2 Memory Clarity | #9–#13 | Canon workflow, retrieval `explanation`, hierarchy docs/UI, hygiene API, test DB isolation | 78+ |
| V3.9.3 Planning Workflow | #14–#18 | Planning packet template, validation, `parent_id`, `cancel_ticket` | 81+ |
| V3.9.4 Agent Visibility | #19–#23 | Agent Feed tab, ticket detail UI, handoff links, work-board clarity, V4 doc lock | **90** |

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
