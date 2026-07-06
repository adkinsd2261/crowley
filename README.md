# Crowley

**An AI orchestration platform with memory-backed context retrieval. Hotswappable AI models without worrying about context windows or platform-specific memory silos.**

Crowley abstracts away model dependencies and context management. Developers integrate once, swap between OpenAI, Anthropic, Ollama, and others freely—with persistent semantic memory that survives model changes.

**v3.9.18 (Stable — July 6, 2026)** enforces agent retrieval at the Actions gateway: handoff→ticket persistence, pre-response gating, domain triggers, and structured observability.

---

## What This Is

Crowley is a **unified context hub** for multi-agent AI workflows. Instead of rebuilding memory and context for each model or platform, you get:

- **Persistent semantic memory** — SQLite + embeddings. Decisions, handoffs, session summaries retrieved on demand without re-contexting
- **Model-agnostic chat** — Same interface to ChatGPT, Claude, or local Ollama. Switch at runtime
- **Concurrent ticketing board** — Single source of truth for multi-agent work (planning, building, QA)
- **Web dashboard** — Live memory search, ticket tracking, agent activity, world model
- **Multi-agent orchestration** — Structured handoffs between planning, coding, and QA phases
- **ChatGPT hybrid Actions gateway** — Bearer-authenticated read/write tool dispatch with boot-sequence enforcement
- **Workflow enforcement (V3.9.16+)** — Boot gate, truth hierarchy, core tool tiers, structured builder handoffs
- **Trust & control (V3.9.17)** — Write attribution, permissions, audit/rollback, memory tiers, conflict resolution
- **Agent retrieval enforcement (V3.9.18)** — Gateway gating, domain triggers, handoff→ticket bridge, proactive chaining
- **Context packets** — Export portable bundles for external agents or human review
- **Zero context window math** — Memory layer handles retrieval; agents get what they need

Think of it as a **local-first memory server** that lets you coordinate multiple AI systems without rebuilding context or losing institutional knowledge on model swaps.

---

## Status

**v3.9.18 (Stable — July 6, 2026)**

- **430 unit tests** locally; GitHub Actions regression gate on `main`
- **Retrieval enforcement:** pre-response gating, domain triggers, proactive chaining on complex queries
- **Handoff persistence:** completed handoffs auto-create durable done tickets
- **Trust & control (V3.9.17):** write attribution, permissions, audit, memory tiers, conflict resolution
- **Production ready:** web chat, memory retrieval, ticketing, multi-agent handoffs, ChatGPT Actions API

Release spec: [docs/V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md](./docs/V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md)

Roadmap: [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md)

---

## Stack

- **Language:** Python 84% + JavaScript 9% + CSS 5% (minimal frontend)
- **Backend:** FastAPI (REST + WebSocket) + SQLite with embeddings (sqlite-vec)
- **Memory:** Semantic embeddings (`all-MiniLM-L6-v2` or `text-embedding-3-small`), hybrid retrieval, deduplication
- **Models:** OpenAI, Anthropic, Ollama (pluggable via unified interface; swap at runtime)
- **Testing:** Regression suite; `CROWLEY_TEST_MODE=1` for isolated DB

---

## How It's Organized

```
.
├── crowley.py              # Core engine (memory, retrieval, chat, ticketing)
├── app.py                  # FastAPI server + SSE endpoints
├── tickets.py              # Ticketing domain (mint, claim, complete)
├── diagnostics.py          # System health and briefing
├── chatgpt_actions.py      # ChatGPT Actions gateway (bearer auth + boot gate)
├── workflow.py             # V3.9.16+ workflow enforcement (boot, truth hierarchy, core tools)
├── agent_identity.py       # V3.9.17 write attribution + permissions
├── write_audit.py          # V3.9.17 append-only audit + rollback
├── memory_tiers.py         # V3.9.17 memory tiers, promotion, decay
├── conflict_engine.py      # V3.9.17 conflict detection + resolution
├── handoff_ticket_bridge.py # V3.9.18 handoff → ticket persistence
├── agent_behavior.py       # V3.9.17+ retrieval policy, gating, observability
├── requirements.txt        # Dependencies
├── .env.example            # Configuration template
├── static/                 # Web UI (HTML/CSS/JS) — dashboard, memory search, tickets
├── scripts/                # Agent orchestration utilities
│   ├── codex_sync.py       # Planning agent ritual (--before / --after)
│   ├── cursor_sync.py      # Builder agent ritual (hooks + --after + QA handoff fields)
│   ├── agent_sync_lib.py   # Shared sync library
│   ├── validate_workflow_e2e.py  # E2E workflow validation
│   ├── export_portable_packet.py
│   └── start_chatgpt_bridge.sh
├── docs/                   # Architecture and release notes
│   ├── WHERE_WE_ARE.md     # Current project state (read first)
│   ├── MEMORY_HIERARCHY.md # Authority order for facts
│   ├── CHATGPT_SETUP.md    # Custom GPT + tunnel setup
│   └── V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md  # Latest release spec
├── tests/                  # Regression suite (430 tests)
├── tickets/                # JSON templates for `--create-tickets`
├── CODEX.md                # Codex agent ritual
├── CURSOR.md               # Cursor agent ritual (hooks setup)
├── VERSIONS.md             # Complete version trail
└── .github/workflows/tests.yml  # CI regression gate
```

