# Where We Are — Crowley (Codex / Cursor onboarding)

**As of:** V3.9.18 · V4 next · **2026-07-06**
**Read this first** on any new Codex or Cursor session after `scripts/codex_sync.py --before` or `scripts/cursor_sync.py --before`.

**Git note:** V3.9.18 Agent Retrieval Enforcement shipped (#131–#135, integrity patch #142–#151). Restart bus after version bumps so `/api/health` matches constants.

---

## 1. What Crowley is right now

Crowley is a **local-first AI OS** for D: chat UI + SQLite memory + world model + HTTP bus on `127.0.0.1:8765`.

**Pipeline (hardwired):**

```
D ──► Crowley (memory, tickets, chat, docs)
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
| **V3.9.5** | **Shipped** — mode classifier, depth controller, co-founder voice, diagnostics separation, regression fixtures, chat UX sweep (#25–#30) |
| **V3.9.6** | **Shipped** — panel states, streaming polish, navigation flow, what-changed feed, livability pass (#31–#36) |
| **V3.9.7** | **Shipped** — drawer/chat polish, embed fallback, CI slim deps, diagnostics/tickets modules, metrics (#40–#49) |
| **V3.9.8** | **Shipped on `main`** — test mode, model probe, runtime health, sqlite-vec fallback, fragile-startup suite (#50–#55) |
| **V3.9.9** | **Shipped on `main`** — Context That Feeds: quality gate, inclusion reasons, slim sync, handoff upgrade, feedback loop, UI/hygiene (#56–#63) |
| **V3.9.10** | **Shipped on `main`** — Task-Frame Context: task frame API, ticket-narrative retrieval, sync/UI/prompt brief (#64–#69) |
| **V3.9.11** | **Shipped on `main`** — Live Wire: pulses, compose wire UI, brain switcher (#70–#75) |
| **V3.9.12** | **Shipped on `main`** — Portable Context Terminal: packet export, writeback parse/ingest, CLI (#76–#80); #81 codex_sync `--known-issue` parity |
| **V3.9.16** | **Shipped** — Workflow Enforcement: boot gate, truth hierarchy, core tools, QA pipeline (#101–#111) |
| **V3.9.17** | **Shipped** — Trust Control and Clarity: attribution, audit, tiers, conflicts, agent behavior (#112–#130) |
| **V3.9.18** | **Shipped** — Agent Retrieval Enforcement: handoff tickets, gating, integrity patch (#131–#151) |
| **V3.9.15** | **Shipped** — GPT Toolbelt: hybrid gateway, tool registry, inspect/planning/GitHub read (#94–#100) |
| **V3.9.14** | **Shipped** — Durable ChatGPT Bridge: LaunchAgent, API-only tunnel, verify tooling (#82–#86) |
| **V3.9.13** | **Shipped on `main`** — Secure ChatGPT Actions API: bearer `/api/actions/*`, bridge scripts, `CHATGPT_SETUP.md` |
| **V4.0** | **Planned** — Spark Lanes; memory lanes, trust states, lane-aware retrieval |

**Current constants (local code):** `CROWLEY_VERSION = "3.9.18"` (`Crowley V3.9.18 Agent Retrieval Enforcement`)

**Repository:** [github.com/adkinsd2261/crowley](https://github.com/adkinsd2261/crowley)

**Direction pivot:** Crowley is the persistent context layer that follows D across reasoning surfaces. The browser UI is one cockpit; ChatGPT, Claude, Codex, Cursor, local models, and future models are terminals/reasoning surfaces. V3.9.12 proves the portable context terminal loop; V3.9.13 adds bearer Actions for Custom GPT; V4.0 gives sparks memory lanes.

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

- Web UI + SSE chat, markdown replies, intelligence drawer (**Tickets**, Tasks, Loops, Decisions, **Changes**, **Agent Feed**, Memory)
- Tickets tab: grouped initiatives, row-click **detail view** (`GET /api/tickets/{id}`), done button
- Multi-agent hub: `codex_sync.py`, `cursor_sync.py`, `agent_sync_lib.py` (mint, claim, close, **cancel**)
- Cursor hooks: sessionStart, beforeSubmitPrompt, stop (handoff nudge)
- Portable context terminal — `GET /api/portable/packet`, writeback parse/ingest, CLI scripts
- ChatGPT Actions API — bearer `/api/actions/*` when `CROWLEY_ACTION_KEY` is set; **boot gate** requires `agent.sync` on fresh sessions ([CHATGPT_SETUP.md](./CHATGPT_SETUP.md))
- **389 unit tests** locally (`CROWLEY_TEST_MODE=1`); CI on `main` runs the same gate
- Personality: Crowley = the running system; co-founder voice; inferred mode/depth; filesystem-first answers
- Git — [github.com/adkinsd2261/crowley](https://github.com/adkinsd2261/crowley); `cursor_sync --after` and `crowley_handoff --from-git` populate file lists

**Known gaps (honest):**

- Canon synthesis is manual-first — re-run via [V3.9.2_CANON_SYNTHESIS_WORKFLOW.md](./V3.9.2_CANON_SYNTHESIS_WORKFLOW.md)
- Legacy `tasks` + `open_loops` coexist with `tickets` — see [MEMORY_HIERARCHY.md](./MEMORY_HIERARCHY.md) § Work board surfaces
- Some `open_loops` may be stale until backlog hygiene runs

---

## 6. Where we are heading

Pre-V4 quality arc complete through **V3.9.13 on `main`**. See [PRE_V4_FUTURE_RELEASE_LADDER.md](./PRE_V4_FUTURE_RELEASE_LADDER.md).

| Initiative | Owner | Notes |
|------------|-------|-------|
| **V3.9.8 Runtime Hardening** | Cursor | **Shipped on `main`** · #50–#55 |
| **V3.9.9 Context That Feeds** | Cursor | **Shipped on `main`** · #56–#63 complete |
| **V3.9.10 Task-Frame Context** | Cursor | **Shipped on `main`** · #64–#69 complete |
| **V3.9.11 Live Wire** | Cursor | **Shipped on `main`** · #70–#75 complete |
| **V3.9.12 Portable Context Terminal** | Cursor | **Shipped on `main`** · #76–#80 · packet-in/writeback-out |
| **V3.9.13 ChatGPT Actions API** | Cursor | **Shipped on `main`** · bearer `/api/actions/*` + bridge tooling |
| **#81 Sync parity** | Cursor | **Shipped on `main`** · codex_sync `--known-issue` |
| **V3.9.16 Workflow Enforcement** | Cursor | **Shipped** · #101–#111 · boot gate, QA pipeline handoffs |
| **V3.9.17 Trust Control and Clarity** | Cursor | **Shipped** · #112–#130 · attribution, audit, tiers, agent behavior |
| **V3.9.18 Agent Retrieval Enforcement** | Cursor | **Shipped** · #131–#135 · gating, domain triggers, handoff tickets |
| **V4 Spark Lanes** | Codex plans | **Next** · sparks + lanes + trust |

**Resume workflow:** Plan or mint **V4.0 Spark Lanes** when D directs.

---

## 7. Key paths

| Path | Role |
|------|------|
| `crowley.py` | Engine (core) |
| `diagnostics.py` | Diagnostics domain |
| `tickets.py` | Ticketing domain |
| `app.py` | HTTP transport |
| `.github/workflows/tests.yml` | CI regression gate (core deps) |
| `scripts/preflight.py` | Release preflight |
| `workflow.py` | Workflow enforcement module (V3.9.16+) |
| `agent_identity.py` | Write attribution + permissions (V3.9.17) |
| `write_audit.py` | Append-only write audit + rollback (V3.9.17) |
| `memory_tiers.py` | Memory tiers, promotion, decay (V3.9.17) |
| `conflict_engine.py` | Conflict detection + resolution (V3.9.17) |
| `agent_behavior.py` | Agent retrieval policy, chaining, validation (V3.9.17) |
| `handoff_ticket_bridge.py` | Handoff → ticket persistence bridge (V3.9.18) |
| `docs/V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md` | V3.9.18 release spec |
| `docs/V3.9.16_WORKFLOW_ENFORCEMENT.md` | V3.9.16 release spec |
| `scripts/validate_workflow_e2e.py` | E2E workflow validation |
| `docs/V3.9.13_SECURE_CHATGPT_ACTIONS_API.md` | V3.9.13 release spec |
| `docs/CHATGPT_ACTIONS_API.md` | V3.9.13 operator guide |
| `docs/CHATGPT_SETUP.md` | Custom GPT + tunnel bridge setup |
| `scripts/start_chatgpt_bridge.sh` | Start bus + tunnel + verify Actions API |
| `openapi-chatgpt.json` | Custom GPT OpenAPI template |
| `chatgpt_actions.py` | Actions router + bearer auth |
| `docs/V3.9.12_PORTABLE_CONTEXT_TERMINAL.md` | V3.9.12 release spec |
| `scripts/export_portable_packet.py` | Export paste-ready context packet |
| `scripts/import_portable_writeback.py` | Import terminal writeback |
| `docs/V3.9.9_CONTEXT_THAT_FEEDS.md` | V3.9.9 release spec |
| `docs/V3.9.8_RUNTIME_HARDENING.md` | V3.9.8 release spec |
| `docs/V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md` | V3.9.7 release spec |
| `docs/PRE_V4_QUALITY_PLAN.md` | Completed V3.9.5/V3.9.6 quality plan |
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
