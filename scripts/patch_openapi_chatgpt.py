#!/usr/bin/env python3
"""Patch openapi-chatgpt.json server URL for a deployed tunnel hostname."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "openapi-chatgpt.json"
DEFAULT_OUTPUT = ROOT / "openapi-chatgpt.deployed.json"


def normalize_base_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("URL must start with https:// or http://")
    if not parsed.netloc:
        raise ValueError("URL must include a hostname")
    base = f"{parsed.scheme}://{parsed.netloc}"
    return base.rstrip("/")


def patch_openapi(*, base_url: str, template: Path, output: Path) -> dict[str, object]:
    if not template.is_file():
        raise FileNotFoundError(f"OpenAPI template not found: {template}")
    payload = json.loads(template.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("OpenAPI template must be a JSON object")
    servers = payload.get("servers")
    if not isinstance(servers, list) or not servers:
        raise ValueError("OpenAPI template must include servers[0]")
    first = servers[0]
    if not isinstance(first, dict):
        raise ValueError("servers[0] must be an object")
    first["url"] = base_url
    first["description"] = (
        "Crowley ChatGPT Actions bridge (Cloudflare Tunnel or ngrok → 127.0.0.1:8765)"
    )
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch ChatGPT OpenAPI server URL.")
    parser.add_argument("--url", required=True, help="Public HTTPS base URL (no trailing path)")
    parser.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE,
        help="Source OpenAPI file (default: openapi-chatgpt.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output file (default: openapi-chatgpt.deployed.json)",
    )
    parser.add_argument(
        "--also-update-canonical",
        action="store_true",
        help="Also write the same URL into openapi-chatgpt.json",
    )
    args = parser.parse_args()

    try:
        base_url = normalize_base_url(args.url)
        patch_openapi(base_url=base_url, template=args.template, output=args.output)
        if args.also_update_canonical and args.output.resolve() != TEMPLATE.resolve():
            patch_openapi(base_url=base_url, template=args.template, output=TEMPLATE)
    except (ValueError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Patched OpenAPI server URL → {base_url}")
    print(f"Wrote {args.output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
