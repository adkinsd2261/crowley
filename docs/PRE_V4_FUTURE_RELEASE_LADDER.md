# Crowley Future Pre-V4 Release Ladder

**Status:** Planning reserve — do not mint tickets until V4 connectivity is underway or re-scoped.
**Baseline:** V3.9.7 shipped; Pre-V4 quality plan and experience batch complete.
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
| Pre-V4 QA Hygiene | State lock-in + stale loop cleanup | Shipped (#37) |

V4 connectivity is the active initiative. V3.9.8–V3.9.9 remain planning reserve.

---

## 3. Likely future versions

### V3.9.7 — Workspace Experience & Reliability (shipped)

Shipped as experience + reliability dual track — see [V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md](./V3.9.7_WORKSPACE_EXPERIENCE_RELIABILITY.md). Original "Memory Freshness" theme deferred to a future gate if needed.

### V3.9.8 -- Work Intelligence

**Goal:** make Crowley understand the work board, not just display it.

Likely focus:

- Release grouping for tickets.
- Ticket dependency and blocked-risk summaries.
- "What is next and why?" reasoning from tickets, handoffs, docs, and decisions.
- Automatic shipped-work timelines from ticket events and handoffs.
- Better summaries of Cursor/Codex work without raw handoff reading.

Done when Crowley can explain the current work program like a project co-founder.

### V3.9.9 -- Operator Confidence / Preflight

**Goal:** make it safe to start V4.

Likely focus:

- One-command health/preflight check.
- Bus/version drift detection.
- Doc-lock checks.
- Test/QA summary.
- V4 readiness diagnostic with hard yes/no and blockers.
- Final cleanup of stale state, loops, docs, and tickets.

Done when Crowley can tell Mr. Go whether V4 can begin and why.

---

## 4. V4 starts after this

V4 should mean connectivity, not more preflight:

- External collectors.
- Git/project activity ingestion.
- Multi-project commands.
- Later optional calendar/filesystem collectors.

Keep collectors opt-in and route new facts through memory_items, tickets, docs, and project state with clear authority order.
