#!/usr/bin/env bash
# Start Crowley HTTP bus if not already running (127.0.0.1:8765).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.crowley"
LOG_FILE="$LOG_DIR/crowley_bus.log"
HEALTH_URL="http://127.0.0.1:8765/api/health"

RESTART=0
if [[ "${1:-}" == "--restart" ]]; then
  RESTART=1
fi

health_ok() {
  # Keep each probe bounded so callers like cursor_sync never hang.
  curl -sf --connect-timeout 1 --max-time 1 "$HEALTH_URL" >/dev/null 2>&1
}

stop_listener() {
  local listen_pid="$1"
  if [[ -z "$listen_pid" ]]; then
    return 0
  fi
  kill "$listen_pid" 2>/dev/null || true
  sleep 2
  if kill -0 "$listen_pid" 2>/dev/null; then
    kill -9 "$listen_pid" 2>/dev/null || true
    sleep 1
  fi
}

listen_pid="$(lsof -i tcp:8765 -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"

if [[ "$RESTART" == "1" ]]; then
  stop_listener "$listen_pid"
elif [[ -n "$listen_pid" ]] && ! health_ok; then
  echo "WARNING: Crowley listener on 8765 is unresponsive; restarting..." >&2
  stop_listener "$listen_pid"
elif health_ok; then
  exit 0
fi

mkdir -p "$LOG_DIR"
cd "$ROOT"
nohup "$ROOT/venv/bin/python3" "$ROOT/app.py" >>"$LOG_FILE" 2>&1 &
disown 2>/dev/null || true

for _ in $(seq 1 10); do
  if health_ok; then
    exit 0
  fi
  sleep 1
done

echo "WARNING: Crowley bus did not become healthy within 10s" >&2
exit 1
