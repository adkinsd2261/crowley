#!/usr/bin/env python3
"""Install and inspect Crowley's existing Cloudflare tunnel at Windows logon."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASK_NAME = "Crowley ChatGPT Bridge"
RUN_VALUE_NAME = "CrowleyChatGPTBridge"
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
RUNNER = ROOT / "scripts" / "run_windows_bridge.cmd"
CONFIG = ROOT / "cloudflared" / "config.yml"
CREDENTIALS_DIR = ROOT / ".crowley" / "cloudflared"
CLOUDFLARED = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Cloudflared"
    / "cloudflared.exe"
)


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def preflight() -> None:
    missing = [
        path
        for path in (RUNNER, CONFIG, CLOUDFLARED)
        if not path.is_file()
    ]
    if missing:
        raise RuntimeError(
            "Missing bridge dependency: " + ", ".join(str(path) for path in missing)
        )
    if not any(CREDENTIALS_DIR.glob("*.json")):
        raise RuntimeError(f"Tunnel credentials missing: {CREDENTIALS_DIR}")


def install() -> int:
    if os.name != "nt":
        raise RuntimeError("This installer is Windows-only")
    preflight()
    result = run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            str(RUNNER),
            "/SC",
            "ONLOGON",
            "/F",
        ]
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        existing = run(["schtasks", "/Query", "/TN", TASK_NAME])
        if existing.returncode == 0:
            print(
                "Windows task already exists; keeping the existing durable "
                f"startup: {TASK_NAME}"
            )
            return 0
        fallback = run(
            [
                "reg.exe",
                "add",
                RUN_KEY,
                "/v",
                RUN_VALUE_NAME,
                "/t",
                "REG_SZ",
                "/d",
                f'cmd.exe /c "{RUNNER}"',
                "/f",
            ]
        )
        if fallback.returncode != 0:
            fallback_detail = (fallback.stderr or fallback.stdout).strip()
            raise RuntimeError(
                f"Task Scheduler: {detail}; logon fallback: {fallback_detail}"
            )
        print(
            "Task Scheduler required administrator permission; installed "
            "current-user Windows logon startup instead."
        )
        return 0
    start_result = run(["schtasks", "/Run", "/TN", TASK_NAME])
    if start_result.returncode != 0:
        raise RuntimeError((start_result.stderr or start_result.stdout).strip())
    print(f"Installed and started Windows task: {TASK_NAME}")
    return 0


def status() -> int:
    result = run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"])
    if result.returncode == 0:
        print(result.stdout.strip())
        return 0
    fallback = run(["reg.exe", "query", RUN_KEY, "/v", RUN_VALUE_NAME])
    if fallback.returncode == 0:
        print("Current-user Windows logon startup is installed.")
        print(fallback.stdout.strip())
        return 0
    print(f"Windows startup missing: {TASK_NAME}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "status"))
    args = parser.parse_args()
    try:
        return install() if args.command == "install" else status()
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
