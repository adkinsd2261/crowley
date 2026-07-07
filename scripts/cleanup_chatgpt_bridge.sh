#!/usr/bin/env bash
# Recover from hung Crowley bus and duplicate cloudflared connectors.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/venv/bin/python3"
SERVICE="$ROOT/scripts/crowley_bridge_service.py"

echo "Cleaning ChatGPT bridge stack..."

# 1) Restart hung or wedged local bus.
bash "$ROOT/scripts/ensure_crowley_bus.sh" --restart

# 2) Stop LaunchAgent temporarily so duplicate connectors do not respawn.
if [[ -f "$PY" ]] && "$PY" "$SERVICE" status >/dev/null 2>&1; then
  echo "Stopping durable LaunchAgent connector for cleanup..."
  "$PY" "$SERVICE" stop || true
  sleep 2
fi

# 3) Prune duplicate tunnel processes (quick tunnels + extra named connectors).
"$PY" - <<PY
import sys
import time

sys.path.insert(0, "${ROOT}/scripts")
import chatgpt_bridge_lib as lib

before = lib.list_connector_pids()
result = lib.cleanup_duplicate_connectors()
time.sleep(1)
after = lib.list_connector_pids()
if after["named"] or after["quick"]:
    result = lib.cleanup_duplicate_connectors()
    time.sleep(1)
    after = lib.list_connector_pids()
print(
    "connectors:",
    f"before named={before['named']} quick={before['quick']}",
    f"killed_named={result['killed_named']} killed_quick={result['killed_quick']}",
    f"after named={after['named']} quick={after['quick']}",
)
PY

# 4) Start durable LaunchAgent connector when installed.
if [[ -f "$ROOT/cloudflared/config.yml" ]] && [[ -f "$HOME/Library/LaunchAgents/com.crowley.chatgpt-bridge.plist" ]]; then
  echo "Starting durable LaunchAgent connector..."
  "$PY" "$SERVICE" start
else
  echo "LaunchAgent not installed; leaving connector cleanup result as-is."
fi

# 5) Verify local + public Actions health (allow connector warm-up).
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

bash "$ROOT/scripts/ensure_crowley_bus.sh"

if [[ -n "${CROWLEY_ACTION_KEY:-}" ]]; then
  echo "Waiting for Cloudflare connector warm-up..."
  sleep 5
  ok=0
  for attempt in $(seq 1 12); do
    if output="$("$PY" "$ROOT/scripts/verify_chatgpt_bridge.py" --skip-service 2>/dev/null)"; then
      echo "$output"
      ok=1
      break
    fi
    if [[ "$attempt" -lt 12 ]]; then
      sleep 2
    fi
  done
  if [[ "$ok" != "1" ]]; then
    echo "WARNING: bridge verification still failing after warm-up." >&2
    "$PY" "$ROOT/scripts/verify_chatgpt_bridge.py" --skip-service
    exit 1
  fi
else
  curl -sf --connect-timeout 1 --max-time 2 http://127.0.0.1:8765/api/health >/dev/null \
    && echo "OK local /api/health" \
    || echo "FAIL local /api/health"
fi

echo "Cleanup complete."
