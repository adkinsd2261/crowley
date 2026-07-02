# Codex Backlog Report — 2026-07-02 (session pause)

**For:** Codex architect lane  
**From:** Cursor builder  
**Mr. Go:** Away until ~2pm; resume workflow at ticket **#62**  
**Full report path:** this file (loaded via filesystem authority)

---

## 1. Executive summary

Large block of work landed **locally** since `origin/main` (V3.9.7, commit `c5aa4de`). **Nothing from V3.9.8 onward has been pushed to GitHub.** Mr. Go approved V3.9.10 (#64–#69) and V3.9.11 (#70–#75) planning packets — **mint only**, no implementation yet.

**Resume order:** `#62` QA → close → `#63` doc lock (V3.9.9) → V3.9.10 `#64–#69` one at a time → V3.9.11 `#70–#75`.

---

## 2. Git / push status (critical)

| Item | State |
|------|-------|
| `origin/main` | `c5aa4de` — V3.9.7 doc lock |
| Local working tree | **All V3.9.8 + V3.9.9 work uncommitted** |
| Pushed without Mr. Go approval? | **No** — nothing pushed beyond V3.9.7 |
| `CROWLEY_VERSION` in local code | `3.9.8` (bumps to `3.9.9` at ticket #63) |

**Codex action:** Treat local tree as source of truth for V3.9.8–V3.9.9 until Mr. Go approves commit/push at #63 or a dedicated push ticket.

---

## 3. Ticket ladder status

### V3.9.8 Runtime Hardening (#50–#55)

Implemented locally. Packet: `tickets/v3.9.8_runtime_hardening.json`. Release doc: `docs/V3.9.8_RUNTIME_HARDENING.md`.

### V3.9.9 Context That Feeds (#56–#63)

Packet: `tickets/v3.9.9_context_that_feeds.json` — **approved and minted**.

| Ticket | Title | Status |
|--------|-------|--------|
| #56 | Memory quality gate | **Closed** (handoff #406) |
| #57 | Retrieval inclusion reasons | **Closed** (#412) |
| #58 | Slim agent sync bundle | **Closed** (#415) |
| #59 | Handoff to memory upgrade | **Closed** (#423) |
| #60 | Post-work feedback loop | **Closed** (#429) |
| #61 | Handoff-ticket wiring | **Closed** (#431) |
| **#62** | Light UI + hygiene report | **in_progress** — code shipped, **awaiting Mr. Go QA** |
| #63 | Doc lock + version bump | **open** — last in V3.9.9 |

**#62 shipped locally (not closed):**

- `GET /api/hygiene` alias; extended `memory_hygiene_report()` (stale_loops, version_conflicts)
- Ticket-aware retrieval: `build_ticket_aware_retrieval_query()`, `retrieve_work_context_memories()`, open-ticket boost
- Agent Feed: "Context pulled for agents" with inclusion_reason pills; Memory tab hygiene callout
- UI retheme to Crowley accent; context section above handoff timeline
- Tests: `tests/test_ui_context_v399.py` (7 tests)

**Product feedback (Mr. Go):** Generic hybrid retrieval in Agent Feed feels wrong when working a specific ticket — context should help the job *in the moment*. Led to V3.9.10 task-frame design.

### V3.9.10 Task-Frame Context (#64–#69)

Packet: `tickets/v3.9.10_task_frame_context.json` — **approved 2026-07-02, minted**.

| Ticket | Title |
|--------|-------|
| #64 | Task frame builder API |
| #65 | Ticket-narrative retrieval |
| #66 | Sync bundle task brief |
| #67 | UI brief for current work |
| #68 | Chat prompt task frame injection |
| #69 | Doc lock + 3.9.10 bump |

**Do not claim until V3.9.9 #63 closes.**

### V3.9.11 Live Wire (#70–#75)

Packet: `tickets/v3.9.11_live_wire.json` — **approved 2026-07-02, minted this session**.

| Ticket | Title |
|--------|-------|
| #70 | Activity pulse table + POST API |
| #71 | Sync script pulse hooks |
| #72 | build_activity_wire builder |
| #73 | World + sync exposure |
| #74 | Compose live wire UI |
| #75 | Doc lock + 3.9.11 bump |

**Do not claim until V3.9.10 #69 closes.**

Theme: compose "In the air" becomes a living activity wire (pulses, ticket moves, ambient fallbacks) — useful to browser and agent sync. No file watcher / WebSocket in v1.

---

## 4. Work done without separate Codex approval (local only)

All items below are **in the uncommitted working tree**. Mr. Go approved V3.9.9 packet and individual ticket QA as the workflow progressed; V3.9.10/3.9.11 were **plan-approved, mint-only**.

| Work block | Tickets | Codex visibility |
|------------|---------|------------------|
| V3.9.8 runtime hardening | #50–#55 | Local code + packet; not on `main` |
| V3.9.9 quality gate through wiring | #56–#61 | Closed handoffs in Crowley memory |
| V3.9.9 UI/hygiene (partial) | #62 | In progress — needs QA |
| V3.9.10 packet draft + mint | #64–#69 | Approved by Mr. Go; minted via codex_sync |
| V3.9.11 plan + mint | #70–#75 | Approved by Mr. Go this session |

**No direct Cursor↔Codex channel.** Codex reads this via `events_from_other_agents` and filesystem docs after sync.

---

## 5. Test / QA status

```
CROWLEY_TEST_MODE=1 CROWLEY_EMBED_PROVIDER=off python -m unittest discover -s tests
→ Ran 219 tests — FAILED (failures=4)
```

Expected failures until #63 doc lock:

- `test_onboarding_docs_locked_for_v397`
- `test_ui_contains_livability_pass_styles`
- `test_project_state_updates_reference_quality_batch`
- `test_refresh_project_state_writes_lock_in_fields`

**Bus restart required** after code changes for live API/UI QA.

---

## 6. Key files touched (uncommitted)

**Engine:** `crowley.py`, `app.py`, `tickets.py`  
**UI:** `static/app.js`, `static/index.html`, `static/styles.css`  
**Scripts:** `cursor_sync.py`, `codex_sync.py`, `agent_sync_lib.py`, `crowley_handoff.py`, `lock_in_state.py`, `preflight.py`  
**Tests:** `test_runtime_hardening.py`, `test_memory_quality_gate.py`, `test_slim_agent_sync.py`, `test_handoff_memory_upgrade.py`, `test_feedback_loop.py`, `test_handoff_ticket_wiring.py`, `test_ui_context_v399.py`, `test_test_mode.py`, others  
**Docs:** VERSIONS, WHERE_WE_ARE, TICKETS, PROJECT_STATE, ROADMAP, PRE_V4_FUTURE_RELEASE_LADDER, V3.9.8_RUNTIME_HARDENING.md, this report  
**Packets:** `v3.9.8`, `v3.9.9`, `v3.9.10`, `v3.9.11` JSON in `tickets/`

---

## 7. Recommended Codex backlog (on return)

1. **Review this report** + `docs/WHERE_WE_ARE.md` after `codex_sync --before`
2. **Do not reprioritize** V3.9.10/3.9.11 until Mr. Go confirms #62 QA
3. **At #63:** plan single commit/push of V3.9.8 + V3.9.9 to `main` (Mr. Go decision)
4. **V3.9.10 planning is done** — no new packet needed unless Mr. Go redirects task-frame design
5. **Reserve packet** `tickets/v3.9.9_memory_judgment_work_intelligence.json` is **superseded** by Context That Feeds — do not mint
6. **Anomaly:** test run may have minted spurious ticket #42 ("Valid probe") from validation tests — consider cancelling if present on board

---

## 8. Decisions for Codex to honor

- Task frame (V3.9.10) is authoritative over retrieval for agent context
- Live wire (V3.9.11) is motion/activity, separate from task frame
- One ticket at a time: claim → implement → QA → Mr. Go approve → `--after --ticket N`
- No direct Codex-to-Cursor communication
- Finish V3.9.9 before starting V3.9.10

---

*Generated by Cursor at session pause. Update after #62/#63 close.*
