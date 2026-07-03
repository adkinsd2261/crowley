# Crowley — Engineering Principles

**Purpose:** Codify design rules visible in the codebase and V3 phase specifications so future work stays coherent.  
**Status:** Derived from `crowley.py` (V3.6 + V3.7.3 + V3.8.1) — not aspirational policy unless marked **(inference)**.

---

## 1. Product philosophy

### 1.1 Conversation is the primary UX **(fact from V3 specs, embodied in code)**

Users should accomplish goals by talking naturally. Slash commands exist for:

- **Override** — correct or set state explicitly
- **Inspection** — see what Crowley believes
- **Control** — tasks, memories, diagnostics on demand

Evidence: `ask_crowley` is the default path in `main()`; autonomous sparks and extraction hook off chat, not commands.

### 1.2 Crowley is Jarvis-shaped co-architect **(fact)**

`_personality_prompt()` defines:

- Local operating intelligence — composed, capable, unhurried (Jarvis-shaped, not servile)
- Natural charisma — wit, warmth, presence; not flattened generic-assistant mode
- Behavioral framing: read the message, match the moment, consult context when facts matter
- Addresses user as Mr. Go; partner dynamic, not help desk

### 1.3 Local-first, single-user **(inference)**

- SQLite file beside the script
- No authentication
- No multi-tenant design
- `.env` for optional cloud API key only

---

## 2. Truth and hallucination

### 2.1 Tiered sources of truth

| Question type | Authoritative source |
|---------------|-------------------|
| Personal / episodic facts | `memory_items` via `retrieve_memories()` in prompt |
| Legacy sparks | `memories` table (dual-written; UI still reads here) |
| Project phase/focus/risk/next action | `project_state` via world context |
| Work items | `tasks` (open) |
| What was decided | `decisions` table |
| What's unresolved | `open_loops` |
| OS health briefing | `gather_diagnostics_context()` SQL facts |
| External agent context | `GET /api/context` (read-only bundle) |

### 2.2 Anti-hallucination rule **(fact)**

From `_personality_prompt()`:

> Only state personal facts if they appear in Relevant memories, Current project state, or Open tasks below.  
> If no stored record exists, say: "I don't have that stored yet."

This is **non-negotiable** for chat behaviour.

### 2.3 Diagnostics: SQL first, model second **(fact)**

`gather_diagnostics_context()` performs zero inference. The model **formats** facts; it must not invent them.

Same pattern for extraction **validation** — model proposes; code decides what writes.

### 2.4 Grounding rule for extraction **(fact)**

User messages are the primary grounding for world-model updates. Assistant suggestions do not apply unless the user clearly agrees (enforced in extraction prompt text).

---

## 3. Memory principles

### 3.1 Messages are raw logs; memories are curated **(fact)**

Docstring in `should_create_implicit_spark`:

> Messages are raw logs; memories are curated.

Every user message is stored in `messages`. Only filtered subsets become sparks.

### 3.2 Two-tier sparks **(fact)**

| Tier | Importance | Purpose |
|------|------------|---------|
| Trim | 1 | Quick capture of signal-heavy user lines |
| Summary | ≥2 | Distilled episodic chunk after conversation batch |

### 3.3 Filter before write **(fact)**

Both trim sparks and extraction use **gate functions** before expensive or persistent actions:

- `should_create_implicit_spark()` — keyword, length, shell, greeting filters
- `should_attempt_state_extract()` — parallel philosophy with extraction-specific keywords

**Principle:** cheap deterministic filters → expensive model calls.

### 3.4 Retrieval is intentionally simple today **(fact)**

Bag-of-words `search_memories()` — predictable, debuggable, no GPU required.

**(inference)** Vector search should remain optional and inspectable when added.

### 3.5 Passive over interactive for episodic memory **(fact)**

Users are not asked “should I remember this?” for sparks. Filtering handles quality.

**(inference)** World-model extraction follows same philosophy — quiet apply, manual correct via commands.

---

## 4. World model principles

### 4.1 Separate episodic memory from project state **(fact)**

Sparks capture *what was said*. World model captures *what is true about the project now*.

