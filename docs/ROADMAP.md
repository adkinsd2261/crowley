# Crowley — Roadmap

**Purpose:** Guide future development from documented current state.  
**As of:** V3.9.11 shipped · V3.9.12 next · V4 direction pivot · **2026-07-03**
**Sources:** `VERSIONS.md`, code, [TICKETS.md](./TICKETS.md).  
Inferences marked **(inference)**.

---

## 1. Roadmap principles

1. **Conversation first** — features should enhance natural chat, not require commands.
2. **Conservative automation** — when uncertain, skip; never destructive auto-actions.
3. **Inspectable** — debug/dry-run paths for every autonomous subsystem.
4. **Minimal diffs** — extend the monolith carefully; no rewrite without cause.
5. **Local-first** — data stays in SQLite unless user opts into external integrations.
6. **Engine owns logic** — `app.py` is transport only; external tools use HTTP bus.
7. **Portable continuity** — Crowley is the persistent context layer that follows D across reasoning surfaces.
8. **Sparks over transcripts** — raw logs are receipts; sparks are future-useful memory units.

---

## 2. Current position

```
V1 ──► V2 Memory ──► V2.5 UX ──► V2.6 Brain
                                      │
                                      ▼
                            V3.0 World Model (manual)
                                      │
                                      ▼
                            V3.1 Diagnostics
                                      │
                                      ▼
                            V3.2 Extraction
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
            V3.5 Chat UI                      V3.6 Memory Backend
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      ▼
                            V3.7 Context Bridge
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
            V3.7.3 Consolidation              V3.8 Memory Trail
            (merge, dedupe, stale)            (canon, multi-agent)
                                      │
                                      ▼
                            V3.8.1 Agent Parity
                                      │
                                      ▼
                            V3.9 Concurrent Ticketing
                                      │
                                      ▼
                            V3.9.1 Repository & CI
                                      │
                                      ▼
                    Pre-V4 ladder (V3.9.2–V3.9.4) ✅
                                      │
                                      ▼
                    Pre-V4 quality V3.9.5 ✅
                                      │
                                      ▼
                    Pre-V4 quality V3.9.6 ✅
                                      │
                                      ▼
                    V3.9.7 Experience & Reliability ✅
                                      │
                                      ▼
                    V3.9.8 Runtime Hardening ✅
                                      │
                                      ▼
                    V3.9.9 Context That Feeds ✅
                              │
                              ▼
                    V3.9.10 Task-Frame Context ✅
                              │
                              ▼
                    V3.9.11 Live Wire ✅
                           │
                           ▼
                    V3.9.12 Portable Context Terminal ◄── YOU ARE HERE
                              │
                              ▼
                    V4.0 Spark Lanes
```

