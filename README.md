# Crowley

**A production-ready AI orchestration platform. Local-first memory layer + persistent context hub for coordinating multiple AI systems (ChatGPT, Claude, Cursor, Codex) in a unified workspace.**

Crowley v3.9.15 is **stable and shipping**. It's a sophisticated memory and task management system that bridges you, AI coding agents, planning agents, and external model integrations—all communicating through a shared bus with persistent, queryable memory.

---

## What This Is

Crowley is the **central hub** in an AI-assisted development pipeline. Instead of juggling separate conversations with Cursor, Claude, and ChatGPT, you get:

- **Persistent local memory** — Semantic retrieval of decisions, handoffs, and context (SQLite + embeddings)
- **Concurrent ticketing board** — Single work board for architects and builders (Codex, Cursor, you)
- **Web chat interface** — SSE-streamed responses, live dashboard, integrated planner
- **Multi-agent bus** — Structured handoffs between planning, coding, and QA phases
- **ChatGPT integration** — Custom Actions API (bearer-authenticated) for seamless model access
- **Context packets** — Export portable context bundles for external agents or human review

Think of it as a **local-first context server** that helps you and multiple AI systems stay on the same page without losing institutional memory or creating silos.

---

## Status

**v3.9.15 (Stable — July 5, 2026)**

- **333+ unit tests** locally; GitHub Actions regression gate on `main`
- **Live production workflows:** web chat, diagnostics, memory consolidation, concurrent tickets, handoff ingestion, ChatGPT Actions API
- **Architecture locked for V4:** v4.0 Spark Lanes planned (memory lanes, trust states)

Roadmap: [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md)

---

## Stack

- **Language:** Python 84% + JavaScript 9% + CSS 5% (minimal frontend)
- **Backend:** FastAPI (REST + WebSocket) + SQLite with embeddings (sqlite-vec)
- **Memory:** Semantic embeddings (`all-MiniLM-L6-v2` or `text-embedding-3-small`), hybrid retrieval, deduplication
- **Chat models:** OpenAI, Anthropic, Ollama (pluggable via unified `call_model()` interface)
- **Tests:** Regression suite; `CROWLEY_TEST_MODE=1` for isolated DB

---

## How It's Organized

```
.
├── crowley.py              # Core engine (memory, bus, chat, retrieval, world model)
├── app.py                  # FastAPI web server + SSE endpoints
├── tickets.py              # Ticketing domain (mint, claim, complete)
├── diagnostics.py          # System health and briefing
├── chatgpt_actions.py      # ChatGPT custom actions router (bearer auth)
├── requirements.txt        # Dependencies
├── .env.example            # Configuration template
├── static/                 # Web UI (HTML/CSS/JS) — chat, dashboard, inspector
├── scripts/                # Agent orchestration utilities
│   ├── codex_sync.py       # Planning agent ritual (--before / --after)
│   ├── cursor_sync.py      # Builder agent ritual (hooks + --after)
│   ├── agent_sync_lib.py   # Shared sync library
│   ├── export_portable_packet.py
│   └── start_chatgpt_bridge.sh
├── docs/                   # Architecture and release notes
│   ├── WHERE_WE_ARE.md     # Current project state (read first)
│   ├── MEMORY_HIERARCHY.md # Authority order for facts
│   ├── CHATGPT_SETUP.md    # Custom GPT + tunnel setup
│   └── V3.9.15_*.md        # Release specs
├── tests/                  # Regression suite (90+ tests)
├── tickets/                # JSON templates for `--create-tickets`
├── CODEX.md                # Codex agent ritual
├── CURSOR.md               # Cursor agent ritual (hooks setup)
├── VERSIONS.md             # Complete version trail
└── .github/workflows/tests.yml  # CI regression gate
```

**How it fits together:**

1. **You chat** at `http://127.0.0.1:8765` or via REST API (`/api/chat`)
2. **Memory layer** stores decisions, handoffs, and session summaries; retrieves on demand
3. **Ticketing** tracks work across agents with status, priorities, and dependencies
4. **Agent handoffs** (Cursor, Codex) sync state via `scripts/*.py --before / --after`
5. **World model** tracks project phase, focus, risks, and next actions
6. **ChatGPT integration** exports context packets and runs `/api/actions/*` endpoints

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

