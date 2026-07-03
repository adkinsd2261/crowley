#!/usr/bin/env python3
"""Verify Crowley ChatGPT Actions API over a public HTTPS base URL."""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import certifi

WRITEBACK_PARSE_BODY: dict[str, Any] = {
    "writeback": {
        "session": {
            "summary": "Bridge verify.",
            "surface": "chatgpt",
            "model": "test",
        },
        "sparks": [],
    }
}


def ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def resolve_host_ip(hostname: str) -> str | None:
    try:
        infos = socket.getaddrinfo(hostname, 443, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            return str(infos[0][4][0])
    except OSError:
        pass

    for nameserver in ("8.8.8.8", "1.1.1.1"):
        try:
            proc = subprocess.run(
                ["dig", f"@{nameserver}", "+short", hostname, "A"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        for line in proc.stdout.splitlines():
            candidate = line.strip()
            if candidate and candidate[0].isdigit():
                return candidate
    return None


def request_code(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
    connect_ip: str | None = None,
) -> int:
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    if connect_ip and parsed.scheme == "https" and host:
        return _https_request_via_ip(
            host=host,
            connect_ip=connect_ip,
            path=path,
            method=method,
            headers=hdrs,
            data=data,
            timeout=timeout,
        )

    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    ctx = ssl_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def _https_request_via_ip(
    *,
    host: str,
    connect_ip: str,
    path: str,
    method: str,
    headers: dict[str, str],
    data: bytes | None,
    timeout: float,
) -> int:
    ctx = ssl_context()
    try:
        with socket.create_connection((connect_ip, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                conn = http.client.HTTPSConnection(host, timeout=timeout, context=ctx)
                conn.sock = ssock
                conn.request(method, path, body=data, headers=headers)
                resp = conn.getresponse()
                return int(resp.status)
    except TimeoutError:
        return 0
    except OSError:
        return 0
    except http.client.HTTPException:
        return 0


def request_with_fallback(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> int:
    code = request_code(url, method=method, headers=headers, body=body, timeout=timeout)
    if code:
        return code

    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host:
        return 0

    connect_ip = resolve_host_ip(host)
    if not connect_ip:
        return 0

    return request_code(
        url,
        method=method,
        headers=headers,
        body=body,
        timeout=timeout,
        connect_ip=connect_ip,
    )


def verify_local(*, action_key: str, port: int = 8765) -> int:
    base = f"http://127.0.0.1:{port}"
    auth = {"Authorization": f"Bearer {action_key}"}
    code = request_code(f"{base}/api/actions/health", headers=auth, timeout=5.0)
    if code != 200:
        print(f"FAIL local /api/actions/health → HTTP {code}", file=sys.stderr)
        return 1
    print("OK   local /api/actions/health → HTTP 200")
    return 0


def verify(*, base_url: str, action_key: str, wait_seconds: int = 90) -> int:
    base = base_url.rstrip("/")
    auth = {"Authorization": f"Bearer {action_key}"}
    checks: list[tuple[str, str, dict[str, Any] | None]] = [
        ("GET", f"{base}/api/actions/health", None),
        ("GET", f"{base}/api/actions/context?limit=3", None),
        ("GET", f"{base}/api/actions/retrieve?q=current%20project&limit=3", None),
        ("POST", f"{base}/api/actions/writeback/parse", WRITEBACK_PARSE_BODY),
    ]

    print("Verifying ChatGPT Actions API over HTTPS...", flush=True)
    deadline = time.monotonic() + wait_seconds

    health_url = checks[0][1]
    health_ok = False
    while time.monotonic() < deadline:
        code = request_with_fallback(health_url, headers=auth)
        if code == 200:
            print(f"OK   /api/actions/health → HTTP {code}")
            health_ok = True
            break
        time.sleep(2)

    if not health_ok:
        print("FAIL /api/actions/health → tunnel not ready in time", file=sys.stderr)
        return 1

    for method, url, body in checks[1:]:
        path = url[len(base) :].split("?", 1)[0]
        code = 0
        for _ in range(3):
            code = request_with_fallback(url, method=method, headers=auth, body=body)
            if code == 200:
                print(f"OK   {path} → HTTP {code}")
                break
            time.sleep(2)
        else:
            print(f"FAIL {path} → HTTP {code}", file=sys.stderr)
            return 1

    print("All Actions checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ChatGPT Actions API over HTTPS.")
    parser.add_argument("--url", help="Public HTTPS base URL")
    parser.add_argument("--key", required=True, help="CROWLEY_ACTION_KEY bearer token")
    parser.add_argument("--wait", type=int, default=90, help="Seconds to wait for tunnel readiness")
    parser.add_argument("--local-only", action="store_true", help="Verify localhost Actions only")
    parser.add_argument("--port", type=int, default=8765, help="Local Crowley port")
    args = parser.parse_args()

    if args.local_only:
        return verify_local(action_key=args.key, port=args.port)

    if not args.url:
        parser.error("--url is required unless --local-only is set")

    return verify(base_url=args.url, action_key=args.key, wait_seconds=args.wait)


if __name__ == "__main__":
    raise SystemExit(main())
