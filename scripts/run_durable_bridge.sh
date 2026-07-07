#!/usr/bin/env bash
# LaunchAgent entrypoint: ensure Crowley bus, then run named cloudflared connector.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_DIR="$ROOT/.crowley/chatgpt_bridge"
LOG_FILE="$BRIDGE_DIR/service.log"
CONFIG="$ROOT/cloudflared/config.yml"

mkdir -p "$BRIDGE_DIR"

resolve_cloudflared() {
  if command -v cloudflared >/dev/null 2>&1; then
    command -v cloudflared
    return 0
  fi
  for candidate in /opt/homebrew/bin/cloudflared /usr/local/bin/cloudflared; do
    if [[ -x "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

CLOUDFLARED="$(resolve_cloudflared || true)"
if [[ -z "$CLOUDFLARED" ]]; then
  echo "ERROR: cloudflared not found in PATH or Homebrew locations." >&2
  exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: Missing $CONFIG — copy cloudflared/config.yml.example and configure." >&2
  exit 1
fi

bash "$ROOT/scripts/ensure_crowley_bus.sh"

if [[ "${CROWLEY_BUS_WATCHDOG:-1}" != "0" ]]; then
  if ! pgrep -f "scripts/watch_crowley_bus.sh" >/dev/null 2>&1; then
    nohup bash "$ROOT/scripts/watch_crowley_bus.sh" >>"$BRIDGE_DIR/bus_watchdog.log" 2>&1 &
    disown 2>/dev/null || true
  fi
fi

exec "$CLOUDFLARED" tunnel --config "$CONFIG" run >>"$LOG_FILE" 2>&1
