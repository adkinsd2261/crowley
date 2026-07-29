#!/usr/bin/env bash
# Cross-platform wrapper for the Crowley HTTP bus manager.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -x "$ROOT/venv/Scripts/python.exe" ]]; then
  PYTHON="$ROOT/venv/Scripts/python.exe"
else
  PYTHON="$ROOT/venv/bin/python3"
fi

exec "$PYTHON" "$ROOT/scripts/ensure_crowley_bus.py" "$@"
