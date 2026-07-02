# Crowley Pre-V4 Release Plan

**Status:** Approved plan  
**Baseline:** V3.9.1 (`Crowley V3.9.1 Repository & CI`)  
**Theme:** Natural memory, auditable on demand

---

## 1. Summary

Crowley will ship three focused releases before V4. The arc is balanced but memory-led:

1. **V3.9.2 — Memory Clarity**
2. **V3.9.3 — Planning Workflow**
3. **V3.9.4 — Agent Visibility / Pre-V4 Readiness**

The guiding principle:

> Crowley should feel natural in conversation, but auditable on demand.

Existing draft tickets `#4-#8` are cancelled as superseded. Cursor implementation work is tracked by tickets `#9-#23`.

---

## 2. Release Ladder

### V3.9.2 — Memory Clarity

**Goal:** Make Crowley's memory logic coherent without becoming rigid.

Cursor ticket slices:

- `#9` Run first canon synthesis workflow: dry-run, inspect packet, write canon only when validation passes, document exact operator steps.
- `#10` Add memory source/explanation surface: expose why a memory appears in prompt/retrieval, including source, type, score, pinned/canon status, and provenance where available.
- `#11` Clarify memory hierarchy in docs and UI language: filesystem/project state, tickets, agent activity, canon, retrieval, chat.
- `#12` Improve memory hygiene checks: identify stale/noisy/conflicting memory rows without auto-deleting anything.
- `#13` Fix test DB isolation/probe pollution so memory tests do not contaminate `crowley.db`.

### V3.9.3 — Planning Workflow

**Goal:** Turn Mr. Go + Codex planning into repeatable planning packets that become Cursor-ready tickets.

Cursor ticket slices:

- `#14` Add Planning Workflow doc: roles, when to brainstorm, when to mint tickets, what "Cursor-ready" means.
- `#15` Add planning packet template: objective, context, decisions, non-goals, risks, ticket slices, acceptance criteria, QA expectations, next action.
- `#16` Add ticket packet validation for `codex_sync.py --create-tickets`: fail before partial creation if required fields are missing.
- `#17` Support initiative grouping with existing `parent_id`: parent planning ticket plus child Cursor tickets.
- `#18` Add a cleanup path for draft/superseded tickets so accidental early tickets can be marked cancelled or replaced cleanly.

### V3.9.4 — Agent Visibility / Pre-V4 Readiness

**Goal:** Make the multi-agent workflow visible and easy to operate before external collectors arrive.

Cursor ticket slices:

- `#19` Add Agent Feed tab to Intelligence drawer using existing agent activity APIs.
- `#20` Add ticket detail view with description, acceptance criteria, status, assignee, priority, and event timeline.
- `#21` Surface handoff-linked ticket history so Cursor's shipped work is visible from the board.
- `#22` Clarify relationship between tickets, legacy tasks, and open loops; tickets remain the agent work board.
- `#23` Update roadmap/onboarding docs so V4 begins from a clean, current state.

---

## 3. V4 Readiness Gate

Do not begin V4 connectivity until these are true:

- Canon exists and is understandable.
- Memory retrieval can be inspected enough to debug bad answers.
- Planning packets can produce small Cursor tickets without relying on chat history.
- Agent/ticket activity is visible in the browser.
- Tests are isolated from the real working database.

---

## 4. Test Plan

- Unit tests for canon synthesis validation, memory retrieval explanation payloads, ticket packet validation, parent/child ticket behavior, and ticket event timeline APIs.
- UI smoke checks for Memory, Tickets, and Agent Feed tabs on desktop and mobile widths.
- Regression check: `python -m unittest discover -s tests -q`.
- Manual QA: run Codex/Cursor sync flow, mint a small test ticket packet, close a ticket with handoff, verify Crowley can explain current work from tickets and agent activity.

---

## 5. Assumptions

- Keep Crowley local-first and SQLite-backed.
- No direct Codex-to-Cursor messaging; Crowley remains the hub.
- No auto-delete or destructive memory cleanup.
- Prefer small Cursor tickets that can ship in one focused pass.
- V4 connectivity means external collectors later, not during this pre-V4 ladder.