**Shipped through V3.9.11:** … task-frame context (#64–#69); live wire — pulses, compose ticker, brain switcher (#70–#75).

**Active initiative:** V3.9.12 Portable Context Terminal (#76–#80). V4.0 Spark Lanes planned after V3.9.12 — see [PRE_V4_FUTURE_RELEASE_LADDER.md](./PRE_V4_FUTURE_RELEASE_LADDER.md).

---

## 3. Shipped — V3.7 Context Bridge (complete)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 1 | `GET /api/context` | ✅ Done |
| 2 | `GET /api/retrieve` | ✅ Done |
| 3 | `POST /api/ingest` | ✅ Done |
| 4 | `.crowley/inbox/` + `scripts/ingest_inbox.py` | ✅ Done |
| 5 | `scripts/crowley_handoff.py` | ✅ Done |
| 6 | `GET /api/bus/health`, `/debug bus`, version `3.7.2` | ✅ Done |

Plan: [V3.7_CONTEXT_BRIDGE.md](./V3.7_CONTEXT_BRIDGE.md)

---

## 4. Shipped — Live UI sync (V3.7.2, complete)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 1/3 | Dashboard API + 5s polling + phase progress bar | ✅ Done |
| 2/3 | Intelligence tab badges, live pill, panel meta | ✅ Done |
| 3/3 | `/task done` CLI + API + UI, backlog cleanup | ✅ Done |

---

## 5. Shipped — V3.6 Phase 4 consolidation (V3.7.3, complete)

| Job | Deliverable | Status |
|-----|-------------|--------|
| Session merge | Implicit trim events → `merged` on session summary | ✅ Done |
| Duplicate merge | Cosine ≥ 0.92 dedupe | ✅ Done |
| Stale marking | 90d low-importance never-accessed | ✅ Done |
| Daily summary | Opt-in `MEMORY_DAILY_SUMMARY=1` | ✅ Done |
| Ops | CLI, API, audit table, tests | ✅ Done |

Plan: [V3.6_MEMORY_BACKEND.md](./V3.6_MEMORY_BACKEND.md) Phase 4

---

## 6. Shipped — V3.8 Memory Trail (complete)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| A | Truthful memory counts + `/api/memory-items` filters | ✅ Done |
| A | Memory tab search/source/type/status UI | ✅ Done |
| B | Canon read path in prompt + sync bundles | ✅ Done |
| B | `GET /api/agent/sync` with top-level `canon` | ✅ Done |
| C | `scripts/synthesize_canon.py` (manual `--write`) | ✅ Done |
| Multi-agent | `codex_sync.py`, `cursor_sync.py`, bus auto-start, Cursor hooks | ✅ Done |

Plan: [V3.8_MEMORY_TRAIL.md](./V3.8_MEMORY_TRAIL.md)

---

## 6b. Shipped — V3.8.1 Agent Parity (complete)

| Deliverable | Status |
|-------------|--------|
| `agent_activity` on `/api/context` and `/api/agent/sync` | ✅ Done |
| Agent activity in `build_prompt()` | ✅ Done |
| `scripts/agent_sync_lib.py` shared verify + display | ✅ Done |
| Cursor `stop` hook + session markers | ✅ Done |
| Cursor `--before` parity with Codex | ✅ Done |

Plan: [V3.8.1_AGENT_PARITY.md](./V3.8.1_AGENT_PARITY.md)

---

## 6c. Shipped — V3.9 Concurrent Ticketing (complete)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| A | `tickets` + `ticket_events` schema; engine; `/api/tickets` | ✅ Done |
| B | Codex `--create-ticket(s)`; Cursor `--claim-ticket` / `--ticket` | ✅ Done |
| C | UI Tickets tab + dashboard counts | ✅ Done |
| D | `build_prompt()` ticket block; docs; ship 3.9 | ✅ Done |

Plan: [V3.9_CONCURRENT_TICKETING.md](./V3.9_CONCURRENT_TICKETING.md)

---

## 6d. Shipped — V3.9.1 Repository & CI (complete)

| Deliverable | Status |
|-------------|--------|
| Git remote on `main` | ✅ [adkinsd2261/crowley](https://github.com/adkinsd2261/crowley) |
| `.gitignore` + handoff `--from-git` | ✅ Done |
| `.github/workflows/tests.yml` | ✅ Done |
| Documentation sweep | ✅ Done |

Plan: [V3.9.1_REPOSITORY_AND_CI.md](./V3.9.1_REPOSITORY_AND_CI.md)

---

## 7. Near-term backlog

| Item | Rationale | Complexity | Status |
|------|-----------|------------|--------|
| Automated CI test suite | Regression risk grows | Medium | ✅ Shipped — GitHub Actions (**157** tests; core deps) |
| V3.9.2 Memory Clarity | Make memory natural but auditable | Medium | ✅ Shipped on `main` (#9–#13) |
| V3.9.3 Planning Workflow | Convert Codex planning into Cursor-ready ticket packets | Medium | ✅ Shipped on `main` (#14–#18) |
| V3.9.4 Agent Visibility | Make agent/ticket activity visible before V4 | Medium | ✅ Shipped on `main` (#19–#23) |
| V3.9.5 Conversation + Model Behavior | Make Crowley pleasant and mode-aware for daily project work | Medium | ✅ Shipped on `main` (#25–#30) |
| V3.9.6 Workspace Polish | Make the browser workspace livable before V4 | Medium | ✅ Shipped on `main` (#31–#36) |
| Pre-V4 QA hygiene | Repair stale project_state/open_loops before deeper work | Low | ✅ Shipped on `main` (#37) |
| V3.9.7 Workspace Experience & Reliability | UI catches up to backend depth; boring boot | Medium | ✅ Shipped on `main` (#40–#49) |
| V3.9.8 Runtime Hardening | No fragile startup — test mode, runtime health | Medium | Local (#50–#55) — not on `origin/main` |
| V3.9.9 Context That Feeds | Quality gate, slim sync, handoff intelligence, UI | Medium | **Shipped locally** (#56–#63) |
| V3.9.10 Task-Frame Context | Task frame before retrieval for agents | Medium | **Shipped locally** (#64–#69) |
| V3.9.11 Live Wire | Compose activity wire + brain switcher | Medium | **Shipped locally** (#70–#75) |
| V3.9.12 Portable Context Terminal | Local/manual Crowley packet + structured writeback | Medium | Minted #76–#80 · **next** |
| V4.0 Spark Lanes | Memory lanes, trust states, lane-aware retrieval | High | Planned after V3.9.12 |
| External collectors | Optional future inputs into lanes | High | Deferred after V4 memory architecture |
| First canon synthesis | Populate `canon` rows for prompts/sync | Low | ✅ Workflow + first run (V3.9.2) |
| Agent feed UI tab | Surface cross-agent handoffs in browser | Medium | ✅ Shipped (#19) |
| Ticket detail + handoff links | Live work board usability | Medium | ✅ Shipped (#20–#21) |
| Tasks vs tickets vs loops | Clarify Intelligence drawer roles | Low | ✅ Shipped (#22) |
| `propose_handoff_updates()` | Handoff-tuned extraction prompt | Low | Open |
| Sparks UI → `memory_items` | Legacy panel | Low–Medium | ✅ Memory tab |
| `/task done <id>` | Task hygiene | Low | ✅ Shipped |
| `git init` baseline | Meaningful handoff file lists | Low | ✅ Shipped — [adkinsd2261/crowley](https://github.com/adkinsd2261/crowley) |

---

## 8. Mid-term (V4 themes) **(inference)**

### 8.1 portable context terminal (V3.9.12)

Export a compact Crowley packet into ChatGPT or another AI/model surface and import structured writeback out. Store the session recap as an episodic receipt and the useful residue as candidate sparks.

### 8.2 Spark lanes (V4.0)

Primary lanes: learning, work, relationships, money, health, operating_style. Every spark gets one lane, optional domain/tags, why_keep, worth reason, confidence, sensitivity, and trust state.

### 8.3 External collectors (opt-in)

Git/calendar/filesystem collectors become later inputs into spark lanes, not the V4 core.

### 8.4 Multi-project support

`/project list`, `/project switch <slug>` — schema ready; extraction must never auto-switch.

### 8.5 MCP / deeper IDE integration

Deferred from V3.7; HTTP bus + Cursor rule is the current integration surface.

---

## 9. Explicit non-goals (carry forward)

| Non-goal | Notes |
|----------|-------|
| Cloud-hosted Crowley | Local-first identity |
| Auto-delete / auto-archive | Safety rule from V3.2 |
| Auto project switching | Safety rule |
| Auth on localhost API | Trust model for single user |
| Live terminal automation | V3.9.12 is local/manual packet + writeback |
| Full agent tool loop (shell execution) | Out of scope |
| WebSocket live push | Polling sufficient for local single-user |

**Shipped (no longer non-goals):** Web UI (V3.5), vector/hybrid retrieval (V3.6), external read/write API (V3.7), live UI dashboard (V3.7.2), memory consolidation (V3.7.3), Memory Trail + multi-agent sync (V3.8).

---

## 10. Technical debt register

| Debt | Impact | Suggested fix |
|------|--------|---------------|
| Monolithic `crowley.py` (~5600 LOC) | Navigation at scale | Partial — `diagnostics.py` + `tickets.py` extracted (V3.9.7) |
| No migration version table | Schema changes risky | `schema_version` + incremental migrations |
| Legacy `/api/sparks` | Confusing vs `memory_items` | Deprecate or redirect to summaries |
| Silent extraction failures | Stale world model | Audit log or `/debug extract-log` |
| `chromadb` unused | Install bloat | Optional via `requirements-ml.txt` only |
| `tasks.project` free text | Inconsistent with `projects` | Normalize or document as alias |

---

## 11. Suggested release sequencing

| Release | Theme | Key deliverables |
|---------|-------|------------------|
| **V3.7.3** | Consolidation | ✅ V3.6 Phase 4 shipped |
| **V3.8** | Memory Trail | ✅ Truthful memory UI, canon path, multi-agent sync |
| **V3.8.1** | Agent Parity | ✅ Activity feed, stop hook, shared verify |
| **V3.9** | Concurrent Ticketing | ✅ Unified ticket board; Codex mints, Cursor fills |
| **V3.9.1** | Repository & CI | ✅ GitHub remote, Actions test gate, doc sweep |
| **V3.9.2** | Memory Clarity | Canon workflow, retrieval explanations, hierarchy ([MEMORY_HIERARCHY.md](./MEMORY_HIERARCHY.md)), hygiene, test isolation |
| **V3.9.3** | Planning Workflow | Planning packets, ticket validation, parent initiatives, cleanup |
| **V3.9.4** | Agent Visibility | ✅ Agent feed, ticket detail/history, work-board clarity, V4 doc lock |
| **V3.9.5** | Conversation + Model Behavior | ✅ Mode classifier, depth, co-founder voice, diagnostics separation, chat UX |
| **V3.9.6** | Workspace Polish | ✅ Panel states, streaming, navigation, what-changed feed, livability, docs lock |
| **V3.9.7** | Experience & Reliability | ✅ UI polish, embed fallback, CI slim deps, diagnostics/tickets modules, metrics, preflight |
| **V3.9.8** | Runtime Hardening | ✅ test mode, model probe, runtime health, sqlite-vec fallback |
| V3.9.9 | Context That Feeds | Shipped locally (#56–#63) |
| V3.9.10 | Task-Frame Context | Shipped locally (#64–#69) |
| V3.9.11 | Live Wire | Shipped locally (#70–#75) |
| V3.9.12 | Portable Context Terminal | Minted #76–#80 · next |
| V3.9.12 | Portable Context Terminal | Minted #76–#80; packet-in/writeback-out |
| **V4.0** | Spark Lanes | Memory lanes, trust states, lane-aware retrieval |

---

## 12. Documentation maintenance

When shipping a version:

1. Bump `CROWLEY_VERSION` and `CROWLEY_RELEASE_LABEL` in `crowley.py`
2. Append section to `VERSIONS.md`
3. Update `docs/PROJECT_STATE.md`, `docs/TICKETS.md`, this roadmap
4. Add ADR to `docs/DECISION_LOG.md` for significant choices
5. Update phase docs (`V3.5`, `V3.6`, `V3.7`, `V3.8`) as needed

---

## 13. Related documents

- [PROJECT_STATE.md](./PROJECT_STATE.md)
- [TICKETS.md](./TICKETS.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [V3.7_CONTEXT_BRIDGE.md](./V3.7_CONTEXT_BRIDGE.md)
- [V3.9.4_AGENT_VISIBILITY.md](./V3.9.4_AGENT_VISIBILITY.md)
- [V3.9.1_REPOSITORY_AND_CI.md](./V3.9.1_REPOSITORY_AND_CI.md)
- [V3.9_CONCURRENT_TICKETING.md](./V3.9_CONCURRENT_TICKETING.md)
- [V3.8_MEMORY_TRAIL.md](./V3.8_MEMORY_TRAIL.md)
- [MEMORY_HIERARCHY.md](./MEMORY_HIERARCHY.md)
- [V3.9.3_PLANNING_WORKFLOW.md](./V3.9.3_PLANNING_WORKFLOW.md)
- [PRE_V4_RELEASE_PLAN.md](./PRE_V4_RELEASE_PLAN.md)
- [PRE_V4_FUTURE_RELEASE_LADDER.md](./PRE_V4_FUTURE_RELEASE_LADDER.md)
- [VERSIONS.md](../VERSIONS.md)
