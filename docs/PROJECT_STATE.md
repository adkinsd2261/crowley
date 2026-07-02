# Crowley — Project State

**As of:** V3.9.4 · V3.9.5/V3.9.6 quality plan approved
**Planning:** Active — [PRE_V4_QUALITY_PLAN.md](./PRE_V4_QUALITY_PLAN.md) · shipped ladder — [PRE_V4_RELEASE_PLAN.md](./PRE_V4_RELEASE_PLAN.md)
**Last doc sync:** 2026-07-02 (V3.9.5/V3.9.6 planning packet)
**Onboarding:** [WHERE_WE_ARE.md](./WHERE_WE_ARE.md) — read first in new Codex/Cursor sessions  
**Source:** `crowley.py`, `app.py`, `VERSIONS.md`, `requirements.txt`  
Inferences marked **(inference)**.

---

## 1. What Crowley is today

Crowley is a **local-first assistant** for a single developer/user, combining:

- Streaming LLM chat (OpenAI primary in `auto` mode, Ollama fallback)
- SQLite-backed message log, memories, typed `memory_items`, tasks
- Structured **world model** for the active software project
- Read-only **diagnostics** briefings
- **Autonomous extraction** that quietly updates the world model from conversational signals
- **Hybrid memory retrieval** (semantic + keyword + recency + importance)
- **Web workspace UI** (V3.5+) — live dashboard polling, phase progress, intelligence panels
- **Context bridge** (V3.7) — HTTP API + inbox scripts for external tools (Cursor, Codex)
- **Knowledge files context** (V3.7.2) — query-scored markdown excerpts in prompts
- **Memory consolidation** (V3.7.3) — merge, dedupe, stale marking, optional daily summary
- **Memory Trail** (V3.8) — truthful memory counts, canon read path, manual canon synthesis
- **Multi-agent hub** (V3.8) — Codex/Cursor sync scripts, `/api/agent/sync`, Crowley-only messaging
- **Agent parity** (V3.8.1) — `agent_activity` in all bundles, stop hook, shared verify lib
- **V3.9 shipped** — concurrent ticketing (`tickets` table, `/api/tickets`, agent mint/claim/close)
- **Pre-V4 ladder shipped** — V3.9.2 memory clarity, V3.9.3 planning workflow, V3.9.4 agent visibility + doc lock (#9–#23)
- **V3.9.2 shipped on `main`** — retrieval explanations, memory hierarchy, hygiene API, test DB isolation
- **V3.9.3 shipped on `main`** — planning workflow, packet validation, parent tickets, cancel path
- **V3.9.4 shipped on `main`** — Agent Feed, ticket detail, handoff↔ticket links, work-board clarity, V4 onboarding lock
- **V3.9.5 planned** — inferred conversation modes, response depth, co-founder voice, diagnostics separation, model-behavior tests
- **V3.9.6 planned** — workspace loading/error/empty states, streaming polish, navigation flow, recent changes feed, final docs lock
- **Cursor memory sync rule** — `.cursor/rules/crowley-memory.mdc` + sessionStart / beforeSubmitPrompt / stop hooks

It is **not** a multi-user service and **not** a full agent framework with tool use.

---

## 2. File inventory

| File | Status | Purpose |
|------|--------|---------|
| `crowley.py` | **Active** | Engine — CLI + all business logic |
| `app.py` | **Active** | Web transport (FastAPI, SSE, context bridge routes) |
| `static/` | **Active** | Workspace UI (HTML, CSS, JS) |
| `scripts/ingest_inbox.py` | **Active** | Ingest `.crowley/inbox/` handoffs |
| `scripts/crowley_handoff.py` | **Active** | Generate handoff templates |
| `scripts/codex_sync.py` | **Active** | Codex before/after/note sync (V3.8, verify V3.8.1) |
| `scripts/cursor_sync.py` | **Active** | Cursor before/after/note/session hooks (V3.8.1) |
| `scripts/agent_sync_lib.py` | **Active** | Shared sync + ticket API helpers (V3.8.1–V3.9) |
| `scripts/ensure_crowley_bus.sh` | **Active** | Auto-start bus on 8765 (V3.8) |
| `scripts/lock_in_state.py` | **Active** | State lock-in: canon seed, loop hygiene, tickets (V3.9+) |
| `scripts/sync_backlog.py` | **Active** | Dedupe tasks, seed open loops |
| `scripts/finalize_live_ui_backlog.py` | **Active** | Close completed Live UI loops |
| `scripts/consolidate_memories.py` | **Active** | Memory consolidation jobs (V3.7.3) |
| `scripts/synthesize_canon.py` | **Active** | Manual canon synthesis (V3.9.2) |
| `CODEX.md` | **Active** | Codex multi-agent ritual |
| `.cursor/rules/crowley-memory.mdc` | **Active** | Cursor pre/post task memory sync |
| `.cursor/hooks.json` | **Active** | sessionStart + beforeSubmitPrompt + stop hooks |
| `.crowley/inbox/` | **Active** | Handoff drop folder |
| `.crowley/processed/` | **Active** | Post-ingest archive |
| `tests/` | **Active** | QA unit tests (**90**; isolated DB; gated by GitHub Actions on `main`) |
| `.github/workflows/tests.yml` | **Active** | CI — `unittest discover` on push/PR |
| `requirements.txt` | **Active** | Dependencies |
| `VERSIONS.md` | **Active** | Release log |
| `docs/TICKETS.md` | **Active** | Human-readable backlog mirror |
| `crowley.db` | **Runtime** | Created by `setup_db()` |
| `docs/` | **Active** | Engineering documentation |

---

## 3. Version history (shipped)

| Version | Label | Summary |
|---------|-------|---------|
| V3.5 | Chat UI | FastAPI workspace, SSE chat, intelligence drawer |
| V3.6 | Memory backend | `memory_items`, embeddings, hybrid retrieval |
| V3.6.0 | Chat continuity | Last 8 messages in `build_prompt()` |
| V3.7 | Context bridge | `/api/context`, `/api/retrieve`, `/api/ingest`, inbox scripts |
| V3.7.1 | QA patch | Greeting fix, UI gap, truth validation, response depth |
| V3.7.2 | Knowledge + live UI | Knowledge files in prompt; live dashboard, task done, phase bar |
| V3.7.3 | Memory consolidation | V3.6 Phase 4 — merge, dedupe, stale, daily summary |
| V3.8 | Memory Trail | Truthful memory UI/API, canon path, multi-agent sync |
| V3.8.1 | Agent Parity | `agent_activity` bundles, stop hook, shared verify |
| V3.9 | Concurrent Ticketing | Unified ticket board; mint/claim/close via sync |
| V3.9.1 | Repository & CI | GitHub remote, Actions test gate, doc sweep |
| V3.9.4 | Agent Visibility | Pre-V4 ladder complete; Agent Feed, ticket detail, handoff links, V4 doc lock |
| V3.9.5 | Conversation + Model Behavior | Planned; mode classifier, depth controller, co-founder voice |
| V3.9.6 | Workspace Polish | Planned; UI states, streaming, navigation, recent changes, docs lock |

Full history: [VERSIONS.md](../VERSIONS.md).

---

## 4. Feature matrix

| Capability | Status | Mechanism |
|------------|--------|-----------|
| Read context API | ✅ V3.7 | `GET /api/context` (+ `knowledge_files`, `canon`, `agent_activity`) |
| Agent sync API | ✅ V3.8 | `GET /api/agent/sync?agent=cursor\|codex` (+ `agent_activity`) |
| Memory search API | ✅ V3.9.2 | `GET /api/retrieve` — includes per-result `explanation` (source, type, score, status, pinned, is_canon, provenance) |
| Memory list API | ✅ V3.8 | `GET /api/memory-items` (filters + pagination) |
| Handoff ingest API | ✅ V3.7 | `POST /api/ingest` |
| Bus health API | ✅ V3.7 | `GET /api/bus/health` |
| Inbox file ingest | ✅ V3.7 | `scripts/ingest_inbox.py` |
| Handoff templates | ✅ V3.7 | `scripts/crowley_handoff.py` |
| Codex sync | ✅ V3.8 | `scripts/codex_sync.py`, `CODEX.md` |
| Cursor sync | ✅ V3.8.1 | `cursor_sync.py`, hooks (start/prompt/stop), `agent_sync_lib` |
| Concurrent tickets | ✅ V3.9 | `tickets` table, `/api/tickets`, mint/claim/close/cancel via sync |
| Ticket detail API | ✅ V3.9.4 | `GET /api/tickets/{id}` + event history; UI row-click detail |
| Agent Feed UI | ✅ V3.9.4 | Intelligence drawer tab from `agent_activity.recent` |
| Planning workflow | ✅ V3.9.3 | Packet template, validation, parent_id, cancel path |
| Memory hygiene | ✅ V3.9.2 | `GET /api/memory/hygiene`, `crowley.py --hygiene` |
| Test DB isolation | ✅ V3.9.2 | `tests/db_helpers.py` — tests do not write `crowley.db` |
| Git + CI | ✅ V3.9.1 | [adkinsd2261/crowley](https://github.com/adkinsd2261/crowley); `.github/workflows/tests.yml` |
| Canon read path | ✅ V3.8 | `list_canon_memory_items()`, prompt + sync bundles |
| Canon synthesis | ✅ V3.9.2 | `scripts/synthesize_canon.py` — manual workflow; first run complete — see `docs/V3.9.2_CANON_SYNTHESIS_WORKFLOW.md` |
| Hybrid memory | ✅ V3.6 | `retrieve_memories()` |
| Knowledge files | ✅ V3.7.2 | `load_knowledge_files_context()` |
| Live UI dashboard | ✅ V3.7.2 | `GET /api/world` → `build_world_dashboard()` |
| Memory tab filters | ✅ V3.8 | Search, source, type, status in `static/app.js` |
| Memory consolidation | ✅ V3.7.3 | `consolidate_memories()`, session/dedupe/stale/daily |
| Task completion | ✅ V3.7.2 | `/task done`, `POST /api/tasks/{id}/done`, UI ✓ |
| Web workspace UI | ✅ V3.5 | `app.py` + `static/` |
| MCP / auth / cloud | ❌ | Out of scope |

---

## 5. Web API routes (`app.py`)

| Method | Path | Role |
|--------|------|------|
| GET | `/api/health` | Version, brain, DB |
| GET | `/api/context` | World + memory + knowledge files + canon bundle |
| GET | `/api/agent/sync` | Per-agent sync bundle (V3.8) |
| GET | `/api/retrieve` | Hybrid memory search |
| POST | `/api/ingest` | External handoff |
| GET | `/api/bus/health` | Context bridge health |
| GET | `/api/world` | Live dashboard (state, panels, truthful memory counts) |
| GET | `/api/tasks` | Open tasks |
| POST | `/api/tasks/{id}/done` | Mark task done |
| GET | `/api/loops` | Open loops |
| GET | `/api/decisions` | Recent decisions |
| GET | `/api/tickets` | Ticket list (open default) |
| GET | `/api/tickets/{id}` | Ticket detail + events |
| POST | `/api/tickets` | Create ticket |
| PATCH | `/api/tickets/{id}` | Update ticket / link handoff memory |
| POST | `/api/tickets/{id}/done` | Mark done |
| POST | `/api/tickets/{id}/cancel` | Cancel with comment (Codex cleanup) |
| GET | `/api/memory-items` | Filtered `memory_items` for UI (V3.8) |
| GET | `/api/memory/hygiene` | Memory hygiene report (V3.9.2) |
| GET | `/api/events/recent` | Recent agent memory events |
| POST | `/api/consolidate` | Memory consolidation jobs |
| GET | `/api/sparks` | Legacy sparks (`memories` table) |
| GET | `/api/messages` | Chat history |
| POST | `/api/chat` | SSE chat |
| GET | `/api/diagnostics` | SSE diagnostics (read-only) |

Bind: `127.0.0.1:8765`.

---

## 6. Known limitations

| Item | Detail |
|------|--------|
| Canon re-synthesis | Manual — follow `docs/V3.9.2_CANON_SYNTHESIS_WORKFLOW.md` after major releases |
| Git baseline | [github.com/adkinsd2261/crowley](https://github.com/adkinsd2261/crowley) on `main`; handoffs use `--from-git` |
| Legacy sparks API | `GET /api/sparks` reads legacy `memories`; UI uses `/api/memory-items` |
| `metadata` on ingest | Accepted, not persisted |
| Daily summary | Opt-in only (`MEMORY_DAILY_SUMMARY=1`) |
| CI pipeline | ✅ V3.9.1 | GitHub Actions — `.github/workflows/tests.yml` on push/PR to `main` (**90** tests) |
| UI poll interval | 5s — not instant; handoff ingest still needed for memory content |
| Ingest inference | Filename-based; markdown `Source:` header not parsed |
| Tasks vs tickets clarification | See MEMORY_HIERARCHY work board surfaces + Intelligence panel notes |

---

## 7. Run commands

```bash
# Web UI + context bridge API
./venv/bin/python3 app.py
# or
./scripts/ensure_crowley_bus.sh

# CLI
./venv/bin/python3 crowley.py

# Tests
./venv/bin/python3 -m unittest discover -s tests -v

# Context bridge
curl "http://127.0.0.1:8765/api/context?q=current+project&limit=8"
curl "http://127.0.0.1:8765/api/world"
curl "http://127.0.0.1:8765/api/agent/sync?agent=cursor&limit=5"
curl "http://127.0.0.1:8765/api/memory-items?status=active&limit=10"
curl http://127.0.0.1:8765/api/bus/health

# Multi-agent sync
./venv/bin/python3 scripts/cursor_sync.py --before
./venv/bin/python3 scripts/codex_sync.py --before

# Handoff workflow
./venv/bin/python3 scripts/crowley_handoff.py --source cursor --type builder_handoff --from-git
./venv/bin/python3 scripts/ingest_inbox.py

# Canon synthesis (see docs/V3.9.2_CANON_SYNTHESIS_WORKFLOW.md)
./venv/bin/python3 scripts/synthesize_canon.py --show-packet
./venv/bin/python3 scripts/synthesize_canon.py              # dry-run
./venv/bin/python3 scripts/synthesize_canon.py --write      # after validation passes
```

---

## 8. Related documents

- [V3.9.4_AGENT_VISIBILITY.md](./V3.9.4_AGENT_VISIBILITY.md)
- [PRE_V4_QUALITY_PLAN.md](./PRE_V4_QUALITY_PLAN.md)
- [V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md](./V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md)
- [V3.9.6_WORKSPACE_POLISH.md](./V3.9.6_WORKSPACE_POLISH.md)
- [V3.9.1_REPOSITORY_AND_CI.md](./V3.9.1_REPOSITORY_AND_CI.md)
- [V3.9_CONCURRENT_TICKETING.md](./V3.9_CONCURRENT_TICKETING.md)
- [V3.8.1_AGENT_PARITY.md](./V3.8.1_AGENT_PARITY.md)
- [V3.8_MEMORY_TRAIL.md](./V3.8_MEMORY_TRAIL.md)
- [V3.7_CONTEXT_BRIDGE.md](./V3.7_CONTEXT_BRIDGE.md)
- [V3.6_MEMORY_BACKEND.md](./V3.6_MEMORY_BACKEND.md)
- [V3.5_CHAT_UI.md](./V3.5_CHAT_UI.md)
- [TICKETS.md](./TICKETS.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [VERSIONS.md](../VERSIONS.md)
