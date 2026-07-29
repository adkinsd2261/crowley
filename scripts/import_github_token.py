#!/usr/bin/env python3
"""Import a copied GitHub token into Crowley's gitignored .env on Windows."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
REPO = "adkinsd2261/crowley"


def clipboard_text() -> str:
    if os.name != "nt":
        raise RuntimeError("Secure clipboard import is Windows-only")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError("Could not read the Windows clipboard")
        return result.stdout.rstrip("\r\n")
    finally:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Set-Clipboard -Value ([string]::Empty)",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )


def upsert_env(values: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    pending = dict(values)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name in pending:
                output.append(f"{name}={pending.pop(name)}")
                continue
        output.append(line)
    if output and output[-1]:
        output.append("")
    output.extend(f"{name}={value}" for name, value in pending.items())
    payload = "\n".join(output).rstrip() + "\n"
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=".env.",
        suffix=".tmp",
        dir=ENV_PATH.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        os.replace(temporary, ENV_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    try:
        token = clipboard_text().strip()
        if not token.startswith(("github_pat_", "ghp_")) or len(token) < 40:
            raise RuntimeError(
                f"Clipboard does not contain a recognizable GitHub token "
                f"(received {len(token)} characters)"
            )
        upsert_env(
            {
                "CROWLEY_GITHUB_TOKEN": token,
                "CROWLEY_GITHUB_REPO": REPO,
            }
        )
        print(
            "GitHub token imported into gitignored .env; "
            f"validated {len(token)} characters; clipboard cleared."
        )
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
