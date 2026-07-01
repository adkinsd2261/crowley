# Crowley — Roadmap

**Purpose:** Guide future development from documented current state.  
**As of:** V3.9.1 shipped · **2026-07-01**  
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
                            V3.9.1 Repository & CI  ◄── YOU ARE HERE
```

**Shipped through V3.9.1:** … concurrent ticketing, **GitHub repo + Actions CI**.

**Active initiative:** None — see [TICKETS.md](./TICKETS.md). Next: canon synthesis, agent feed tab, or V4 connectivity.

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
| Automated CI test suite | Regression risk grows | Medium | ✅ Shipped — GitHub Actions |
| First canon synthesis | Populate `canon` rows for prompts/sync | Low | Script ready; manual run |
| Agent feed UI tab | Surface cross-agent handoffs in browser | Medium | API exists; tab deferred |
| `propose_handoff_updates()` | Handoff-tuned extraction prompt | Low | Open |
| Sparks UI → `memory_items` | Legacy panel | Low–Medium | ✅ Memory tab |
| `/task done <id>` | Task hygiene | Low | ✅ Shipped |
| `git init` baseline | Meaningful handoff file lists | Low | ✅ Shipped — [adkinsd2261/crowley](https://github.com/adkinsd2261/crowley) |

---

## 8. Mid-term (V4 themes) **(inference)**

### 8.1 External collectors (opt-in)

Git/calendar → `memory_items`, not world model directly.

### 8.2 Multi-project support

`/project list`, `/project switch <slug>` — schema ready; extraction must never auto-switch.

### 8.3 MCP / deeper IDE integration

Deferred from V3.7; HTTP bus + Cursor rule is the current integration surface.

---

## 9. Explicit non-goals (carry forward)

| Non-goal | Notes |
|----------|-------|
| Cloud-hosted Crowley | Local-first identity |
| Auto-delete / auto-archive | Safety rule from V3.2 |
| Auto project switching | Safety rule |
| Auth on localhost API | Trust model for single user |
| Full agent tool loop (shell execution) | Out of scope |
| WebSocket live push | Polling sufficient for local single-user |

**Shipped (no longer non-goals):** Web UI (V3.5), vector/hybrid retrieval (V3.6), external read/write API (V3.7), live UI dashboard (V3.7.2), memory consolidation (V3.7.3), Memory Trail + multi-agent sync (V3.8).

---

## 10. Technical debt register

| Debt | Impact | Suggested fix |
|------|--------|---------------|
| Monolithic `crowley.py` (~4000 LOC) | Navigation at scale | Module split when second contributor |
| No migration version table | Schema changes risky | `schema_version` + incremental migrations |
| Legacy `/api/sparks` | Confusing vs `memory_items` | Deprecate or redirect to summaries |
| Silent extraction failures | Stale world model | Audit log or `/debug extract-log` |
| `chromadb` unused | Install bloat | Remove from requirements |
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
| **V3.9.2+** | Polish | Agent feed UI tab, canon automation |
| **V4.0** | Connectivity | Git collector, multi-project commands |

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
- [V3.9.1_REPOSITORY_AND_CI.md](./V3.9.1_REPOSITORY_AND_CI.md)
- [V3.9_CONCURRENT_TICKETING.md](./V3.9_CONCURRENT_TICKETING.md)
- [V3.8_MEMORY_TRAIL.md](./V3.8_MEMORY_TRAIL.md)
- [VERSIONS.md](../VERSIONS.md)
