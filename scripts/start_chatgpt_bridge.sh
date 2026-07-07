#!/usr/bin/env bash
# Start Crowley + HTTPS tunnel for ChatGPT Custom GPT Actions.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_DIR="$ROOT/.crowley/chatgpt_bridge"
TUNNEL_LOG="$BRIDGE_DIR/tunnel.log"
PID_FILE="$BRIDGE_DIR/tunnel.pid"
MODE="${1:-}"
PY="$ROOT/venv/bin/python3"
LIB="$ROOT/scripts/chatgpt_bridge_lib.py"

usage() {
  cat <<'EOF'
Usage: ./scripts/start_chatgpt_bridge.sh [--named|--quick|--ngrok]

  --named   Stable hostname via cloudflared/config.yml; prefers durable LaunchAgent (default)
  --quick   Cloudflare quick tunnel (random *.trycloudflare.com URL; explicit opt-in)
  --ngrok   Fallback when cloudflared is unavailable (requires ngrok)

Loads .env, ensures Crowley bus, checks local Actions auth, starts or reuses tunnel,
patches openapi-chatgpt.deployed.json, verifies /api/actions/* over HTTPS.

Named production: use ./scripts/crowley_bridge_service.py install for durable connector.

Stop foreground tunnel: kill "$(cat .crowley/chatgpt_bridge/tunnel.pid)"
EOF
}

fail() {
  local category="$1"
  local message="$2"
  local inspect="$3"
  echo "ERROR [$category]: $message" >&2
  echo "Inspect: $inspect" >&2
  exit 1
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
    fail "missing_key" "CROWLEY_ACTION_KEY must be set in .env" ".env and Custom GPT bearer auth"
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

cleanup_stale_pid() {
  "$PY" -c "
import sys
from pathlib import Path
sys.path.insert(0, '${ROOT}/scripts')
import chatgpt_bridge_lib as lib
pid_file = Path('${PID_FILE}')
if lib.cleanup_stale_pid_file(pid_file):
    print(f'Removed stale tunnel PID file ({pid_file}).', file=sys.stderr)
"
}

stop_existing_tunnel() {
  cleanup_stale_pid
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

verify_tunnel_pid_alive() {
  if [[ ! -f "$PID_FILE" ]]; then
    fail "no_connector" "Tunnel PID file missing after start" "cloudflared log $TUNNEL_LOG"
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    fail "stale_pid" "Tunnel process $pid exited immediately" "cloudflared log $TUNNEL_LOG"
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
  fail "tunnel_not_ready" "Timed out waiting for tunnel URL" "log $TUNNEL_LOG, DNS, cloudflared connector"
}

start_quick_tunnel() {
  ensure_cloudflared || fail "cloudflared_missing" "cloudflared not installed" "brew install cloudflared"
  stop_existing_tunnel
  mkdir -p "$BRIDGE_DIR"
  : >"$TUNNEL_LOG"
  echo "Starting Cloudflare quick tunnel → http://127.0.0.1:8765" >&2
  cloudflared tunnel --url http://127.0.0.1:8765 >>"$TUNNEL_LOG" 2>&1 &
  echo $! >"$PID_FILE"
  verify_tunnel_pid_alive
  wait_for_tunnel_url 'https://[a-zA-Z0-9-]+\.trycloudflare\.com'
}

named_service_running() {
  local code
  code="$("$PY" "$ROOT/scripts/crowley_bridge_service.py" status >/dev/null 2>&1; echo $?)"
  [[ "$code" == "0" ]]
}

start_named_tunnel() {
  ensure_cloudflared || fail "cloudflared_missing" "cloudflared not installed" "brew install cloudflared"
  local config="$ROOT/cloudflared/config.yml"
  if [[ ! -f "$config" ]]; then
    fail "missing_config" "Missing $config" "copy cloudflared/config.yml.example and configure"
  fi
  if [[ -z "${CLOUDFLARE_TUNNEL_HOSTNAME:-}" ]]; then
    fail "missing_hostname" "Set CLOUDFLARE_TUNNEL_HOSTNAME in .env for --named" ".env"
  fi

  if named_service_running; then
    echo "Durable LaunchAgent connector already running — reusing ${CLOUDFLARE_TUNNEL_HOSTNAME}" >&2
    "$PY" -c "import sys; sys.path.insert(0, '$ROOT/scripts'); import chatgpt_bridge_lib as l; l.cleanup_duplicate_connectors()" >/dev/null 2>&1 || true
    printf 'https://%s' "${CLOUDFLARE_TUNNEL_HOSTNAME}"
    return 0
  fi

  if "$PY" -c "import sys; sys.path.insert(0, '$ROOT/scripts'); import chatgpt_bridge_lib as l; raise SystemExit(0 if l.connector_process_running() else 1)"; then
    echo "Named cloudflared connector already running — reusing ${CLOUDFLARE_TUNNEL_HOSTNAME}" >&2
    "$PY" -c "import sys; sys.path.insert(0, '$ROOT/scripts'); import chatgpt_bridge_lib as l; l.cleanup_duplicate_connectors()" >/dev/null 2>&1 || true
    printf 'https://%s' "${CLOUDFLARE_TUNNEL_HOSTNAME}"
    return 0
  fi

  echo "Tip: for durable named bridge use ./scripts/crowley_bridge_service.py install" >&2
  "$PY" -c "import sys; sys.path.insert(0, '$ROOT/scripts'); import chatgpt_bridge_lib as l; l.cleanup_duplicate_connectors()" >/dev/null 2>&1 || true
  stop_existing_tunnel
  mkdir -p "$BRIDGE_DIR"
  : >"$TUNNEL_LOG"
  echo "Starting named Cloudflare tunnel (${CLOUDFLARE_TUNNEL_HOSTNAME}) in background..." >&2
  cloudflared tunnel --config "$config" run >>"$TUNNEL_LOG" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 3
  verify_tunnel_pid_alive
  printf 'https://%s' "${CLOUDFLARE_TUNNEL_HOSTNAME}"
}

start_ngrok_tunnel() {
  if ! command -v ngrok >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      echo "Installing ngrok via Homebrew..." >&2
      brew install ngrok/ngrok/ngrok
    else
      fail "ngrok_missing" "ngrok not installed" "https://ngrok.com/download"
    fi
  fi
  stop_existing_tunnel
  mkdir -p "$BRIDGE_DIR"
  : >"$TUNNEL_LOG"
  echo "Starting ngrok → http://127.0.0.1:8765" >&2
  ngrok http 127.0.0.1:8765 --log=stdout >>"$TUNNEL_LOG" 2>&1 &
  echo $! >"$PID_FILE"
  verify_tunnel_pid_alive
  local url=""
  for _ in $(seq 1 30); do
    url="$(
      curl -sf http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | "$PY" -c "
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
  fail "tunnel_not_ready" "Timed out waiting for ngrok URL" "log $TUNNEL_LOG"
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

verify_local_actions() {
  if ! "$PY" "$ROOT/scripts/verify_chatgpt_actions_https.py" \
    --local-only \
    --key "${CROWLEY_ACTION_KEY}"; then
    fail "local_actions" "Local /api/actions/health check failed" "Crowley bus, .env CROWLEY_ACTION_KEY"
  fi
}

verify_public_actions() {
  local url="$1"
  if ! "$PY" "$ROOT/scripts/verify_chatgpt_actions_https.py" \
    --url "$url" \
    --key "${CROWLEY_ACTION_KEY}"; then
    fail "public_actions" "Public Actions HTTPS verification failed" \
      "cloudflared connector, DNS, .env key, ChatGPT schema URL"
  fi
}

main() {
  case "$MODE" in
    "" | --named) MODE="named" ;;
    --quick) MODE="quick" ;;
    --ngrok) MODE="ngrok" ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      fail "usage" "Unknown option: $MODE" "./scripts/start_chatgpt_bridge.sh --help"
      ;;
  esac

  load_env
  require_action_key
  mkdir -p "$BRIDGE_DIR"
  cleanup_stale_pid

  echo "Ensuring Crowley bus on 127.0.0.1:8765..."
  bash "$ROOT/scripts/ensure_crowley_bus.sh"
  restart_bus_if_actions_disabled
  verify_local_actions

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

  "$PY" "$ROOT/scripts/patch_openapi_chatgpt.py" --url "$public_url"

  echo ""
  verify_public_actions "$public_url"

  echo ""
  echo "ChatGPT bridge is running."
  if [[ -f "$PID_FILE" ]]; then
    echo "  Tunnel PID: $(cat "$PID_FILE")"
  elif [[ "$MODE" == "named" ]] && named_service_running; then
    echo "  Connector: durable LaunchAgent service"
  fi
  echo "  Tunnel log: $TUNNEL_LOG"
  echo "  OpenAPI:    openapi-chatgpt.deployed.json (import into Custom GPT)"
  echo "  Setup doc:  docs/CHATGPT_SETUP.md"
  echo "  Verify:     ./scripts/verify_chatgpt_bridge.py"
  if [[ -f "$PID_FILE" ]]; then
    echo ""
    echo "Stop foreground tunnel: kill \$(cat $PID_FILE)"
  fi
}

main "$@"
