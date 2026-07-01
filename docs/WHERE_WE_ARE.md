# Where We Are — Crowley (Codex / Cursor onboarding)

**As of:** V3.9 (`Crowley V3.9 Concurrent Ticketing`) · **2026-07-01**  
**Read this first** on any new Codex or Cursor session after `scripts/codex_sync.py --before` or `scripts/cursor_sync.py --before`.

---

## 1. What Crowley is right now

Crowley is a **local-first AI OS** for Mr. Go: chat UI + SQLite memory + world model + HTTP bus on `127.0.0.1:8765`.

**Pipeline (hardwired):**

```
Mr. Go ──► Crowley (memory, tickets, chat, docs)
              ▲ handoffs only
         Codex (architect) │ Cursor (builder)
```

- **Codex** — plans, decides, mints tickets, posts `architect_handoff` / `note`
- **Cursor** — implements, tests, closes tickets via `--after --ticket ID`
- **Crowley** — answers from filesystem docs + agent activity + tickets + memory (not chat guesses)

---

## 2. Version trail (shipped)

| Version | What landed |
|---------|-------------|
| V3.7 | Context bridge — `/api/context`, ingest, inbox scripts |
| V3.7.2 | Knowledge files in prompts + live UI dashboard |
| V3.7.3 | Memory consolidation (merge, dedupe, stale) |
| V3.8 | Memory Trail — truthful memory counts, canon path, multi-agent sync |
| V3.8.1 | Agent parity — `agent_activity`, stop hook, shared verify |
| **V3.9** | **Concurrent ticketing** — `tickets` table, `/api/tickets`, mint/claim/close |

**Current constants:** `CROWLEY_VERSION = "3.9"`, `CROWLEY_RELEASE_LABEL = "Crowley V3.9 Concurrent Ticketing"`

---

## 3. Memory trail (where truth lives)

| Layer | Source | Use for |
|-------|--------|---------|
| Filesystem | `VERSIONS.md`, `PROJECT_STATE.md`, `docs/WHERE_WE_ARE.md`, phase docs | Version, architecture, what shipped |
| Agent activity | `last_by_source` on `/api/agent/sync` | When did Codex/Cursor last post |
| Tickets | `/api/tickets`, sync bundle `tickets` | What work is open, assigned, blocked |
| project_state | SQLite `project_state` | Phase, focus, risk, next_action (may lag docs slightly) |
| Canon | Pinned `Canon:` rows in `memory_items` | Always-on continuity (after lock-in) |
| Handoffs | `.crowley/processed/*`, `memory_items` events | Session-by-session builder/architect log |
| Hybrid retrieval | `/api/retrieve` | Supporting context only — lower authority |

**Authoritative order for facts:** filesystem → tickets → agent_activity → project_state → canon → retrieval.

---

## 4. Agent rituals (required)

### Codex (new session)

```bash
./venv/bin/python3 scripts/codex_sync.py --before
```

Read: **Your role**, last contact, Cursor events, tickets, open loops.

After planning:

```bash
./venv/bin/python3 scripts/codex_sync.py --create-ticket \
  --title "…" --assignee cursor --priority 1 --description "…" --acceptance "…"

./venv/bin/python3 scripts/codex_sync.py --after \
  --summary "…" --next-action "…" --decision "…"
```

### Cursor (new session)

Hooks run `--before` automatically. After shipping:

```bash
./venv/bin/python3 scripts/cursor_sync.py --after --ticket <ID> \
  --summary "…" --next-action "…" --qa-result "tests OK"
```

---

## 5. Where we are (product)

**Done and stable:**

- Web UI + SSE chat, markdown replies, intelligence drawer (Tasks, **Tickets**, Loops, Decisions, Memory)
- Multi-agent hub: `codex_sync.py`, `cursor_sync.py`, `agent_sync_lib.py`
- Cursor hooks: sessionStart, beforeSubmitPrompt, stop (handoff nudge)
- 52+ unit tests (manual run; no CI yet)
- Personality: Crowley = the running system; Jarvis-shaped; filesystem-first answers
- Git baseline — `cursor_sync --after` and `crowley_handoff --from-git` populate file lists

**Known gaps (honest):**

- No CI pipeline (tests exist locally)
- Canon was empty until lock-in / first synthesis
- Legacy `tasks` + `open_loops` coexist with `tickets` (tickets = agent board)
- Some open_loops may be stale until backlog hygiene runs

---

## 6. Where we are heading (pick one next)

| Initiative | Owner | Notes |
|------------|-------|-------|
| **V3.9.1 — CI** | Cursor builds, Codex specs | GitHub Actions or similar; run `unittest discover` |
| **First canon synthesis** | Codex plans, manual `--write` | `scripts/synthesize_canon.py` |
| **Agent feed UI tab** | Cursor builds | API exists; dedicated tab deferred from V3.8 |

Codex should **mint tickets** for the chosen initiative; Cursor fills by ticket ID.

---

## 7. Key paths

| Path | Role |
|------|------|
| `crowley.py` | Engine |
| `app.py` | HTTP transport |
| `docs/V3.9_CONCURRENT_TICKETING.md` | V3.9 spec |
| `docs/V3.8_MEMORY_TRAIL.md` | Memory trail spec |
| `CODEX.md` / `CURSOR.md` | Agent rituals |
| `.cursor/rules/crowley-memory.mdc` | Cursor rule |
| `scripts/lock_in_state.py` | State hygiene (loops, canon seed, tickets) |
| `tickets/` | JSON templates for `--create-tickets` |

---

## 8. Quick health check

```bash
./scripts/ensure_crowley_bus.sh
curl -s http://127.0.0.1:8765/api/health | python3 -m json.tool
curl -s "http://127.0.0.1:8765/api/agent/sync?agent=codex&limit=5" | python3 -m json.tool
./venv/bin/python3 -m unittest discover -s tests -q
```

---

*This file is loaded into Crowley prompts and should stay current after each major ship.*
