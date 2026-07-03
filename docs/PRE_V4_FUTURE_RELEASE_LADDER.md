# Crowley Future Pre-V4 Release Ladder

**Status:** V3.9.13 shipped on `main` · V4 planned next · V4 after .10/.11/.12/.13 gate complete.
**Baseline:** V3.9.7 on `origin/main`; V3.9.8+ in local working tree.
**Purpose:** Keep the next planning arc ready without cluttering Cursor's active ticket board.

---

## 1. Planning stance

Treat the remaining V3 line as quality gates before V4 memory architecture, not a place to add broad new product surface.

Crowley's north star is now sharper: **Crowley is the persistent context layer that follows D across reasoning surfaces.** ChatGPT, Cursor, Codex, Ollama, OpenAI, Claude, and the browser are terminals or reasoning engines that Crowley can operate through.

The target state before V4:

- Crowley knows what is true, what changed, what is open, and what is stale.
- Crowley answers with the right depth and tone for the moment.
- The workspace is usable for real daily work.
- Any AI/model surface can be used as a local/manual Crowley terminal with context in and structured writeback out.
- Operators can ask "are we ready for V4?" and get a concrete yes/no with blockers.

---

## 2. Current active batch

| Release | Theme | Status |
|---------|-------|--------|
| V3.9.5 | Conversation + Model Behavior | Shipped (#25–#30) |
| V3.9.6 | Workspace Polish | Shipped (#31–#36) |
| V3.9.7 | Workspace Experience & Reliability | Shipped (#40–#49) |
| V3.9.8 | Runtime Hardening | Shipped on `main` (#50–#55) |
| V3.9.9 | Context That Feeds | **Shipped on `main`** (#56–#63) |
| V3.9.10 | Task-Frame Context | **Shipped on `main`** (#64–#69) |
| V3.9.11 | Live Wire | **Shipped** (#70–#75) |
| V3.9.12 | Portable Context Terminal | **Shipped** (#76–#80) |
| V3.9.13 | Secure ChatGPT Actions API | **Shipped** — bearer `/api/actions/*` |
| V4.0 | Spark Lanes | **Next** — mint when Mr. Go directs |
| Pre-V4 QA Hygiene | State lock-in + stale loop cleanup | Shipped (#37) |

V4 memory-lane architecture starts when Mr. Go mints V4.0 (V3.9.12 terminal loop and V3.9.13 Actions API proven).

---

## 3. Likely future versions

### V3.9.13 — Secure ChatGPT Actions API (shipped)

Bearer-authenticated `/api/actions/*` for ChatGPT Custom GPT. Operator sets `CROWLEY_ACTION_KEY`; `./scripts/start_chatgpt_bridge.sh` for tunnel + verify. See [V3.9.13_SECURE_CHATGPT_ACTIONS_API.md](./V3.9.13_SECURE_CHATGPT_ACTIONS_API.md), [CHATGPT_ACTIONS_API.md](./CHATGPT_ACTIONS_API.md), [CHATGPT_SETUP.md](./CHATGPT_SETUP.md).

**Boundary:** Does not configure tunnel or Custom GPT automatically. Does not expose full internal API.

### V3.9.7 — Workspace Experience & Reliability (shipped)

Shipped as experience + reliability dual track — see [V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md](./V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md). Original "Memory Freshness" theme deferred to a future gate if needed.

### V3.9.8 — Runtime Hardening (shipped)

Shipped — see [V3.9.8_RUNTIME_HARDENING.md](./V3.9.8_RUNTIME_HARDENING.md). Unified test mode, model probe, `/api/health` runtime block, sqlite-vec safe fallback, fragile-startup regression suite.

### V3.9.9 — Context That Feeds (shipped)

**Goal:** Better memory entering better handoffs — quality gate, inclusion reasons, slim sync, handoff upgrade, feedback loop, UI/hygiene.

**Packet:** `tickets/v3.9.9_context_that_feeds.json` — approved, minted #56–#63.

Shipped — see [V3.9.9_CONTEXT_THAT_FEEDS.md](./V3.9.9_CONTEXT_THAT_FEEDS.md).

### V3.9.10 — Task-Frame Context (shipped)

**Goal:** Task frame first, supporting retrieval second — ticket narrative drives context, not generic search.

**Packet:** `tickets/v3.9.10_task_frame_context.json` — approved 2026-07-02, minted #64–#69.

Shipped — see [V3.9.10_TASK_FRAME_CONTEXT.md](./V3.9.10_TASK_FRAME_CONTEXT.md).

### V3.9.11 — Live Wire (minted)

**Goal:** Compose "In the air" live activity wire — agent pulses, ticket moves, ambient fallbacks; exposed to browser and agent sync.

**Packet:** `tickets/v3.9.11_live_wire.json` — approved 2026-07-02, minted #70–#75. **Next** after V3.9.10 lock.

### V3.9.12 — Portable Context Terminal (shipped)

**Goal:** Make any AI/model surface usable as a local/manual Crowley terminal: export a compact Crowley packet into that surface, then import a structured writeback containing an episodic receipt and candidate sparks. ChatGPT is the first tested surface, not the architecture.

**Packet:** `tickets/v3.9.12_portable_context_terminal.json` — approved and minted #76–#80.

Shipped — see [V3.9.12_PORTABLE_CONTEXT_TERMINAL.md](./V3.9.12_PORTABLE_CONTEXT_TERMINAL.md).

**Boundary:** V3.9.12 proves the workflow only. It does not build OAuth, a browser extension, live terminal automation, cloud sync, or durable lane architecture.

### V4.0 — Spark Lanes / Memory Architecture (planned)

**Goal:** Redesign memory around sparks as the memory unit and lanes as the retrieval/trust boundary.

**Packet:** `tickets/v4.0_spark_lanes.json` — planned, not minted. Start after V3.9.12 packet-in/writeback-out and V3.9.13 Actions API are proven.

**Primary lanes:** learning, work, relationships, money, health, operating_style.

Reserve packet `tickets/v3.9.9_memory_judgment_work_intelligence.json` — superseded by Context That Feeds theme.

---

## 4. V4 starts after this

V4 should mean memory architecture, not more UI polish or generic collectors.

- Sparks are the memory unit.
- Raw logs are receipts; episodic summaries are anchors; sparks are future-use compression; patterns emerge from reused sparks; canon remains manually reviewed high-trust truth.
- Retrieval chooses a lane/scope before searching broadly.
- Sensitive lanes default to candidate/review state.
- External collectors remain later optional inputs, not the V4 core.
