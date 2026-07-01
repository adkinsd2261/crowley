#!/usr/bin/env bash
# Cursor sessionStart: ensure Crowley bus is up and pull agent context.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$ROOT/scripts/ensure_crowley_bus.sh" >/dev/null 2>&1 || true
"$ROOT/venv/bin/python3" "$ROOT/scripts/cursor_sync.py" --session-start >/dev/null 2>&1 || true
"$ROOT/venv/bin/python3" "$ROOT/scripts/cursor_sync.py" --before >&2 || true
exit 0
