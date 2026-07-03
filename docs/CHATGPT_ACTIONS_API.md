# ChatGPT Actions API — Crowley V3.9.13

**Status:** Shipped (2026-07-03) · tunnel and Custom GPT setup are operator steps (not configured by default)

Crowley V3.9.13 adds a **narrow, bearer-authenticated** `/api/actions/*` surface for ChatGPT Custom GPT Actions. It reuses the V3.9.12 portable context terminal engine but does **not** expose the full internal API.

---

## Purpose

- Let a Custom GPT read Crowley context and memories over HTTPS (via tunnel)
- Export the portable context packet at session start
- Validate and stage terminal writebacks at session end
- Keep localhost UI, chat, tickets, brain switching, and internal routes unchanged

**Do not** point a Custom GPT at the full `/api/*` tree. Use only `/api/actions/*`.

---

## Security model

| Layer | Behavior |
|-------|----------|
| Bind address | Crowley stays on `127.0.0.1:8765` by default — not `0.0.0.0` |
| Actions auth | `Authorization: Bearer <CROWLEY_ACTION_KEY>` on every `/api/actions/*` route |
| Key storage | `CROWLEY_ACTION_KEY` env var on the Crowley host only |
| Missing key | `/api/actions/*` returns **503** with `actions_api_disabled` — no silent open access |
| Bad/missing auth | **401** with structured error (never logs or returns the secret) |
| Token compare | `hmac.compare_digest` |
| Public health | `GET /api/health` remains public (local UI / preflight) |

### Excluded from Actions API

Ticket mutation, task mutation, brain switching, chat/messages, memory-item listing, diagnostics, ingest of arbitrary handoffs, and agent sync are **not** exposed.

Writeback ingest uses `ingest_terminal_writeback()` — session receipt + **staged** spark candidates only.

---

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `CROWLEY_ACTION_KEY` | Yes (for Actions) | Bearer token shared with Custom GPT Action auth |
| `CROWLEY_TEST_MODE` | Optional | Test/stub mode (CI and local tests) |
| `OPENAI_API_KEY` | Optional | Unrelated to Actions auth; used by Crowley chat |

Example (`.env` — never commit):

```bash
CROWLEY_ACTION_KEY=replace-with-long-random-secret
```

See `.env.example`.

---

## Local run

```bash
export CROWLEY_ACTION_KEY="test-secret"
./venv/bin/python3 app.py
```

In another terminal:

```bash
# Unauthorized — no key configured on server
unset CROWLEY_ACTION_KEY
curl -i http://127.0.0.1:8765/api/actions/health

# Re-start app with key set, then authorized:
export CROWLEY_ACTION_KEY="test-secret"
curl -i -H "Authorization: Bearer test-secret" \
  http://127.0.0.1:8765/api/actions/health

curl -i -H "Authorization: Bearer test-secret" \
  "http://127.0.0.1:8765/api/actions/retrieve?q=current%20project%20state&limit=5"

curl -i -X POST \
  -H "Authorization: Bearer test-secret" \
  -H "Content-Type: application/json" \
  http://127.0.0.1:8765/api/actions/writeback/parse \
  -d '{"writeback":{"session":{"summary":"Test ChatGPT Actions parse.","surface":"chatgpt","model":"test"},"sparks":[]}}'
```

Wrong token (expect 401):

```bash
curl -i -H "Authorization: Bearer wrong" \
  http://127.0.0.1:8765/api/actions/health
```

Local UI health (no auth, unchanged):

```bash
curl -i http://127.0.0.1:8765/api/health
```

---

## Cloudflare Tunnel notes

Crowley should remain bound to localhost. Expose it with a tunnel, not `0.0.0.0`.

**Operator setup:** see [CHATGPT_SETUP.md](./CHATGPT_SETUP.md) and run:

```bash
./scripts/start_chatgpt_bridge.sh
```

Named tunnel template: `cloudflared/config.yml.example`

**Not auto-configured in-repo** — you start the bridge when ready.

---

## Custom GPT setup

Full walkthrough: **[CHATGPT_SETUP.md](./CHATGPT_SETUP.md)**

Quick start:

```bash
./scripts/start_chatgpt_bridge.sh
```

Then import **`openapi-chatgpt.deployed.json`** into the Custom GPT Action editor.

### Recommended Custom GPT instructions (snippet)

```
You are a Crowley terminal. At session start, call actionsPortablePacket or actionsContext to load truth.
Use actionsRetrieve for targeted memory lookup only when needed.
At session end, build structured writeback JSON per the packet contract, call actionsWritebackParse, then actionsWritebackIngest on success.
Never invent project version, ticket state, or memory facts — read them from Crowley first.
Do not call routes outside /api/actions/*.
```

---

## Actions routes

| Method | Path | Wraps |
|--------|------|-------|
| GET | `/api/actions/health` | Auth check + safe runtime |
| GET | `/api/actions/context` | `build_context_bundle()` |
| GET | `/api/actions/retrieve` | `retrieve_memories_api()` |
| GET | `/api/actions/portable/packet` | `build_portable_context_packet(surface="chatgpt")` + markdown |
| POST | `/api/actions/writeback/parse` | `parse_terminal_writeback()` |
| POST | `/api/actions/writeback/ingest` | `ingest_terminal_writeback()` |

OpenAPI: [`openapi-chatgpt.json`](../openapi-chatgpt.json)

---

## Known limitations

- No OAuth — single shared bearer secret
- No rate limiting on Actions routes (localhost-first)
- Tunnel / Custom GPT / Cloudflare not auto-configured
- Writeback sparks remain **candidates** until promoted through existing Crowley workflows
- Actions packet surface is fixed to `chatgpt` (local `/api/portable/packet` still accepts `surface` param)

---

## Warning

**Do not expose the full Crowley `/api/*` surface to the public internet or Custom GPT Actions.** The Actions API is intentionally minimal. Internal routes can mutate tickets, tasks, brain config, and chat history without the Actions bearer gate.
