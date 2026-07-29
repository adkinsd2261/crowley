#!/usr/bin/env python3
"""Start or restart the local Crowley HTTP bus on macOS, Linux, or Windows."""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / ".crowley"
LOG_FILE = LOG_DIR / "crowley_bus.log"
# Startup readiness must stay local, bounded, and free of model/provider probes.
# /api/health intentionally gathers richer runtime diagnostics and can take
# several seconds when local/cloud providers are unavailable.
HEALTH_URL = "http://127.0.0.1:8765/api/metrics/summary"
PORT = 8765


def health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1) as response:
            return response.status == 200
    except (OSError, TimeoutError):
        return False


def listener_pid() -> int | None:
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        pattern = re.compile(
            rf"^\s*TCP\s+\S*:{PORT}\s+\S+\s+LISTENING\s+(\d+)\s*$",
            re.IGNORECASE,
        )
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if match:
                return int(match.group(1))
        return None

    result = subprocess.run(
        ["lsof", "-i", f"tcp:{PORT}", "-sTCP:LISTEN", "-t"],
        capture_output=True,
        text=True,
        check=False,
    )
    first = result.stdout.strip().splitlines()
    return int(first[0]) if first and first[0].isdigit() else None


def stop_listener(pid: int) -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                print(f"WARNING: could not stop Crowley listener {pid}: {detail}", file=sys.stderr)
                return False
        else:
            os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            if listener_pid() != pid:
                return True
            time.sleep(0.1)
        if os.name != "nt":
            os.kill(pid, signal.SIGKILL)
        return listener_pid() != pid
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"WARNING: could not stop Crowley listener {pid}: {exc}", file=sys.stderr)
        return False


def start_bus() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    creationflags = 0
    popen_kwargs: dict[str, object] = {}
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True

    with LOG_FILE.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, str(ROOT / "app.py")],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **popen_kwargs,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()

    pid = listener_pid()
    if args.restart or (pid is not None and not health_ok()):
        if pid is not None and not stop_listener(pid):
            return 1
    elif health_ok():
        return 0

    start_bus()
    for _ in range(120):
        if health_ok():
            return 0
        time.sleep(0.5)
    print("WARNING: Crowley bus did not become healthy within 60s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
