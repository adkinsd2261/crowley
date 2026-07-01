#!/usr/bin/env bash
# Start Crowley HTTP bus if not already running (127.0.0.1:8765).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/.crowley"
LOG_FILE="$LOG_DIR/crowley_bus.log"
HEALTH_URL="http://127.0.0.1:8765/api/health"

if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
  exit 0
fi

mkdir -p "$LOG_DIR"
cd "$ROOT"
nohup "$ROOT/venv/bin/python3" "$ROOT/app.py" >>"$LOG_FILE" 2>&1 &
disown 2>/dev/null || true

for _ in $(seq 1 15); do
  if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
done

echo "WARNING: Crowley bus did not become healthy within 15s" >&2
exit 1
