#!/usr/bin/env bash
# Lightweight watchdog: restart wedged Crowley bus when health probes fail.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HEALTH_URL="http://127.0.0.1:8765/api/health"
INTERVAL="${CROWLEY_BUS_WATCH_INTERVAL:-30}"
LOG_FILE="$ROOT/.crowley/bus_watchdog.log"

health_ok() {
  curl -sf --connect-timeout 1 --max-time 2 "$HEALTH_URL" >/dev/null 2>&1
}

recover_bus() {
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog: restarting unresponsive Crowley bus" >>"$LOG_FILE"
  bash "$ROOT/scripts/ensure_crowley_bus.sh" --restart >>"$LOG_FILE" 2>&1 || true
}

mkdir -p "$ROOT/.crowley"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) watchdog: started (interval=${INTERVAL}s)" >>"$LOG_FILE"

while true; do
  if ! health_ok; then
    recover_bus
  fi
  sleep "$INTERVAL"
done