**How it works:**

1. **You (or an agent) chat** at `http://127.0.0.1:8765` or via `/api/chat`
2. **Memory layer** stores handoffs, decisions, summaries; retrieves semantically on demand
3. **Ticketing** tracks work across agents with status, priority, and dependencies
4. **Model picker** — Switch between OpenAI, Anthropic, Ollama at runtime; memory persists
5. **Agent handoffs** — Structured sync points let Codex (planner) and Cursor (builder) exchange context without silos

---

## Quick Start

### Requirements

- Python 3.10+
- OpenAI API key (or Ollama for local models)
- Git

### Installation

```bash
# Clone
git clone https://github.com/adkinsd2261/crowley.git
cd crowley

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # on Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure env
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY (or use Ollama)
```

### Run

```bash
# Start the web server
python app.py
# → opens at http://127.0.0.1:8765

# Or use the terminal REPL
python crowley.py
```

### First Steps

1. **Web dashboard** (recommended): `python app.py` → click the link, start chatting
2. **Switch models:** Use the model picker in the dashboard or set `MODEL_PROVIDER` in `.env`
3. **Explore memory:** Visit http://127.0.0.1:8765 → Memory tab shows decisions, handoffs, summaries
4. **View tickets:** Ticketing tab shows work items, priorities, agent assignments
5. **Read docs:** [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md) for agent setup and workflows

---

## Key Concepts

### Memory

Crowley stores and retrieves **decisions**, **handoffs**, and **summaries** using semantic embeddings:

- **Type:** architect_handoff, builder_handoff, session_summary, qa_result, note, canon
- **Source:** codex, cursor, crowley, manual
- **Status:** active, archived, pruned

Retrieve with `/api/retrieve?q=search_query` or search in the Memory tab. Memory survives model changes.

**Authority order:** filesystem → tickets → agent activity → live DB state → pinned canon → retrieval. For *what changed* / *what now*, agent activity beats stale project state and memory.

### Model Hotswapping

Switch between models without losing context:

```bash
# Use GPT-4
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Summarize decisions", "model": "gpt-4"}' \
  -N

# Switch to Claude—memory is preserved
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What was the decision?", "model": "claude-opus"}' \
  -N
```

Both queries access the same semantic memory without re-indexing or reprocessing.

### Ticketing

Concurrent work board with:

- **Status:** open, claimed, in_progress, blocked, done, cancelled
- **Priority:** 1–4 (lower = higher)
- **Hierarchy:** parent/child relationships (epics → tasks)
- **Handoff links:** Tickets reference memory for context

Created by Codex, claimed by Cursor, visible on the dashboard.

### Agents

- **Codex** — Planning agent. Mints tickets, posts decisions, sets direction.
- **Cursor** — Builder agent. Claims tickets, implements, posts completion handoffs.
- **You** — Operator. Chat with Crowley; approve decisions; run orchestration.
- **ChatGPT (Custom Actions)** — External integration via hybrid `/api/actions/*` gateway.

Setup: [CODEX.md](./CODEX.md) · [CURSOR.md](./CURSOR.md)

---

