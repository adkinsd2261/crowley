#!/usr/bin/env bash
# stop: nudge handoff if Cursor session ended without ingest.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
"$ROOT/venv/bin/python3" "$ROOT/scripts/cursor_sync.py" --session-end >&2 || true
exit 0
