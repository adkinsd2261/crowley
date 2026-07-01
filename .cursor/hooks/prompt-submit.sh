#!/usr/bin/env bash
# beforeSubmitPrompt: refresh Crowley context before each user message.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$ROOT/scripts/ensure_crowley_bus.sh" >/dev/null 2>&1 || true
"$ROOT/venv/bin/python3" "$ROOT/scripts/cursor_sync.py" --before >/dev/null 2>&1 || true
exit 0
