#!/usr/bin/env bash
# Start Crowley + HTTPS tunnel for ChatGPT Custom GPT Actions.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_DIR="$ROOT/.crowley/chatgpt_bridge"
TUNNEL_LOG="$BRIDGE_DIR/tunnel.log"
PID_FILE="$BRIDGE_DIR/tunnel.pid"
MODE="${1:-}"

usage() {
  cat <<'EOF'
Usage: ./scripts/start_chatgpt_bridge.sh [--quick|--named|--ngrok]

  --quick   Cloudflare quick tunnel (default; random *.trycloudflare.com URL)
  --named   Use cloudflared/config.yml + CLOUDFLARE_TUNNEL_HOSTNAME in .env
  --ngrok   Fallback when cloudflared is unavailable (requires ngrok)

Loads .env, ensures Crowley bus, starts tunnel, patches openapi-chatgpt.deployed.json,
verifies /api/actions/* over HTTPS, prints the public URL.

Stop tunnel: kill "$(cat .crowley/chatgpt_bridge/tunnel.pid)"
EOF
}

load_env() {
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
  fi
}

require_action_key() {
  if [[ -z "${CROWLEY_ACTION_KEY:-}" ]]; then
    echo "ERROR: CROWLEY_ACTION_KEY must be set in .env" >&2
    exit 1
  fi
}

ensure_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    return 0
  fi
  if command -v brew >/dev/null 2>&1; then
    echo "Installing cloudflared via Homebrew..." >&2
    brew install cloudflared
    return 0
  fi
  return 1
}

stop_existing_tunnel() {
  if [[ -f "$PID_FILE" ]]; then
    old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      echo "Stopping previous tunnel (pid $old_pid)..." >&2
      kill "$old_pid" 2>/dev/null || true
      sleep 1
    fi
    rm -f "$PID_FILE"
  fi
}

wait_for_tunnel_url() {
  local pattern="$1"
  local url=""
  for _ in $(seq 1 45); do
    url="$(grep -Eo "$pattern" "$TUNNEL_LOG" 2>/dev/null | head -1 || true)"
    if [[ -n "$url" ]]; then
      printf '%s' "$url"
      return 0
    fi
    sleep 1
  done
  echo "ERROR: Timed out waiting for tunnel URL. See $TUNNEL_LOG" >&2
  return 1
}

start_quick_tunnel() {
  ensure_cloudflared || {
    echo "ERROR: cloudflared not installed. Run: brew install cloudflared" >&2
    exit 1
  }
  stop_existing_tunnel
  mkdir -p "$BRIDGE_DIR"
  : >"$TUNNEL_LOG"
  echo "Starting Cloudflare quick tunnel → http://127.0.0.1:8765" >&2
  cloudflared tunnel --url http://127.0.0.1:8765 >>"$TUNNEL_LOG" 2>&1 &
  echo $! >"$PID_FILE"
  wait_for_tunnel_url 'https://[a-zA-Z0-9-]+\.trycloudflare\.com'
}

start_named_tunnel() {
  ensure_cloudflared || exit 1
  local config="$ROOT/cloudflared/config.yml"
  if [[ ! -f "$config" ]]; then
    echo "ERROR: Missing $config — copy cloudflared/config.yml.example and configure." >&2
    exit 1
  fi
  if [[ -z "${CLOUDFLARE_TUNNEL_HOSTNAME:-}" ]]; then
    echo "ERROR: Set CLOUDFLARE_TUNNEL_HOSTNAME in .env for --named mode." >&2
    exit 1
  fi
  stop_existing_tunnel
  mkdir -p "$BRIDGE_DIR"
  : >"$TUNNEL_LOG"
  echo "Starting named Cloudflare tunnel (${CLOUDFLARE_TUNNEL_HOSTNAME})..." >&2
  cloudflared tunnel --config "$config" run >>"$TUNNEL_LOG" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 3
  printf 'https://%s' "${CLOUDFLARE_TUNNEL_HOSTNAME}"
}

start_ngrok_tunnel() {
  if ! command -v ngrok >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      echo "Installing ngrok via Homebrew..." >&2
      brew install ngrok/ngrok/ngrok
    else
      echo "ERROR: ngrok not installed. See https://ngrok.com/download" >&2
      exit 1
    fi
  fi
  stop_existing_tunnel
  mkdir -p "$BRIDGE_DIR"
  : >"$TUNNEL_LOG"
  echo "Starting ngrok → http://127.0.0.1:8765" >&2
  ngrok http 127.0.0.1:8765 --log=stdout >>"$TUNNEL_LOG" 2>&1 &
  echo $! >"$PID_FILE"
  local url=""
  for _ in $(seq 1 30); do
    url="$(
      curl -sf http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | "$ROOT/venv/bin/python3" -c "
import json, sys
data = json.load(sys.stdin)
for t in data.get('tunnels', []):
    u = t.get('public_url', '')
    if u.startswith('https://'):
        print(u)
        break
" 2>/dev/null || true
    )"
    if [[ -n "$url" ]]; then
      printf '%s' "$url"
      return 0
    fi
    sleep 1
  done
  echo "ERROR: Timed out waiting for ngrok URL. See $TUNNEL_LOG" >&2
  return 1
}

restart_bus_if_actions_disabled() {
  local code
  code="$(
    curl -s -o /dev/null -w '%{http_code}' \
      -H "Authorization: Bearer ${CROWLEY_ACTION_KEY}" \
      http://127.0.0.1:8765/api/actions/health || true
  )"
  if [[ "$code" == "503" ]]; then
    echo "Restarting Crowley bus to load CROWLEY_ACTION_KEY from .env..." >&2
    bus_pid="$(lsof -ti tcp:8765 2>/dev/null | head -1 || true)"
    if [[ -n "$bus_pid" ]]; then
      kill "$bus_pid" 2>/dev/null || true
      sleep 2
    fi
    bash "$ROOT/scripts/ensure_crowley_bus.sh"
  fi
}

main() {
  case "$MODE" in
    "" | --quick) MODE="quick" ;;
    --named | --ngrok) ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $MODE" >&2
      usage
      exit 1
      ;;
  esac

  load_env
  require_action_key
  mkdir -p "$BRIDGE_DIR"

  echo "Ensuring Crowley bus on 127.0.0.1:8765..."
  bash "$ROOT/scripts/ensure_crowley_bus.sh"
  restart_bus_if_actions_disabled

  "$ROOT/venv/bin/python3" "$ROOT/scripts/verify_chatgpt_actions_https.py" \
    --local-only \
    --key "${CROWLEY_ACTION_KEY}"

  local public_url=""
  case "$MODE" in
    quick)
      public_url="$(start_quick_tunnel)"
      ;;
    named)
      public_url="$(start_named_tunnel)"
      ;;
    ngrok)
      public_url="$(start_ngrok_tunnel)"
      ;;
  esac

  public_url="${public_url%/}"
  echo ""
  echo "Public URL: $public_url"

  "$ROOT/venv/bin/python3" "$ROOT/scripts/patch_openapi_chatgpt.py" --url "$public_url"

  echo ""
  "$ROOT/venv/bin/python3" "$ROOT/scripts/verify_chatgpt_actions_https.py" \
    --url "$public_url" \
    --key "${CROWLEY_ACTION_KEY}"

  echo ""
  echo "ChatGPT bridge is running."
  echo "  Tunnel PID: $(cat "$PID_FILE")"
  echo "  Tunnel log: $TUNNEL_LOG"
  echo "  OpenAPI:    openapi-chatgpt.deployed.json (import into Custom GPT)"
  echo "  Setup doc:  docs/CHATGPT_SETUP.md"
  echo ""
  echo "Stop: kill \$(cat $PID_FILE)"
}

main "$@"
