# Crowley

**An AI orchestration platform with memory-backed context retrieval. Hotswappable AI models without worrying about context windows or platform-specific memory silos.**

Crowley abstracts away model dependencies and context management. Developers integrate once, swap between OpenAI, Anthropic, Ollama, and others freely—with persistent semantic memory that survives model changes.

---

## What This Is

Crowley is a **unified context hub** for multi-agent AI workflows. Instead of rebuilding memory and context for each model or platform, you get:

- **Persistent semantic memory** — SQLite + embeddings. Decisions, handoffs, session summaries retrieved on demand without re-contexting
- **Model-agnostic chat** — Same interface to ChatGPT, Claude, or local Ollama. Switch at runtime
- **Concurrent ticketing board** — Single source of truth for multi-agent work (planning, building, QA)
- **Web dashboard** — Live memory search, ticket tracking, agent activity, world model
- **Multi-agent orchestration** — Structured handoffs between planning, coding, and QA phases
- **Context packets** — Export portable bundles for external agents or human review
- **Zero context window math** — Memory layer handles retrieval; agents get what they need

Think of it as a **local-first memory server** that lets you coordinate multiple AI systems without rebuilding context or losing institutional knowledge on model swaps.

---

## Status

**v3.9.15 (Stable — July 5, 2026)**

- **333+ unit tests** locally; GitHub Actions regression gate on `main`
- **Production ready:** web chat, memory retrieval, ticketing, multi-agent handoffs, hotswappable models
- **Architecture locked for v4:** Memory lanes and trust states planned

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
├── requirements.txt        # Dependencies
├── .env.example            # Configuration template
├── static/                 # Web UI (HTML/CSS/JS) — dashboard, memory search, tickets
├── scripts/                # Agent orchestration utilities
│   ├── codex_sync.py       # Planning agent ritual
│   ├── cursor_sync.py      # Builder agent ritual
│   ├── agent_sync_lib.py   # Shared sync library
│   └── export_portable_packet.py
├── docs/                   # Architecture and release notes
│   ├── WHERE_WE_ARE.md     # Current project state (read first)
│   ├── MEMORY_HIERARCHY.md # Authority order for facts
│   └── V3.9.15_*.md        # Release specs
├── tests/                  # Regression suite (90+ tests)
├── tickets/                # JSON templates for ticketing
├── VERSIONS.md             # Version trail
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

### Model Hotswapping

Switch between models without losing context:

```python
# All three queries share the same memory layer
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Summarize decisions", "model": "gpt-4"}'

# Later, use Claude—memory is preserved
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What was the decision?", "model": "claude-opus"}'
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
- **External models** — Via context packets or direct API integration.

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

Full interactive docs at `/docs` (if FastAPI docs enabled).

### Example: Chat with Model Selection

```bash
# Use GPT-4
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the project focus?", "model": "gpt-4"}' \
  -N

# Switch to Claude—memory persists
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What was decided?", "model": "claude-opus"}' \
  -N
```

---

## Configuration

Edit `.env`:

```dotenv
# Model provider (auto / openai / anthropic / ollama)
MODEL_PROVIDER=auto

# API keys (use what you need)
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...

# Ollama endpoint (for local models)
OLLAMA_BASE_URL=http://localhost:11434
```

At runtime, the web dashboard lets you pick between available models. Context memory is **model-agnostic**—switch freely.

---

## Multi-Agent Workflows

### Codex (Planning Agent)

```bash
# Start of session — read current context
./venv/bin/python3 scripts/codex_sync.py --before

# After planning — mint tickets
./venv/bin/python3 scripts/codex_sync.py --create-ticket \
  --title "Implement feature X" \
  --assignee cursor \
  --priority 1

# Close session with handoff
./venv/bin/python3 scripts/codex_sync.py --after \
  --summary "Planned feature X" \
  --decision "Use approach Y"
```

### Cursor (Builder Agent)

```bash
# Session start (auto-triggered by hook)
# Reads: role, context, tickets, decisions

# After shipping
./venv/bin/python3 scripts/cursor_sync.py --after --ticket <TICKET_ID> \
  --summary "Implemented feature X" \
  --qa-result "Tests pass"
```

Setup: [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md)

---

## Development

### Run Tests

```bash
CROWLEY_TEST_MODE=1 pytest tests/ -v
```

333+ tests cover memory, retrieval, ticketing, model switching, and agent sync. GitHub Actions regression gate on `main`.

### Debug Commands

```bash
# Terminal REPL
python crowley.py
/debug retrieve query   # Explain retrieval scoring
/debug consolidate      # Memory hygiene dry-run
/diagnostics            # System briefing
```

### Key Paths

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

**Current:** v3.9.15 (Stable)

- [x] Persistent semantic memory + retrieval
- [x] Model hotswapping (OpenAI, Anthropic, Ollama)
- [x] Concurrent ticketing board
- [x] Multi-agent orchestration
- [x] Web dashboard
- [x] Context packet export
- [x] CI regression gate

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
