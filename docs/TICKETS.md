# Crowley — Backlog & Tickets

**As of:** V3.9.19 · V4.0 Cognitive Memory **mid-lock** T1–T13 (#203–#215) · 2026-07-07
**Source of truth:** `tickets` table (agent board) · legacy `project_state`, `open_loops`, `tasks` in SQLite

---

## Active initiative — V4.0 Cognitive Memory

**Current:** V3.9.19 Memory Quality shipped (#152–#166). **Active:** V4.0 Cognitive Memory — **14/24 tickets shipped** (#203–#216). **Not a release** — version constant still `3.9.19` until T24 (#226).

**Packet:** `tickets/v4.0_cognitive_memory.json` (supersedes `v4.0_spark_lanes.json`)  
**Mid-lock doc:** [V4.0_COGNITIVE_MEMORY_MID_LOCK.md](./V4.0_COGNITIVE_MEMORY_MID_LOCK.md)  
**Part 1 bridge E2E (2026-07-07):** [V4.0_PART1_BRIDGE_E2E_LOCK.md](./V4.0_PART1_BRIDGE_E2E_LOCK.md)  
**T14 context resolution (2026-07-07):** [V4.0_T14_CONTEXT_RESOLUTION_LOCK.md](./V4.0_T14_CONTEXT_RESOLUTION_LOCK.md) — resume **#217 (T15)**

**Next ladders (minted, do not claim until prior ladder doc-locked):**


| Release                    | Tickets | Packet                                    | Status                          |
| -------------------------- | ------- | ----------------------------------------- | ------------------------------- |
| V3.9.9 Context That Feeds  | #56–#63 | `tickets/v3.9.9_context_that_feeds.json`  | **Shipped on `main`**             |
| V3.9.10 Task-Frame Context | #64–#69 | `tickets/v3.9.10_task_frame_context.json` | **Shipped on `main`**             |
| V3.9.11 Live Wire          | #70–#75 | `tickets/v3.9.11_live_wire.json`          | **Shipped on `main`**             |
| V3.9.12 Portable Context Terminal   | #76–#80 | `tickets/v3.9.12_portable_context_terminal.json`   | **Shipped on `main`**  |
| V3.9.15 GPT Toolbelt              | #94–#100 | `tickets/v3.9.15_gpt_toolbelt.json`              | **Shipped**  |
| V3.9.16 Workflow Enforcement      | #101–#111 | `tickets/v3.9.16_workflow_enforcement.json`   | **Shipped**  |
| V3.9.17 Trust Control and Clarity | #112–#130 | —                                             | **Shipped**  |
| V3.9.19 Memory Quality              | #152–#166 | —                                             | **Shipped**  |
| V3.9.18 Agent Retrieval Enforcement | #131–#135 | —                                             | **Shipped**  |
| V3.9.14 Durable ChatGPT Bridge       | #82–#86 | `tickets/v3.9.14_durable_chatgpt_bridge.json`   | **Shipped**  |
| V3.9.13 Secure ChatGPT Actions API  | —       | `docs/V3.9.13_SECURE_CHATGPT_ACTIONS_API.md`       | **Shipped on `main`**  |
| V4.0 Cognitive Memory      | #203–#226 | `tickets/v4.0_cognitive_memory.json`      | **In progress** · T1–T14 shipped · T15–T24 open |


See [V3.9.14_DURABLE_CHATGPT_BRIDGE.md](./V3.9.14_DURABLE_CHATGPT_BRIDGE.md) · [V3.9.13_SECURE_CHATGPT_ACTIONS_API.md](./V3.9.13_SECURE_CHATGPT_ACTIONS_API.md) · [WHERE_WE_ARE.md](./WHERE_WE_ARE.md).


| Ticket theme                                   | Status                                       |
| ---------------------------------------------- | -------------------------------------------- |
| V3.9.2 Memory Clarity (#9–#13)                 | Shipped on `main`                            |
| V3.9.3 Planning Workflow (#14–#18)             | Shipped on `main`                            |
| V3.9.4 Agent Visibility (#19–#23)              | Shipped on `main`                            |
| V3.9.5 Conversation + Model Behavior (#25–#30) | Shipped on `main`                            |
| V3.9.6 Workspace Polish (#31–#36)              | Shipped on `main`                            |
| Pre-V4 QA hygiene (#37)                        | Shipped on `main`                            |
| V3.9.7 Experience & Reliability (#40–#49)      | Shipped on `main`                            |
| V3.9.8 Runtime Hardening (#50–#55)             | **Shipped on `main`** |
| V3.9.9 Context That Feeds (#56–#63)            | **Shipped on `main`** — shipped at #63 doc lock     |
| V3.9.10 Task-Frame Context (#64–#69)         | **Shipped on `main`** — shipped at #69 doc lock     |
| V3.9.11 Live Wire (#70–#75)                  | **Shipped on `main`** — shipped at #75 doc lock     |
| V3.9.12 Portable Context Terminal (#76–#80)             | **Shipped on `main`** — shipped at #80 doc lock     |
| #81 Sync parity (codex `--known-issue`)        | **Shipped on `main`** |
| V3.9.13 Secure ChatGPT Actions API               | **Shipped on `main`** — bearer `/api/actions/*` + bridge |
| V3.9.16 Workflow Enforcement (#101–#111)         | **Shipped** — boot gate, QA pipeline, core tools |
| V3.9.17 Trust Control and Clarity (#112–#130)  | **Shipped** — attribution, audit, tiers, agent behavior |
| V3.9.19 Memory Quality (#152–#166)             | **Shipped** — ingest dedup, lifecycle, validation runtime wiring |
| V3.9.18 Agent Retrieval Enforcement (#131–#135) | **Shipped** — gating, domain triggers, handoff tickets |
| V4.0 Cognitive Memory (#203–#226)              | **Mid-lock** — T1–T14 (#203–#216) shipped; T15–T24 open |

**Direction pivot:** Crowley is the persistent context layer that follows D across reasoning surfaces. Portable Context Terminal proves packet-in/writeback-out. V4.0 makes sparks the core memory unit with lanes: learning, work, relationships, money, health, operating_style.


Run `scripts/codex_sync.py --before` and read [WHERE_WE_ARE.md](./WHERE_WE_ARE.md).

Draft tickets `#4-#8` were cancelled as superseded. Reserve packet `tickets/v3.9.9_memory_judgment_work_intelligence.json` superseded by Context That Feeds theme.

---

## Open loops (tracked in DB — post lock-in hygiene)


| Priority | Item                                             |
| -------- | ------------------------------------------------ |
| P1       | LLM merge of duplicate content bodies (deferred) |
| P3       | Debounced canon synthesis after ingest           |
| P4       | QA autonomous extraction                         |


Resolved: test DB isolation (#13, shipped).

---

## Completed (recent)

- **V4.0 Part 1 bridge E2E (2026-07-07)** — ChatGPT Actions loop verified; sqlite-vec, auto-promote, retrieve hardening — [V4.0_PART1_BRIDGE_E2E_LOCK.md](./V4.0_PART1_BRIDGE_E2E_LOCK.md)
- **V4.0 Part 1 patch (2026-07-07)** — agent.sync ASE (#229–#231) + GitHub read envelope — [V4.0_PART1_PATCH_AGENT_GITHUB.md](./V4.0_PART1_PATCH_AGENT_GITHUB.md)
- **V4.0 Cognitive Memory (partial · mid-lock #215)** — sparks through context orchestration — see [V4.0_COGNITIVE_MEMORY_MID_LOCK.md](./V4.0_COGNITIVE_MEMORY_MID_LOCK.md)
- **V3.9.13 Secure ChatGPT Actions API** — bearer `/api/actions/*`, `CROWLEY_ACTION_KEY`, OpenAPI, bridge (`start_chatgpt_bridge.sh`)
- **#81 Sync parity** — codex_sync `--known-issue` parity with cursor_sync
- **V3.9.12 Portable Context Terminal** — packet export, writeback parse/ingest, CLI (#76–#80)
- **V3.9.11 Live Wire** — activity pulses, compose wire UI, brain switcher (#70–#75)
- **V3.9.10 Task-Frame Context** — task frame API, ticket-narrative retrieval (#64–#69)
- **V3.9.9 Context That Feeds** — quality gate, slim sync, feedback loop (#56–#63)
- **V3.9.8 Runtime Hardening** — test mode, runtime health, fragile-startup suite (#50–#55)
- **V3.9.5 Conversation + Model Behavior** — mode classifier (#25), depth (#26), personality (#27), diagnostics separation (#28), fixtures (#29), chat UX (#30)
- **V3.9.7 Experience & Reliability** — drawer polish (#40), chat readability (#41), embed fallback (#42), CI slim deps (#43), cohesion (#44), work surfaces (#45), diagnostics module (#46), tickets module (#47), metrics (#48), preflight lock (#49)
- **V3.9.6 Workspace Polish** — panel states (#31), streaming (#32), navigation (#33), what-changed feed (#34), livability (#35), docs lock (#36)
- **V3.9.4 Agent Visibility** — Agent Feed (#19), ticket detail (#20), handoff links (#21), work-board clarity (#22), V4 doc lock (#23)
- **V3.9.3 Planning Workflow** — packet template/validation, parent initiatives, cancel path (#14–#18)
- **V3.9.2 Memory Clarity** — canon workflow, retrieval explanations, hierarchy, hygiene, test isolation (#9–#13)
- **V3.9.1 Repository & CI** — GitHub remote, `.github/workflows/tests.yml`, doc sweep
- Git repository baseline — [github.com/adkinsd2261/crowley](https://github.com/adkinsd2261/crowley)
- V3.9 Concurrent Ticketing (`tickets` API, sync mint/claim/close, UI tab, prompt block)
- V3.8 Memory Trail (truthful counts, memory filters, canon path, synthesis script)
- V3.8 multi-agent sync (`codex_sync.py`, `cursor_sync.py`, `/api/agent/sync`, Cursor hooks)
- Bus restart QA on 8765
- V3.6 Phase 4 memory consolidation (session merge, dedupe, stale, daily opt-in)
- Live UI sync (dashboard, polling, phase bar, intelligence polish, task done)
- V3.7 Context Bridge (phases 1–6)
- V3.7.1 QA patch · V3.7.2 Knowledge files · V3.7.3 Consolidation
- UI Memory tab · Cursor `crowley-memory.mdc` rule
- Full V3.6–V3.7 integration QA

---

## Conventions

1. `project_state.phase` → `Phase N/M — Title` for progress UI.
2. Complete tasks: CLI `/task done <id>` or ✓ in Intelligence → Tasks tab.
3. Ingest Cursor/Codex handoffs after dev sessions for memory alignment.
4. Run consolidation: `python crowley.py --consolidate all` or `/debug consolidate all`.
5. Pull agent context before work: `cursor_sync.py --before` or `codex_sync.py --before`.
6. New session onboarding: read `docs/WHERE_WE_ARE.md` (loaded in every Crowley prompt).
7. Re-run lock-in after major ships: `scripts/lock_in_state.py`.
8. CI runs on every push/PR to `main` — keep tests green before merge.
