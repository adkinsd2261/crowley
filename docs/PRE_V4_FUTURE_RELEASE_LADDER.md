# Crowley Future Pre-V4 Release Ladder

**Status:** V3.9.9 active locally · V3.9.10–V3.9.11 minted · V4 after .9/.10/.11 gate.
**Baseline:** V3.9.7 on `origin/main`; V3.9.8+ in local working tree.
**Purpose:** Keep the next planning arc ready without cluttering Cursor's active ticket board.

---

## 1. Planning stance

Treat the remaining V3 line as quality gates before V4 connectivity, not a place to add broad new product surface.

The target state before V4:

- Crowley knows what is true, what changed, what is open, and what is stale.
- Crowley answers with the right depth and tone for the moment.
- The workspace is usable for real daily work.
- Operators can ask "are we ready for V4?" and get a concrete yes/no with blockers.

---

## 2. Current active batch

| Release | Theme | Status |
|---------|-------|--------|
| V3.9.5 | Conversation + Model Behavior | Shipped (#25–#30) |
| V3.9.6 | Workspace Polish | Shipped (#31–#36) |
| V3.9.7 | Workspace Experience & Reliability | Shipped (#40–#49) |
| V3.9.8 | Runtime Hardening | Local (#50–#55) — push with V3.9.9 lock |
| V3.9.9 | Context That Feeds | **Active** (#56–#61 done; #62 QA; #63 lock) |
| V3.9.10 | Task-Frame Context | Minted (#64–#69) — after V3.9.9 |
| V3.9.11 | Live Wire | Minted (#70–#75) — after V3.9.10 |
| Pre-V4 QA Hygiene | State lock-in + stale loop cleanup | Shipped (#37) |

V4 connectivity starts after V3.9.11 doc lock (or Mr. Go reprioritizes).

---

## 3. Likely future versions

### V3.9.7 — Workspace Experience & Reliability (shipped)

Shipped as experience + reliability dual track — see [V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md](./V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md). Original "Memory Freshness" theme deferred to a future gate if needed.

### V3.9.8 — Runtime Hardening (shipped)

Shipped — see [V3.9.8_RUNTIME_HARDENING.md](./V3.9.8_RUNTIME_HARDENING.md). Unified test mode, model probe, `/api/health` runtime block, sqlite-vec safe fallback, fragile-startup regression suite.

### V3.9.9 — Context That Feeds (active)

**Goal:** Better memory entering better handoffs — quality gate, inclusion reasons, slim sync, handoff upgrade, feedback loop, UI/hygiene.

**Packet:** `tickets/v3.9.9_context_that_feeds.json` — approved, minted #56–#63.

**Status:** #56–#61 closed locally; **#62 in_progress** (UI + hygiene — awaiting QA); **#63** doc lock pending.

### V3.9.10 — Task-Frame Context (minted)

**Goal:** Task frame first, supporting retrieval second — ticket narrative drives context, not generic search.

**Packet:** `tickets/v3.9.10_task_frame_context.json` — approved 2026-07-02, minted #64–#69. Do not claim until V3.9.9 #63 closes.

### V3.9.11 — Live Wire (minted)

**Goal:** Compose "In the air" live activity wire — agent pulses, ticket moves, ambient fallbacks; exposed to browser and agent sync.

**Packet:** `tickets/v3.9.11_live_wire.json` — approved 2026-07-02, minted #70–#75. Do not claim until V3.9.10 #69 closes.

Reserve packet `tickets/v3.9.9_memory_judgment_work_intelligence.json` — superseded by Context That Feeds theme.

---

## 4. V4 starts after this

V4 should mean connectivity, not more preflight:

- External collectors.
- Git/project activity ingestion.
- Multi-project commands.
- Later optional calendar/filesystem collectors.

Keep collectors opt-in and route new facts through memory_items, tickets, docs, and project state with clear authority order.
