#!/usr/bin/env bash
# Cursor sessionStart: ensure Crowley bus is up and pull agent context.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -x "$ROOT/venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT/venv/Scripts/python.exe"
else
  PYTHON="$ROOT/venv/bin/python3"
fi
"$PYTHON" "$ROOT/scripts/ensure_crowley_bus.py" >/dev/null 2>&1 || true
"$PYTHON" "$ROOT/scripts/cursor_sync.py" --session-start >/dev/null 2>&1 || true
"$PYTHON" "$ROOT/scripts/cursor_sync.py" --before >&2 || true
exit 0