Both inject into prompts but serve different roles.

### 4.2 Append-only decisions **(fact)**

No command or extraction path deletes decisions. History accumulates.

### 4.3 Open loops are actionable tension **(fact)**

Loops represent unresolved items with priority. Closing is **manual only** (`/loops done`).

### 4.4 Conservative autonomous maintenance **(fact, V3.2)**

| Rule | Implementation |
|------|----------------|
| High bar to write | `EXTRACT_CONFIDENCE_MIN = 0.85` |
| When unsure, skip | Empty JSON encouraged in prompt |
| No destructive auto ops | Apply only adds/updates allowed fields |
| Dedupe | 24h decisions, open loop descriptions |
| Reject noise | Generic value blocklist |
| No downgrade | `_is_lower_information()` |
| Quiet | No user-facing apply notifications |
| Inspectable | `/debug extract`, `/world` |
| Reversible | `/state set`, manual loop close |

### 4.5 `updated_by` provenance **(fact)**

`project_state.updated_by` records `seed`, `user`, or `extract` — manual overrides remain auditable.

---

## 5. Inference and provider principles

### 5.1 Single inference gateway **(fact)**

All model calls go through `call_model()`:

- Chat (streaming)
- Summarisation (quiet, non-streaming)
- Diagnostics formatting (streaming)
- Extraction proposals (quiet, non-streaming)

**Principle:** one place to add providers, logging, retries.

### 5.2 Auto mode with graceful fallback **(fact)**

`MODEL_PROVIDER = "auto"` prefers OpenAI when key present; falls back to Ollama once on failure.

### 5.3 Background inference is quiet **(fact)**

`quiet=True` suppresses terminal errors for spark summarisation and extraction — must not interrupt REPL UX.

### 5.4 Streaming for user-facing replies only **(fact)**

User sees token stream for chat and diagnostics. Background jobs use `stream=False`.

---

## 6. Concurrency and SQLite

### 6.1 Fresh connections in background threads **(fact)**

`create_spark()` and `_run_extraction()` open their own `connect_db()` — never share connections across threads.

### 6.2 Non-blocking locks **(fact)**

`_spark_lock.acquire(blocking=False)` and `_extract_lock.acquire(blocking=False)` — if busy, skip work rather than queue indefinitely.

### 6.3 WAL mode **(fact)**

`PRAGMA journal_mode=WAL` — readers/writers coexist better for CLI + background writers.

### 6.4 Fail soft on extraction **(fact)**

`_run_extraction` catches all exceptions and passes — chat must never crash due to background maintenance.

**(inference)** Tradeoff: silent data loss of extraction vs REPL stability; debug tooling compensates.

---

## 7. Command design principles

### 7.1 Slash prefix **(fact)**

Commands start with `/`. Gating functions reject `/` messages for sparks and extraction.

### 7.2 Pipe-delimited arguments **(fact)**

`/remember`, `/task add`, `/decisions add`, `/loops add` use `|` separators — consistent parsing via `_parse_pipe_pair`.

### 7.3 Read-only debug namespace **(fact)**

`/debug *` inspects without changing state — except `/debug extract` which calls model but uses `dry_run=True` for apply.

### 7.4 Diagnostics accepts no args **(fact)**

`/diagnostics` with trailing args prints usage — prevents accidental conflation with chat.

---

## 8. Code organisation principles

### 8.1 Minimal scope diffs **(inference from user rules + version history)**

Features accreted as sections in one file:

```
constants → db → world model → diagnostics → extraction → memory → retrieval → prompting → CLI
```

New work should add focused functions in the appropriate section, not rewrite unrelated paths.

### 8.2 No schema changes unless necessary **(fact from V3 specs)**

V3.2 added zero schema migrations — extraction uses existing tables and `source` / `updated_by` columns.

### 8.3 Constants over magic numbers **(fact)**

Thresholds (`MEMORY_LIMIT`, `EXTRACT_CONFIDENCE_MIN`, etc.) are module-level named constants.

### 8.4 Comments explain why, not what **(inference)**