## API Overview

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/chat` | Chat (SSE stream) with model selection |
| `GET` | `/api/health` | System status + version |
| `GET` | `/api/world` | Dashboard snapshot (memory, tickets, activity) |
| `GET` | `/api/tickets` | List tickets (with filtering) |
| `POST` | `/api/tickets` | Create ticket |
| `PATCH` | `/api/tickets/{id}` | Update ticket |
| `GET` | `/api/retrieve` | Search memories (semantic + keyword) |
| `POST` | `/api/ingest` | Ingest handoffs from agents |
| `GET` | `/api/context` | Build context bundle (world + memory + tickets) |
| `GET` | `/api/portable/packet` | Export context for external agents |
| `GET` | `/api/agent/sync` | Agent activity feed |
| `GET/POST` | `/api/actions/*` | ChatGPT hybrid Actions gateway (bearer auth) |

Full interactive docs at `/docs` (if FastAPI docs enabled).

---

## Configuration

Edit `.env`:

```dotenv
# Model provider (auto / openai / anthropic / ollama)
MODEL_PROVIDER=auto

# API keys (use what you need)
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...

# Bearer token for ChatGPT custom actions (optional)
CROWLEY_ACTION_KEY=your-secret-key

# GitHub token for github.* tools in ChatGPT Actions (optional)
CROWLEY_GITHUB_TOKEN=ghp_...

# Ollama endpoint (for local models)
OLLAMA_BASE_URL=http://localhost:11434
```

At runtime, the web dashboard lets you pick between available models. Context memory is **model-agnostic**—switch freely.

---

## Multi-Agent Workflows

### Codex (Planning Agent)

```bash
./venv/bin/python3 scripts/codex_sync.py --before

./venv/bin/python3 scripts/codex_sync.py --create-ticket \
  --title "Implement feature X" \
  --assignee cursor \
  --priority 1

./venv/bin/python3 scripts/codex_sync.py --after \
  --summary "Planned feature X" \
  --decision "Use approach Y"
```

### Cursor (Builder Agent)

```bash
# Session start (auto-triggered by hook)

./venv/bin/python3 scripts/cursor_sync.py --after --ticket <TICKET_ID> \
  --summary "Implemented feature X" \
  --next-action "Codex reviews; merge" \
  --qa-result "Tests pass; manual QA: ✓" \
  --confidence high \
  --context-basis "agent.sync via --before; ticket #N; git diff"
```

Setup: [docs/V3.9.3_PLANNING_WORKFLOW.md](./docs/V3.9.3_PLANNING_WORKFLOW.md)

---

## ChatGPT Integration

Crowley exposes a bearer-authenticated `/api/actions/*` **hybrid gateway**: `GET /catalog`, `POST /read`, `POST /write` dispatch to an internal tool registry.

**Fresh session rule (V3.9.16+):** Call `agent.sync` before other tools, or the gateway returns `428 boot_required`.

**Setup:**

1. Start bridge: `scripts/start_chatgpt_bridge.sh --named` (or `--ngrok`)
2. Import `openapi-chatgpt.deployed.json` into Custom GPT builder
3. Set bearer token (`CROWLEY_ACTION_KEY`) in Custom GPT Actions config
4. Test: *"Call actionsHealth, then actionsRead with tool agent.sync"*

**Core tools:** `agent.sync`, `context.get`, `memory.*`, `ticket.*`, `handoff.ingest`, `note.ingest` — see `/api/actions/catalog` for full list with `core` / `secondary` tiers.

Docs: [CHATGPT_SETUP.md](./docs/CHATGPT_SETUP.md) · [docs/V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md](./docs/V3.9.18_AGENT_RETRIEVAL_ENFORCEMENT.md)

---

## Development

### Run Tests

```bash
CROWLEY_TEST_MODE=1 pytest tests/ -v
# or
./venv/bin/python3 -m unittest discover -s tests -q
```

430 tests cover memory, retrieval, ticketing, agent sync, workflow enforcement, trust layers, and V3.9.18 retrieval gating. GitHub Actions regression gate on `main`.

Validate workflow end-to-end:

```bash
./venv/bin/python3 scripts/validate_workflow_e2e.py
```

### Debug Commands

```bash
python crowley.py
/debug retrieve query   # Explain retrieval scoring
/debug consolidate      # Memory hygiene dry-run
/diagnostics            # System briefing
```

### Key Paths

- `workflow.py` — V3.9.16+ workflow enforcement
- `agent_behavior.py` — V3.9.17 agent retrieval policy and observability
- `crowley.py` — Core engine (memory, retrieval, chat)
- `app.py` — FastAPI transport
- `tickets.py` — Ticketing domain
- `docs/WHERE_WE_ARE.md` — Current state
- `.github/workflows/tests.yml` — CI regression gate

---

## Contributing

Contributions are welcome:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Add tests for new functionality
4. Run `pytest tests/ -v` locally (with `CROWLEY_TEST_MODE=1`)
5. Commit with clear messages
6. Push and open a PR

---

## License

Unlicensed (or add your license here).

---

## Roadmap

**Current:** v3.9.18 (Stable)

- [x] Persistent semantic memory + retrieval
- [x] Model hotswapping (OpenAI, Anthropic, Ollama)
- [x] Concurrent ticketing board
- [x] Multi-agent orchestration (Codex, Cursor)
- [x] ChatGPT hybrid Actions gateway + boot gate
- [x] Workflow enforcement (truth hierarchy, QA handoff schema)
- [x] Web dashboard
- [x] Context packet export
- [x] CI regression gate on GitHub Actions

**Next:** v4.0 Spark Lanes

- [ ] Memory lanes (narrative threads)
- [ ] Trust states (confidence scoring)
- [ ] Lane-aware retrieval
- [ ] Distributed agent coordination

---

## Getting Help

- **Docs:** [docs/](./docs/) — Architecture, setup guides
- **Current state:** [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md) — Version history, roadmap
- **Issues:** [GitHub Issues](https://github.com/adkinsd2261/crowley/issues)
- **Chat in Crowley:** `python app.py` → http://127.0.0.1:8765

---

## What's Next?

1. **Run the web interface:** `python app.py`
2. **Explore memory:** Dashboard Memory tab shows decisions and context
3. **Switch models:** Use the model picker to try different AI providers
4. **Check tickets:** View and manage work items on the Ticketing tab
5. **Read current state:** [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md)
