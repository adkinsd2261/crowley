# Crowley — Backlog & Tickets

**As of:** V3.9.4 · Pre-V4 ladder complete (2026-07-02)
**Source of truth:** `tickets` table (agent board) · legacy `project_state`, `open_loops`, `tasks` in SQLite

---

## Active initiative

**Pre-V4 release ladder complete.** V4 connectivity is the next theme — Codex plans; Cursor implements when minted. See [PRE_V4_RELEASE_PLAN.md](./PRE_V4_RELEASE_PLAN.md) and [V3.9.4_AGENT_VISIBILITY.md](./V3.9.4_AGENT_VISIBILITY.md).

| Ticket theme | Status |
|--------------|--------|
| V3.9.2 Memory Clarity (#9–#13) | Shipped on `main` |
| V3.9.3 Planning Workflow (#14–#18) | Shipped on `main` |
| V3.9.4 Agent Visibility (#19–#23) | Shipped on `main` |

Run `scripts/codex_sync.py --before` and read [WHERE_WE_ARE.md](./WHERE_WE_ARE.md).

Draft tickets `#4-#8` were created during planning and are cancelled as superseded. Active Cursor implementation tickets are `#9-#23`.

---

## Open loops (tracked in DB — post lock-in hygiene)

| Priority | Item |
|----------|------|
| P1 | LLM merge of duplicate content bodies (deferred) |
| P3 | Debounced canon synthesis after ingest |
| P4 | QA autonomous extraction |

Resolved: test DB isolation (#13, shipped).

---

## Completed (recent)

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