# Or run Crowley with terminal REPL
python crowley.py
```

### First Steps

1. **Web UI** (recommended): `python app.py` → click the link, start chatting
2. **Terminal REPL**: `python crowley.py` → type messages, press Enter
3. **Read the state**: Visit http://127.0.0.1:8765 → Intelligence drawer shows memory, tickets, decisions
4. **Onboarding**: See [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md) for agent setup

---

## Key Concepts

### Memory

Crowley stores and retrieves **handoffs**, **decisions**, and **session summaries** using semantic embeddings. Memory items have:

- **Type:** architect_handoff, builder_handoff, session_summary, qa_result, note, canon
- **Source:** codex, cursor, crowley, manual
- **Status:** active, archived, pruned

Retrieve with `/api/retrieve?q=search_query` or search in the Memory tab.

**Authority order:** filesystem (`VERSIONS.md`, `docs/WHERE_WE_ARE.md`) → live DB state → agent activity → tickets → pinned canon → retrieval.

### Tickets

Work tracked on a **concurrent ticketing board** with:

- **Status:** open, claimed, in_progress, blocked, done, cancelled
- **Priority:** 1–4 (lower = higher)
- **Hierarchy:** parent/child relationships (initiatives → subtasks)
- **Handoff links:** Tickets reference memory handoffs for context

Created by Codex, claimed by Cursor, visible in the Intelligence drawer.

### Agents

- **Codex** — Planning agent. Mints tickets, posts architect handoffs, sets direction.
- **Cursor** — Builder agent. Claims tickets, implements, posts builder handoffs on completion.
- **You** — Operator. Chat with Crowley; approve decisions; run orchestration scripts.
- **ChatGPT (Custom Actions)** — External integration. Receives context packets via `/api/actions/context`.

Setup rituals: [CODEX.md](./CODEX.md) · [CURSOR.md](./CURSOR.md)

---

## API Overview

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/chat` | Stream chat responses (SSE) |
| `GET` | `/api/health` | System status + version |
| `GET` | `/api/world` | Dashboard snapshot (memory, tickets, activity) |
| `GET` | `/api/tickets` | List tickets (with filtering) |
| `POST` | `/api/tickets` | Create ticket |
| `PATCH` | `/api/tickets/{id}` | Update ticket |
| `GET` | `/api/retrieve` | Search memories (hybrid semantic + keyword) |
| `POST` | `/api/ingest` | Ingest handoffs from agents |
| `GET` | `/api/context` | Build context bundle (world + memory + tickets) |
| `GET` | `/api/portable/packet` | Export context for external agents |
| `GET` | `/api/agent/sync` | Agent activity feed (last contact, recent events) |
| `GET` | `/api/actions/*` | ChatGPT custom actions (bearer auth) |

Full interactive docs at `/docs` (if FastAPI docs enabled).

### Example: Chat via API

```bash
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the current project focus?"}' \
  -N  # Stream
```

---

## Configuration

Edit `.env`:

```dotenv
# OpenAI API key (required for OpenAI models)
OPENAI_API_KEY=sk-proj-...

# Model provider (auto / openai / anthropic / ollama)
MODEL_PROVIDER=auto

# Bearer token for ChatGPT custom actions (optional)
CROWLEY_ACTION_KEY=your-secret-key

# Cloudflare tunnel hostname (optional, for remote access)
CLOUDFLARE_TUNNEL_HOSTNAME=crowley.yourdomain.com

# GitHub token for git.* tools in ChatGPT Actions (optional)
CROWLEY_GITHUB_TOKEN=ghp_...
```

### Switching Models

The web UI and `POST /api/brain` endpoint let you switch between OpenAI, Anthropic, and Ollama at runtime. See [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md) § 4 for agent-specific setup.

---

## Multi-Agent Workflows

### Codex (Planning Agent)

```bash
# Start of session — read context
./venv/bin/python3 scripts/codex_sync.py --before

# After planning — mint tickets and close session
./venv/bin/python3 scripts/codex_sync.py --create-ticket \
  --title "Implement feature X" \
  --assignee cursor \
  --priority 1 \
  --description "Spec: ..." \
  --acceptance "Passes test suite"

./venv/bin/python3 scripts/codex_sync.py --after \
  --summary "Planned feature X" \
  --next-action "Cursor implements" \
  --decision "Use approach Y"
```

