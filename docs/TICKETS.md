# Crowley — Backlog & Tickets

**As of:** V3.9 shipped (2026-07-01)  
**Source of truth:** `project_state`, `open_loops`, `tasks` in SQLite · **V3.9 target:** `tickets` table (planned).

---

## Active initiative

**Pick next** (planning tickets minted on board):

| Ticket theme | Assignee | Priority |
|--------------|----------|------------|
| V3.9.1 CI pipeline | Codex plans | P2 |
| First canon synthesis | Codex plans | P2 |
| Agent feed UI tab | Codex plans | P3 |

Run `scripts/codex_sync.py --before` and read [WHERE_WE_ARE.md](./WHERE_WE_ARE.md).

---

## Open loops (tracked in DB — post lock-in hygiene)

| Priority | Item |
|----------|------|
| P1 | LLM merge of duplicate content bodies (deferred) |
| P2 | Automated CI test suite |
| P2 | QA test isolation / probe row pollution |
| P3 | Debounced canon synthesis after ingest |
| P4 | QA autonomous extraction |

---

## Completed (recent)

- Git repository initialized (`.gitignore`, baseline commit, `--from-git` handoffs)
- V3.9 Concurrent Ticketing (`tickets` API, sync mint/claim/close, UI tab, prompt block)
- V3.8 Memory Trail (truthful counts, memory filters, canon path, synthesis script)
- V3.8 multi-agent sync (`codex_sync.py`, `cursor_sync.py`, `/api/agent/sync`, Cursor hooks)
- Bus restart QA on 8765 (37 tests passing)
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
