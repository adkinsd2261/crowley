# Crowley

**A local AI agent orchestration platform for coordinating multiple AI systems (Codex, Cursor, ChatGPT) in a unified workspace.**

Crowley is a sophisticated memory and task management system that bridges human developers, AI coding agents, architectural planners, and ChatGPT integrations. It provides a shared bus, persistent memory layer, and concurrent ticketing system to coordinate complex development workflows.

---

## What This Is

Crowley operates as the **central hub** in an AI-assisted development pipeline. Instead of juggling separate conversations with Cursor, Codex, and ChatGPT, you get:

- **Unified memory** — Shared context across all agents, with semantic retrieval
- **Ticketing board** — Track work across agents with status, priorities, and dependencies
- **Web chat interface** — Talk to Crowley directly, or integrate via REST APIs
- **Handoff system** — Structured pass-offs between planning, coding, and QA phases
- **ChatGPT integration** — Export context packets for custom GPT actions

Think of it as a **local orchestration platform** that helps you coordinate multiple AI systems toward a single goal without losing context or creating silos.

---

## Stack

- **Language:** Python 82% + JavaScript 10% (static UI)
- **Framework:** FastAPI for REST + WebSocket APIs
- **Core engine:** `crowley.py` (memory, chat, scheduling)
- **Ticketing:** Concurrent ticket system with handoff linking
- **Database:** SQLite with vector embeddings (sqlite-vec)
- **Chat models:** OpenAI, Anthropic, Ollama (pluggable)

---

## How It's Organized

```
.
├── app.py                  # FastAPI web server + endpoints
├── crowley.py              # Core engine (memory, bus, chat, retrieval)
├── tickets.py              # Ticketing board domain
├── chatgpt_actions.py      # ChatGPT custom actions router
├── diagnostics.py          # System health checks
├── requirements.txt        # Dependencies (FastAPI, pydantic, sqlite-vec, etc.)
├── .env.example            # Configuration template
├── CODEX.md                # Instructions for Codex (planning agent)
├── VERSIONS.md             # Release notes and changelog
├── static/                 # Web UI (HTML/CSS/JS)
├── scripts/                # Sync utilities (codex_sync.py, etc.)
├── docs/                   # Architecture docs
├── tests/                  # Test suite
└── tickets/                # Ticket and planning templates
```

**How it fits together:**

1. **Agent communication** — Multiple agents (Cursor, Codex, ChatGPT) submit structured handoffs via `/api/ingest`
2. **Memory layer** — Handoffs, decisions, and chat are stored, summarized, and consolidated
3. **Ticketing** — Work is tracked as tickets with parent/child relationships, blocks, and handoff links
4. **Retrieval** — Semantic search over memory returns relevant context for each agent
5. **Chat UI** — Local web interface at `http://127.0.0.1:8765` streams SSE events from Crowley

---

## Getting Started

### Requirements

- Python 3.10+
- OpenAI API key (or Ollama for local models)
- Git

### Installation

```bash
# Clone
git clone https://github.com/yourusername/crowley.git
cd crowley

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # on Windows: venv\Scripts\activate

# Install
pip install -r requirements.txt

# Copy example env and add your key
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Run

```bash
# Start the web server
python app.py
# → opens at http://127.0.0.1:8765

# Or run Crowley with terminal REPL
python crowley.py
```

### Key Endpoints

- **`GET /api/health`** — System status + version
- **`POST /api/chat`** — Stream SSE chat responses
- **`GET /api/world`** — Dashboard snapshot (memories, tickets, recent events)
- **`GET /api/tickets`** — List open tickets (with filtering)
- **`POST /api/ingest`** — Ingest handoffs from agents
- **`GET /api/portable/packet`** — Export context for ChatGPT

### Example: Chat via API

```bash
curl -X POST http://127.0.0.1:8765/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is my current project?"}'
```

---

## Key Concepts

### Memory

Crowley stores and retrieves **agent events**, **handoffs**, and **decisions** using semantic embeddings. Memory items have:
- **Type:** builder_handoff, architect_handoff, session_summary, qa_result, note
- **Source:** codex, cursor, chatgpt, manual
- **Status:** active, archived, pruned

Retrieve with `/api/retrieve?q=search_query`.

### Tickets

Work tracked on a **concurrent ticketing board** with:
- **Status:** open, claimed, in_progress, blocked, done, cancelled
- **Priorities:** 1-4 (lower = higher priority)
- **Hierarchy:** parent/child relationships for initiatives and subtasks
- **Handoff links:** Tickets can reference memory handoffs for context

### Agents

- **Codex** — Planning / architectural agent. Creates specs and decisions.
- **Cursor** — Coding agent. Implements features and runs tests.
- **ChatGPT** — External integration. Receives context packets via `/api/portable/packet`.
- **Crowley** — The coordinator. Runs the bus and serves the chat UI.

---

## Configuration

Edit `.env`:

```dotenv
# OpenAI API key (required)
OPENAI_API_KEY=sk-proj-...

# Bearer token for ChatGPT custom actions (optional)
CROWLEY_ACTION_KEY=

# Cloudflare tunnel hostname (optional, for remote access)
CLOUDFLARE_TUNNEL_HOSTNAME=crowley.yourdomain.com
```

### Using a Different Model

```bash
# At startup, the web UI lets you switch between OpenAI, Anthropic, and Ollama
# Or set via /api/brain endpoint
```

---

## Development

### Run Tests

```bash
pytest tests/
```

### Debugging

Check system health:

```bash
curl http://127.0.0.1:8765/api/health | jq
```

Stream diagnostics:

```bash
curl -N http://127.0.0.1:8765/api/diagnostics
```

### Architecture Files

- **`docs/WHERE_WE_ARE.md`** — Current project state and focus
- **`CODEX.md`** — Instructions for Codex planning phase
- **`CURSOR.md`** — Instructions for Cursor builder phase

---

## API Overview

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/health` | System status |
| `POST` | `/api/chat` | Stream chat messages |
| `GET` | `/api/world` | Dashboard data |
| `GET` | `/api/context` | Build context bundle |
| `GET` | `/api/retrieve` | Search memories |
| `GET` | `/api/messages` | Recent chat history |
| `GET` | `/api/tickets` | List tickets |
| `POST` | `/api/tickets` | Create ticket |
| `PATCH` | `/api/tickets/{id}` | Update ticket |
| `POST` | `/api/ingest` | Ingest handoff |
| `GET` | `/api/portable/packet` | ChatGPT context export |

For full docs, see the FastAPI interactive docs at `/docs` (if enabled).

---

## Contributing

Contributions are welcome! Please:

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit with clear messages
4. Push and open a PR

---

## License

Unlicensed (or add your license here).

---

## Roadmap

- [ ] Multi-project isolation and switching
- [ ] Advanced memory consolidation heuristics
- [ ] Slack integration for async notifications
- [ ] Web UI dark mode and accessibility improvements
- [ ] Distributed agent coordination (multiple machines)

---

## Support

- **Issues:** [GitHub Issues](https://github.com/adkinsd2261/crowley/issues)
- **Docs:** See `docs/` directory
- **Chat in Crowley:** `python app.py` and ask at http://127.0.0.1:8765

---

## What's Next?

- Try the web interface: `python app.py`
- Read `CODEX.md` if you're integrating a planning agent
- Check `docs/WHERE_WE_ARE.md` for current project status
