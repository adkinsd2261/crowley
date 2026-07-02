# Where We Are — Crowley (Codex / Cursor onboarding)

**As of:** V3.9.4 · V3.9.5/V3.9.6 quality plan approved · **2026-07-02**
**Read this first** on any new Codex or Cursor session after `scripts/codex_sync.py --before` or `scripts/cursor_sync.py --before`.

---

## 1. What Crowley is right now

Crowley is a **local-first AI OS** for Mr. Go: chat UI + SQLite memory + world model + HTTP bus on `127.0.0.1:8765`.

**Pipeline (hardwired):**

```
Mr. Go ──► Crowley (memory, tickets, chat, docs)
              ▲ handoffs only
         Codex (architect) │ Cursor (builder)
```

- **Codex** — plans, decides, mints tickets, posts `architect_handoff` / `note`
- **Cursor** — implements, tests, closes tickets via `--after --ticket ID`
- **Crowley** — answers from filesystem docs + agent activity + tickets + memory (not chat guesses)

---

## 2. Version trail (shipped)

| Version | What landed |
|---------|-------------|
| V3.7 | Context bridge — `/api/context`, ingest, inbox scripts |
| V3.7.2 | Knowledge files in prompts + live UI dashboard |
| V3.7.3 | Memory consolidation (merge, dedupe, stale) |
| V3.8 | Memory Trail — truthful memory counts, canon path, multi-agent sync |
| V3.8.1 | Agent parity — `agent_activity`, stop hook, shared verify |
| V3.9 | Concurrent ticketing — `tickets` table, `/api/tickets`, mint/claim/close |
| **V3.9.1** | **Repository & CI** — GitHub `main`, Actions test gate, doc sweep |
| **V3.9.2** | **Shipped on `main`** — canon synthesis workflow, retrieval explanations, memory hierarchy, hygiene report, test DB isolation |
| **V3.9.3** | **Shipped on `main`** — planning workflow doc, packet template/validation, parent initiatives, draft ticket cancel path |
| **V3.9.4** | **Shipped** — Agent Feed, ticket detail, handoff links, work-board clarity, V4 doc lock (#19–#23) |
| **V3.9.5** | **Planned** — conversation mode classifier, depth controller, co-founder voice, diagnostics separation |
| **V3.9.6** | **Planned** — loading/error/empty states, streaming polish, navigation flow, "what changed" feed |

**Current constants:** `CROWLEY_VERSION = "3.9.4"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9.4 Agent Visibility"`

**Repository:** [github.com/adkinsd2261/crowley](https://github.com/adkinsd2261/crowley)

---

## 3. Memory trail (where truth lives)

See [MEMORY_HIERARCHY.md](./MEMORY_HIERARCHY.md) for the full reference. Summary:

| Layer | Source | Use for |
|-------|--------|---------|
| Filesystem | `VERSIONS.md`, `PROJECT_STATE.md`, `docs/WHERE_WE_ARE.md`, phase docs | Version, architecture, what shipped |
| Tickets | `/api/tickets`, sync bundle `tickets` | What work is open, assigned, blocked |
| Agent activity | `last_by_source` on `/api/agent/sync` | When Codex/Cursor last posted |
| project_state | SQLite `project_state` | Phase, focus, risk, next_action (may lag docs slightly) |
| Canon | Pinned `Canon:` rows in `memory_items` | Always-on continuity — **does not override** filesystem, tickets, or project state |
| Handoffs | `.crowley/processed/*`, `memory_items` events | Session-by-session builder/architect log |
| Hybrid retrieval | `/api/retrieve` | Supporting context only — lowest authority |

**Authoritative order for facts:** filesystem → tickets → agent_activity → project_state → **canon** → retrieval → chat.

### Work board surfaces (tickets vs tasks vs open loops)

| Surface | Role | Agent board? |
|---------|------|--------------|
| **Tickets** | Authoritative work board — Codex mints; Cursor claims and ships | **Yes** |
| **Tasks** | Lightweight legacy todos (due dates, quick hygiene) | No |
| **Open loops** | Unresolved project questions, risks, and follow-ups | No |

Cursor and Codex assigned work lives on **tickets**, not tasks or open loops. See [MEMORY_HIERARCHY.md](./MEMORY_HIERARCHY.md).

**Prompt injection order:** filesystem → live DB state → agent activity → tickets → **canon** → hybrid retrieval → chat.

Operator workflow: [V3.9.2_CANON_SYNTHESIS_WORKFLOW.md](./V3.9.2_CANON_SYNTHESIS_WORKFLOW.md)

---

## 4. Agent rituals (required)

Planning workflow (roles, when to mint tickets, Cursor-ready definition): [V3.9.3_PLANNING_WORKFLOW.md](./V3.9.3_PLANNING_WORKFLOW.md).

### Codex (new session)

```bash
./venv/bin/python3 scripts/codex_sync.py --before
```

Read: **Your role**, last contact, Cursor events, tickets, open loops.

After planning:

```bash
./venv/bin/python3 scripts/codex_sync.py --create-ticket \
  --title "…" --assignee cursor --priority 1 --description "…" --acceptance "…"

./venv/bin/python3 scripts/codex_sync.py --after \
  --summary "…" --next-action "…" --decision "…"
```

### Cursor (new session)

Hooks run `--before` automatically. After shipping:

```bash
./venv/bin/python3 scripts/cursor_sync.py --after --ticket <ID> \
  --summary "…" --next-action "…" --qa-result "tests OK"
```

---

## 5. Where we are (product)

**Done and stable:**

- Web UI + SSE chat, markdown replies, intelligence drawer (**Tickets**, Tasks, Loops, Decisions, **Agent Feed**, Memory)
- Tickets tab: grouped initiatives, row-click **detail view** (`GET /api/tickets/{id}`), done button
- Multi-agent hub: `codex_sync.py`, `cursor_sync.py`, `agent_sync_lib.py` (mint, claim, close, **cancel**)
- Cursor hooks: sessionStart, beforeSubmitPrompt, stop (handoff nudge)
- **90 unit tests** — isolated temp DB per test (`tests/db_helpers.py`); local run + **GitHub Actions** on push/PR to `main`
- Personality: Crowley = the running system; Jarvis-shaped; filesystem-first answers
- Git — [github.com/adkinsd2261/crowley](https://github.com/adkinsd2261/crowley); `cursor_sync --after` and `crowley_handoff --from-git` populate file lists

**Known gaps (honest):**

- Canon synthesis is manual-first — re-run via [V3.9.2_CANON_SYNTHESIS_WORKFLOW.md](./V3.9.2_CANON_SYNTHESIS_WORKFLOW.md)
- Legacy `tasks` + `open_loops` coexist with `tickets` — see [MEMORY_HIERARCHY.md](./MEMORY_HIERARCHY.md) § Work board surfaces
- Some `open_loops` may be stale until backlog hygiene runs

---

## 6. Where we are heading

Pre-V4 ladder complete. The active pre-V4 quality plan adds two small releases before connectivity: [PRE_V4_QUALITY_PLAN.md](./PRE_V4_QUALITY_PLAN.md).

| Initiative | Owner | Notes |
|------------|-------|-------|
| **V3.9.2 Memory Clarity** | Shipped on `main` | Tickets `#9–#13` |
| **V3.9.3 Planning Workflow** | Shipped on `main` | Tickets `#14–#18` |
| **V3.9.4 Agent Visibility** | Shipped on `main` | Tickets `#19–#23` |
| **V3.9.5 Conversation + Model Behavior** | Open | Tickets `#25–#30` |
| **V3.9.6 Workspace Polish** | Open | Tickets `#31–#36` |
| **Pre-V4 QA Hygiene** | Open | Ticket `#37` — state lock-in + stale open-loop cleanup |

**V4 connectivity** (git collector, multi-project commands) waits until V3.9.5 and V3.9.6 ship and docs are locked.

---

## 7. Key paths

| Path | Role |
|------|------|
| `crowley.py` | Engine |
| `app.py` | HTTP transport |
| `.github/workflows/tests.yml` | CI regression gate |
| `docs/PRE_V4_QUALITY_PLAN.md` | Active V3.9.5/V3.9.6 quality plan |
| `docs/V3.9.5_CONVERSATION_MODEL_BEHAVIOR.md` | V3.9.5 release spec |
| `docs/V3.9.6_WORKSPACE_POLISH.md` | V3.9.6 release spec |
| `docs/V3.9.4_AGENT_VISIBILITY.md` | V3.9.4 spec + V4 readiness gate |
| `docs/V3.9.1_REPOSITORY_AND_CI.md` | V3.9.1 spec |
| `docs/V3.9.3_PLANNING_WORKFLOW.md` | Planning packets, mint gate, cancel vs edit |
| `docs/PRE_V4_RELEASE_PLAN.md` | Approved pre-V4 release ladder |
| `docs/V3.9_CONCURRENT_TICKETING.md` | V3.9 spec |
| `docs/V3.8_MEMORY_TRAIL.md` | Memory trail spec |
| `CODEX.md` / `CURSOR.md` | Agent rituals |
| `.cursor/rules/crowley-memory.mdc` | Cursor rule |
| `scripts/lock_in_state.py` | State hygiene (loops, canon seed, tickets) |
| `tickets/` | JSON templates for `--create-tickets` |

---

## 8. Quick health check

```bash
./scripts/ensure_crowley_bus.sh
curl -s http://127.0.0.1:8765/api/health | python3 -m json.tool
curl -s "http://127.0.0.1:8765/api/agent/sync?agent=codex&limit=5" | python3 -m json.tool
./venv/bin/python3 -m unittest discover -s tests -q
```

---

*This file is loaded into Crowley prompts and should stay current after each major ship.*
