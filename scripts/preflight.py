#!/usr/bin/env python3
"""Crowley preflight — version, DB, embed status, optional quick tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402

DEFAULT_HEALTH_URL = "http://127.0.0.1:8765/api/health"


def _fetch_health(url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            import json

            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _doc_version_ok() -> bool:
    versions = (ROOT / "VERSIONS.md").read_text(encoding="utf-8")
    return crowley.CROWLEY_VERSION in versions


def main() -> int:
    parser = argparse.ArgumentParser(description="Crowley release preflight")
    parser.add_argument("--health-url", default=DEFAULT_HEALTH_URL)
    parser.add_argument("--quick", action="store_true", help="Run a fast unittest subset")
    args = parser.parse_args()

    blockers: list[str] = []
    notes: list[str] = []

    try:
        crowley.setup_db()
        conn = crowley.connect_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        notes.append("DB writable: ok")
    except Exception as exc:
        blockers.append(f"DB setup failed: {exc}")

    provider = crowley._memory_embed_provider()
    notes.append(f"embed_provider: {provider}")

    conn = crowley.connect_db()
    try:
        sqlite_vec = crowley._try_load_sqlite_vec(conn)
    finally:
        conn.close()
    notes.append(f"sqlite_vec: {sqlite_vec}")

    if not _doc_version_ok():
        blockers.append(f"VERSIONS.md missing {crowley.CROWLEY_VERSION}")

    health = _fetch_health(args.health_url)
    if health is None:
        blockers.append(f"Bus health unreachable at {args.health_url}")
    else:
        live_version = str(health.get("version", ""))
        if live_version != crowley.CROWLEY_VERSION:
            blockers.append(
                f"/api/health version {live_version} != constants {crowley.CROWLEY_VERSION}"
            )
        else:
            notes.append(f"/api/health: {live_version}")

    if args.quick:
        env = os.environ.copy()
        env["CROWLEY_EMBED_PROVIDER"] = "off"
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            blockers.append("Quick unittest discover failed")
        else:
            notes.append("Quick tests: ok")

    print(f"Crowley preflight — {crowley.CROWLEY_RELEASE_LABEL}")
    for line in notes:
        print(f"  ✓ {line}")
    for line in blockers:
        print(f"  ✗ {line}")

    if blockers:
        print("\nPreflight FAILED.")
        return 1

    print("\nPreflight OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