### Cursor (Builder Agent)

```bash
# Session start (auto-triggered by hook)
# Reads: your role, last contact, tickets, decisions

# After shipping
./venv/bin/python3 scripts/cursor_sync.py --after --ticket <TICKET_ID> \
  --summary "Implemented feature X" \
  --next-action "Codex reviews; merge" \
  --qa-result "Tests pass; manual QA: ✓"
```

Setup: [CODEX.md](./CODEX.md) · [CURSOR.md](./CURSOR.md) · [docs/V3.9.3_PLANNING_WORKFLOW.md](./docs/V3.9.3_PLANNING_WORKFLOW.md)

---

## ChatGPT Integration

Crowley exposes a bearer-authenticated `/api/actions/*` endpoint for custom ChatGPT actions.

**Setup:**

1. Generate OpenAPI schema: `scripts/start_chatgpt_bridge.sh --named`
2. Deploy with Cloudflare tunnel or ngrok: `scripts/start_chatgpt_bridge.sh`
3. Import schema into Custom GPT builder
4. Set bearer token in Custom GPT Actions config

**Features:** Query memory, list tickets, create notes, retrieve context, read GitHub.

Docs: [CHATGPT_SETUP.md](./docs/CHATGPT_SETUP.md) · [docs/V3.9.13_SECURE_CHATGPT_ACTIONS_API.md](./docs/V3.9.13_SECURE_CHATGPT_ACTIONS_API.md)

---

## Development

### Run Tests

```bash
CROWLEY_TEST_MODE=1 pytest tests/ -v
# or
./venv/bin/python3 -m unittest discover -s tests -q
```

333+ tests cover memory, tickets, agent sync, diagnostics, and chat behavior. GitHub Actions regression gate on `main`.

### Debug Commands

```bash
# Terminal REPL
python crowley.py
/debug prompt           # Show system prompt + context
/debug retrieve query   # Explain retrieval scoring
/debug consolidate type # Memory hygiene dry-run
/diagnostics            # System briefing

# Web API
curl http://127.0.0.1:8765/api/health | jq
curl -N http://127.0.0.1:8765/api/diagnostics  # Stream briefing
```

### Key Paths

- `crowley.py` — Core engine
- `app.py` — FastAPI transport
- `tickets.py` — Ticketing domain
- `diagnostics.py` — System health
- `docs/WHERE_WE_ARE.md` — Current state (read first)
- `docs/MEMORY_HIERARCHY.md` — Authority order for facts
- `.github/workflows/tests.yml` — CI regression gate

---

## Contributing

Contributions are welcome! Please:

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

- [x] Persistent memory + semantic retrieval
- [x] Concurrent ticketing board
- [x] Multi-agent orchestration (Codex, Cursor)
- [x] ChatGPT custom actions API
- [x] Web UI with live dashboard
- [x] Portable context packets
- [x] CI regression gate on GitHub Actions

**Next:** v4.0 Spark Lanes

- [ ] Memory lanes (narrative threads)
- [ ] Trust states (confidence levels)
- [ ] Lane-aware retrieval
- [ ] Distributed agent coordination

---

## Getting Help

- **Docs:** [docs/](./docs/) — Architecture, release notes, setup guides
- **Where we are:** [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md) — State and roadmap (start here)
- **Issues:** [GitHub Issues](https://github.com/adkinsd2261/crowley/issues)
- **Chat in Crowley:** `python app.py` → web UI at http://127.0.0.1:8765

---

## What's Next?

1. **Run the web interface:** `python app.py` (no terminal needed)
2. **Chat with Crowley:** Ask about the project; explore memory, tickets, and decisions in the Intelligence drawer
3. **Read current state:** [docs/WHERE_WE_ARE.md](./docs/WHERE_WE_ARE.md) — Version history, agent setup, what's shipping
4. **Integrate an agent:** Follow [CODEX.md](./CODEX.md) or [CURSOR.md](./CURSOR.md) for Cursor/Codex setup
5. **Explore the API:** See `/docs` endpoint or read the API table above
