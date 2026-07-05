#!/usr/bin/env python3
"""Verify durable ChatGPT bridge end-to-end (V3.9.14 #85)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import chatgpt_bridge_lib as bridge  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify local bus, Actions auth, LaunchAgent, connector, and public routes."
    )
    parser.add_argument("--key", help="CROWLEY_ACTION_KEY (default: from .env)")
    parser.add_argument("--url", help="Public HTTPS base (default: CLOUDFLARE_TUNNEL_HOSTNAME)")
    parser.add_argument("--skip-service", action="store_true", help="Skip LaunchAgent status check")
    args = parser.parse_args()

    key = args.key
    if not key:
        env = ROOT / ".env"
        if env.is_file():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("CROWLEY_ACTION_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        print("ERROR: set CROWLEY_ACTION_KEY in .env or pass --key", file=sys.stderr)
        return 1

    report = bridge.build_verify_report(
        action_key=key,
        public_base=args.url,
        check_service=not args.skip_service,
    )
    print("ChatGPT bridge verification")
    for check in report.get("checks") or []:
        mark = "OK" if check.get("ok") else "FAIL"
        name = check.get("name")
        code = check.get("code")
        extra = f" HTTP {code}" if code is not None else ""
        print(f"  {mark} {name}{extra}")
    if report.get("failures"):
        print("\nTroubleshooting:", file=sys.stderr)
        for line in report["failures"]:
            print(f"  {line}", file=sys.stderr)
    else:
        print("\nAll bridge checks passed.")
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