Existing code uses docstrings on public functions; inline comments sparse — match this style.

---

## 9. Security and privacy principles

### 9.1 Secrets never in code or docs **(fact)**

- `.env` gitignored
- `/debug brain` shows key **presence**, not value
- `.env.example` uses placeholder

### 9.2 No silent exfiltration **(fact)**

Only explicit API calls to configured providers; no analytics SDKs in code.

### 9.3 Local data ownership **(fact)**

`crowley.db` is user-owned; gitignored.

---

## 10. Testing and QA principles

### 10.1 Current state **(fact)**

No committed automated test file. QA patterns observed:

- `py_compile` for syntax
- Inline Python scripts with mocks for extraction gating/apply
- Manual CLI verification

### 10.2 Recommended principles going forward **(inference)**

| Area | Minimum coverage |
|------|------------------|
| Extraction gating | Greeting, shell, question, signal message |
| `apply_state_proposals` | Confidence, dedupe, dry_run, generic filter |
| Diagnostics | No DB writes |
| Commands | Smoke test each handler |
| Provider routing | Mock `call_model`, test resolution |

### 10.3 Do not test the model **(inference)**

Gate and apply logic should be deterministic; model output tested via fixtures/mocks.

---

## 11. Versioning principles

### 11.1 Dual version labels **(fact)**

- `CROWLEY_VERSION` — `"3.9.10"`
- `CROWLEY_RELEASE_LABEL` — `"Crowley V3.9.10 Task-Frame Context"`

### 11.2 VERSIONS.md is release log **(fact)**

Shipped features documented there; `docs/` is engineering depth.

### 11.3 Phase-based V3 delivery **(fact)**

| Phase | Theme |
|-------|-------|
| 1 | Manual world model |
| 2 | Read-only diagnostics |
| 3 | Autonomous extraction |

Future phases should maintain this incremental safety pattern **(inference)**.

### 11.4 Transport layer **(fact, V3.5+)**

`app.py` must not contain business logic. New HTTP features call engine functions in `crowley.py`.

### 11.5 Memory bus **(fact, V3.7)**

External ingest writes `memory_items` only. Read APIs are read-only. Localhost trust model — no auth in MVP.

---

## 12. UX tone principles

### 12.1 Startup **(fact)**

“Go for Crowley.” / “Morning, Mr. Go.” — establishes relationship without theatrics.

### 12.2 Thinking indicator **(fact)**

`Crowley: thinking...` before streamed output — consistent across chat and diagnostics.

### 12.3 Error messages **(fact)**

Provider errors prefixed with `Crowley:` and cleared with `\r` where streaming started.

### 12.4 No spam from automation **(fact)**

Successful spark creation and extraction apply produce **no** user-visible output.

---

## 13. Decision checklist for new features

Before implementing, answer:

1. **Does conversation benefit without a new command?**
2. **Is there a gate before model/DB cost?**
3. **Is it inspectable via `/debug` or read-only command?**
4. **Can the user override manually?**
5. **Does it avoid auto-delete/archive/switch?**
6. **Does chat anti-hallucination still hold?**
7. **Are background threads using fresh DB connections?**
8. **Is scope limited to one section of `crowley.py`?**

If any answer fails for a world-model feature, redesign or defer.

---

## 14. Anti-patterns (do not introduce)

| Anti-pattern | Why |
|--------------|-----|
| Extract from assistant message alone | Violates grounding rule |
| Auto-close loops on chat inference | Destructive; user loses track |
| Write during diagnostics | Breaks read-only contract |
| Full transcript in every prompt | Unbounded tokens; use retrieval + chat window (V3.6.0) |
| User-facing extraction spam | Violates quiet default |
| Lowering confidence threshold without audit | Increases hallucinated state risk |
| Removing commands when adding automation | Commands are control surfaces |
| Importing chromadb without fallback | Heavy dep; breaks minimal install |

---

## 15. Related documents

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [PROJECT_STATE.md](./PROJECT_STATE.md)
- [ROADMAP.md](./ROADMAP.md)
- [DECISION_LOG.md](./DECISION_LOG.md)
