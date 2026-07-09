# Crowley — Roadmap

**Purpose:** Guide future development from documented current state.
**As of:** V4.1.0 shipped · V4.2–V4.5 cognitive completion ladder minted · **2026-07-09**
**Sources:** `VERSIONS.md`, [TICKETS.md](./TICKETS.md), [V4_COGNITIVE_SPEC_GAP_ANALYSIS.md](./V4_COGNITIVE_SPEC_GAP_ANALYSIS.md).
Inferences marked **(inference)**. Post-V5 device themes are **directional** — release numbers not assigned yet.

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
9. **Complete the backbone before devices** — V4.2–V4.5 closes the cognitive loop (input → retrieval → chat context → truth → security) before V5 automation and physical surfaces.
10. **Devices consume sparks, not reinvent memory** — speaker, glasses, and agents read the same spark graph Crowley already maintains.

---

## 2. Current position

```
… V3.9.x ladder (shipped) …
                              │
                              ▼
                    V4.0 Cognitive Memory ✅ (#203–#226)
                              │
                              ▼
                    V4.1 Architecture + MCP Readiness ✅ (#316–#325)
                              │
                              ▼
              V4.2–V4.5 Cognitive Completion ◄── YOU ARE HERE
              (input → retrieval → chat wire → truth → security)
              Tickets #352–#374 · builder-owned · one ladder at a time
                              │
                              ▼
                    V5 — automation, MCP transport, voice (planned, not minted)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    Physical speaker (Echo-class)    Brilliant Labs AI Frames
    spark-aware voice surface        wearable Crowley terminal
    (horizon — no release # yet)     (horizon — after voice + speaker)
```

**Shipped:** V4.0 cognitive memory (sparks, graph, context API, safeguards). V4.1 facade extraction + shared tool contract + security baseline.

**Active:** V4.2–V4.5 completes the ChatGPT cognitive-memory spec — closes the gap where chat still uses legacy `memory_items` instead of ranked sparks. Planning: [V4_COGNITIVE_SPEC_GAP_ANALYSIS.md](./V4_COGNITIVE_SPEC_GAP_ANALYSIS.md). Tickets: [TICKETS.md](./TICKETS.md).

**Not yet specified as versioned releases:** physical speaker hardware, frame integration, and intermediate milestones between V5 and those devices. The journey is intentionally multi-step; this roadmap names themes, not dates.

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

