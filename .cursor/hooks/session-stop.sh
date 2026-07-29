#!/usr/bin/env bash
# stop: nudge handoff if Cursor session ended without ingest.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -x "$ROOT/venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT/venv/Scripts/python.exe"
else
  PYTHON="$ROOT/venv/bin/python3"
fi
"$PYTHON" "$ROOT/scripts/cursor_sync.py" --session-end >&2 || true
exit 0