| Item | Rationale | Status |
|------|-----------|--------|
| **V4.2 Input Intelligence** | Intent gate, schema extensions, chunking, promotion (#352–#357) | Minted · open |
| **V4.3 Retrieval + Query** | Query interpreter, auto lane, cap 8–15 (#358–#362) | Minted · after V4.2 lock |
| **V4.4 Context + Chat Wire** | Token budget, structured sections, `build_prompt` (#363–#367) | Minted · after V4.3 lock |
| **V4.5 Truth + Security Lock** | Arbitration, correction API, encryption, acceptance suite (#369–#374) | Minted · after V4.4 lock |
| V5 planning packet | Automation, MCP transport, voice — themes only until V4.5 locks | **Not minted** |

Historical V3.9.x and V4.0/V4.1 items are shipped; see [VERSIONS.md](../VERSIONS.md) and [TICKETS.md](./TICKETS.md).

---

## 8. Mid-term themes

### 8.1 V4.2–V4.5 — cognitive completion (active)

Finish the operational blueprint: messy input → structured sparks → bounded retrieval → live chat context → truth/correction → encryption. V4.1 prepared MCP **metadata**; V4.2–V4.5 completes the **memory backbone** that every future surface will read.

Packets: `tickets/v4.2_input_intelligence.json` through `v4.5_truth_security_lock.json`.
Lock target: [V4_ACCEPTANCE_TEST_MATRIX.md](./V4_ACCEPTANCE_TEST_MATRIX.md) (six acceptance tests).

### 8.2 V5 — automation, MCP, and voice **(planned, not minted)**

After V4.5 cognitive completion lock, V5 is the first release that intentionally adds **execution and new transports**:

| Theme | Intent |
|-------|--------|
| **Automation** | Event triggers, proactive workflows, pattern-driven actions — the spec's V5 out-of-scope items |
| **MCP tooling** | Ship MCP transport on top of `crowley_tools.py` (contract already exists from V4.1) |
| **Voice** | TTS/STT integration, voice-friendly context packing, local voice session hooks |

V5 assumes sparks are authoritative in chat and APIs. Automation must respect existing permission tiers and never bypass T18–T20 security gates.

**Not in V5 by default:** custom hardware, wearables, or field devices — those are separate horizons below.

### 8.3 Physical speaker — spark-aware voice terminal **(horizon)**

Direction: an Echo-class **local speaker** that is a Crowley terminal, not a generic assistant.

- Voice in → cognitive ingest (same pipeline as chat)
- Voice out → answers grounded in **located sparks** (lane, confidence, lineage), not opaque RAG
- User can ask “what do you know about X?” and Crowley resolves to specific sparks in the system
- Depends on: solid V4 cognitive loop, V5 voice stack, reliable on-device or low-latency STT/TTS

Release number and hardware spec **not assigned** — likely multiple milestones (prototype firmware, wake word, bus bridge, spark UX on device).

### 8.4 Brilliant Labs AI Frames — wearable Crowley **(horizon)**

Direction: integrate Crowley into **Brilliant Labs AI Frames** as a wearable context surface once voice and a working physical speaker path exist.

- Glasses as capture + glanceable recall, not the system of record
- Crowley remains hub: frames consume `cognitive.context` / voice APIs; sparks stay in SQLite
- Chat and ingest on frames feed the same receipt → spark pipeline

**Sequencing (inference):** V4 cognitive complete → V5 voice/MCP/automation → speaker prototype proves spark locate + voice UX → frames integration. Exact ordering may shift; frames are not the next release after V5.

### 8.5 External collectors (opt-in)

Git/calendar/filesystem collectors become inputs into spark lanes — likely post-V5 or parallel to automation work.

### 8.6 Multi-project support

`/project list`, `/project switch <slug>` — schema ready; extraction must never auto-switch.

---

## 9. Explicit non-goals (carry forward)

| Non-goal | Notes |
|----------|-------|
| Cloud-hosted Crowley | Local-first identity |
| Auto-delete / auto-archive | Safety rule from V3.2 |
| Auto project switching | Safety rule |
| Auth on localhost API | Trust model for single user; `/api/actions/*` uses bearer when exposed via tunnel |
| Live terminal automation | V3.9.12 packet + writeback; V3.9.13 Actions API for Custom GPT |
| MCP server transport | Deferred to **V5**; tool contract prepared in V4.1 |
| Voice / TTS / STT | Deferred to **V5**; frames and speaker are later horizons |
| Proactive automation / event triggers | Deferred to **V5** |
| Custom speaker hardware | Horizon — not a versioned release yet |
| Brilliant Labs frames integration | Horizon — after voice + speaker path **(inference)** |
| Full agent tool loop (unrestricted shell execution) | Out of scope — automation in V5 stays gated |
| WebSocket live push | Polling sufficient for local single-user |

**Shipped (no longer non-goals):** Web UI (V3.5), vector/hybrid retrieval (V3.6), external read/write API (V3.7), live UI dashboard (V3.7.2), memory consolidation (V3.7.3), Memory Trail + multi-agent sync (V3.8).

---

## 10. Technical debt register

| Debt | Impact | Suggested fix |
|------|--------|---------------|
| Monolithic `crowley.py` (~6.1k LOC facade) | Navigation at scale | V4.1 extracted domains; new logic stays out of facade |
| No migration version table | Schema changes risky | `schema_version` + incremental migrations |
| Legacy `/api/sparks` | Confusing vs `memory_items` | Deprecate or redirect to summaries |
| Silent extraction failures | Stale world model | Audit log or `/debug extract-log` |
| `chromadb` unused | Install bloat | Optional via `requirements-ml.txt` only |
| `tasks.project` free text | Inconsistent with `projects` | Normalize or document as alias |

---

## 11. Release sequencing

| Release | Theme | Status |
|---------|-------|--------|
| V3.9.x – V3.9.20 | Agent sync, Actions API, memory quality, ticket linkage | ✅ Shipped |
| **V4.0** | Cognitive Memory — sparks, graph, context API | ✅ Shipped (#203–#226) |
| **V4.1** | Architecture facade, security baseline, MCP-ready tool contract | ✅ Shipped (#316–#325) |
| **V4.2** | Input intelligence — intent, schema, chunking | Minted (#352–#357) |
| **V4.3** | Retrieval + query control | Minted (#358–#362) |
| **V4.4** | Context orchestration + chat wire | Minted (#363–#367) |
| **V4.5** | Truth, feedback, encryption, cognitive completion lock | Minted (#369–#374) |
| **V5** | Automation, MCP transport, voice | **Planned** — mint after V4.5 lock |
| *Horizon* | Physical speaker (spark-locate voice) | Direction only — no release # |
| *Horizon* | Brilliant Labs AI Frames + Crowley | Direction only — after voice + speaker **(inference)** |

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
- [V4_COGNITIVE_SPEC_GAP_ANALYSIS.md](./V4_COGNITIVE_SPEC_GAP_ANALYSIS.md)
- [V4_ACCEPTANCE_TEST_MATRIX.md](./V4_ACCEPTANCE_TEST_MATRIX.md)
- [V4.0_COGNITIVE_MEMORY_RELEASE_LOCK.md](./V4.0_COGNITIVE_MEMORY_RELEASE_LOCK.md)
- [V4.1_FINAL_ARCHITECTURE_AUDIT.md](./V4.1_FINAL_ARCHITECTURE_AUDIT.md)
- [VERSIONS.md](../VERSIONS.md)
