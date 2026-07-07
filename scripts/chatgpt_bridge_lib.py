#!/usr/bin/env python3
"""Shared ChatGPT bridge operator helpers (V3.9.14)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import certifi

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class FailureHint:
    category: str
    message: str
    inspect: str


def classify_http_failure(
    code: int,
    *,
    context: str = "request",
    body: str = "",
) -> FailureHint:
    """Map HTTP/status codes to operator troubleshooting hints."""
    if code == 0:
        return FailureHint(
            category="local_connection",
            message=f"{context}: could not connect (connection refused or timeout)",
            inspect="Crowley bus on 127.0.0.1:8765, cloudflared connector, DNS",
        )
    if code == 401:
        return FailureHint(
            category="key_mismatch",
            message=f"{context}: HTTP 401 unauthorized",
            inspect=".env CROWLEY_ACTION_KEY and Custom GPT bearer auth",
        )
    if code == 403:
        return FailureHint(
            category="cloudflare_or_waf",
            message=f"{context}: HTTP 403 forbidden",
            inspect="Cloudflare/WAF blocking; verify User-Agent on HTTPS checks",
        )
    if code == 404 and "actions" not in context.lower():
        return FailureHint(
            category="route_boundary_ok",
            message=f"{context}: HTTP 404 (expected for blocked public paths)",
            inspect="tunnel ingress should 404 non-/api/actions/* routes",
        )
    if code == 404:
        return FailureHint(
            category="route_or_path",
            message=f"{context}: HTTP 404",
            inspect="cloudflared ingress path rules and ChatGPT schema URL",
        )
    if code == 502:
        return FailureHint(
            category="tunnel_upstream",
            message=f"{context}: HTTP 502 bad gateway",
            inspect="cloudflared connector running and Crowley bus healthy locally",
        )
    if code == 503:
        return FailureHint(
            category="actions_disabled",
            message=f"{context}: HTTP 503 Actions API disabled",
            inspect=".env CROWLEY_ACTION_KEY and restart Crowley bus",
        )
    if "1033" in body or code == 530:
        return FailureHint(
            category="dns_tunnel_not_ready",
            message=f"{context}: tunnel/DNS not ready (Cloudflare 1033/530)",
            inspect="cloudflared connector, DNS route, named tunnel config",
        )
    return FailureHint(
        category="unknown_http",
        message=f"{context}: HTTP {code}",
        inspect="tunnel log, service status, local /api/actions/health",
    )


def read_pid_file(pid_file: Path) -> int | None:
    if not pid_file.is_file():
        return None
    try:
        raw = pid_file.read_text(encoding="utf-8").strip()
        return int(raw) if raw.isdigit() else None
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def cleanup_stale_pid_file(pid_file: Path) -> bool:
    """Remove pid file when process is gone. Returns True if cleaned."""
    pid = read_pid_file(pid_file)
    if pid is None:
        if pid_file.is_file():
            pid_file.unlink(missing_ok=True)
            return True
        return False
    if not pid_alive(pid):
        pid_file.unlink(missing_ok=True)
        return True
    return False


def _pgrep_pids(pattern: str) -> list[int]:
    proc = subprocess.run(
        ["pgrep", "-f", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    pids: list[int] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return sorted(set(pids))


def list_connector_pids(config_path: Path | None = None) -> dict[str, list[int]]:
    """Return named and quick cloudflared tunnel PIDs."""
    config = str((config_path or ROOT / "cloudflared" / "config.yml").resolve())
    named: list[int] = []
    for pattern in (
        f"cloudflared tunnel --config {config} run",
        "cloudflared tunnel --config cloudflared/config.yml run",
    ):
        named.extend(_pgrep_pids(pattern))
    quick = _pgrep_pids(r"cloudflared tunnel --url http://127\.0\.0\.1:8765")
    return {
        "named": sorted(set(named)),
        "quick": sorted(set(quick)),
    }


def connector_process_running(config_path: Path | None = None) -> bool:
    return bool(list_connector_pids(config_path=config_path)["named"])


def _kill_pids(pids: list[int]) -> list[int]:
    killed: list[int] = []
    for pid in pids:
        try:
            os.kill(pid, 15)
            killed.append(pid)
        except OSError:
            continue
    if not killed:
        return killed
    import time

    time.sleep(1.0)
    for pid in list(killed):
        if pid_alive(pid):
            try:
                os.kill(pid, 9)
            except OSError:
                continue
    return killed


def cleanup_duplicate_connectors(
    *,
    config_path: Path | None = None,
    keep_pid: int | None = None,
) -> dict[str, list[int]]:
    """Stop duplicate cloudflared connectors; always remove quick tunnels."""
    groups = list_connector_pids(config_path=config_path)
    killed_quick = _kill_pids(groups["quick"])

    named = groups["named"]
    keep = keep_pid
    if keep is None and len(named) == 1:
        keep = named[0]
    if keep is not None and keep in named:
        to_kill = [pid for pid in named if pid != keep]
    else:
        # Multiple named connectors and no keeper — stop all; caller restarts one.
        to_kill = named
        keep = None

    killed_named = _kill_pids(to_kill)
    return {
        "killed_quick": killed_quick,
        "killed_named": killed_named,
        "kept_named": [keep] if keep is not None else [],
    }


def bus_responsive(timeout: float = 2.0) -> bool:
    code, _ = http_status("http://127.0.0.1:8765/api/health", timeout=timeout)
    return code == 200


def launchagent_service_status() -> tuple[int, str]:
    script = ROOT / "scripts" / "crowley_bridge_service.py"
    proc = subprocess.run(
        [sys.executable, str(script), "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def _ssl_context():
    import ssl

    ctx = ssl.create_default_context(cafile=certifi.where())
    return ctx


def http_status(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
            body = resp.read(512).decode("utf-8", errors="replace")
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        body = exc.read(512).decode("utf-8", errors="replace")
        return int(exc.code), body
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, ""


def local_actions_health(action_key: str) -> tuple[int, FailureHint | None]:
    code, _ = http_status(
        "http://127.0.0.1:8765/api/actions/health",
        headers={"Authorization": f"Bearer {action_key}"},
        timeout=5.0,
    )
    if code == 200:
        return code, None
    return code, classify_http_failure(code, context="local /api/actions/health")


def actions_retrieve_probe(
    base_url: str,
    action_key: str,
    *,
    timeout: float = 20.0,
) -> tuple[int, str, FailureHint | None]:
    """POST retrieve.search via Actions read gateway; return status, content-type, hint."""
    base = base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {action_key}",
        "Content-Type": "application/json",
        "User-Agent": "Crowley-ChatGPT-Bridge-Verify/1.0",
        "Accept": "application/json",
    }

    def _post(tool: str, args: dict[str, object]) -> tuple[int, str, str]:
        url = f"{base}/api/actions/read"
        payload = json.dumps({"tool": tool, "args": args}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
            content_type = str(resp.headers.get("Content-Type") or "")
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, content_type, body

    try:
        sync_code, _, sync_body = _post(
            "agent.sync",
            {"agent": "chatgpt", "limit": 3},
        )
        if sync_code != 200:
            return sync_code, "", classify_http_failure(
                sync_code, context="agent.sync before retrieve.search", body=sync_body
            )
        code, content_type, body = _post(
            "retrieve.search",
            {"q": "bridge verification probe", "limit": 3},
        )
        if code != 200:
            return code, content_type, classify_http_failure(
                code, context="retrieve.search", body=body
            )
        if "application/json" not in content_type.lower():
            return (
                code,
                content_type,
                FailureHint(
                    category="invalid_content_type",
                    message="retrieve.search returned non-JSON content-type",
                    inspect=content_type or "missing Content-Type",
                ),
            )
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return (
                code,
                content_type,
                FailureHint(
                    category="invalid_json",
                    message="retrieve.search body is not valid JSON",
                    inspect=body[:200],
                ),
            )
        if not isinstance(parsed.get("results"), list):
            return (
                code,
                content_type,
                FailureHint(
                    category="invalid_payload",
                    message="retrieve.search JSON missing results list",
                    inspect=str(parsed.keys()),
                ),
            )
        return code, content_type, None
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        return exc.code, str(exc.headers.get("Content-Type") or ""), classify_http_failure(
            exc.code, context="retrieve.search", body=body
        )
    except Exception:
        return 0, "", FailureHint(
            category="local_connection",
            message="retrieve.search probe could not connect",
            inspect=base,
        )


def format_hint(hint: FailureHint) -> str:
    return f"[{hint.category}] {hint.message} → inspect: {hint.inspect}"


def build_verify_report(
    *,
    action_key: str,
    public_base: str | None = None,
    check_service: bool = True,
) -> dict[str, Any]:
    """Full durable bridge verification report."""
    public_base = (public_base or os.environ.get("CLOUDFLARE_TUNNEL_HOSTNAME", "")).strip()
    if public_base and not public_base.startswith("http"):
        public_base = f"https://{public_base}"

    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    bus_code, _ = http_status("http://127.0.0.1:8765/api/health", timeout=5.0)
    checks.append({"name": "local_bus", "code": bus_code, "ok": bus_code == 200})
    if bus_code != 200:
        failures.append(format_hint(classify_http_failure(bus_code, context="local /api/health")))

    local_code, local_hint = local_actions_health(action_key)
    checks.append({"name": "local_actions", "code": local_code, "ok": local_code == 200})
    if local_hint:
        failures.append(format_hint(local_hint))

    retrieve_code, retrieve_ct, retrieve_hint = actions_retrieve_probe(
        "http://127.0.0.1:8765",
        action_key,
        timeout=20.0,
    )
    checks.append(
        {
            "name": "local_actions_retrieve",
            "code": retrieve_code,
            "ok": retrieve_hint is None,
            "content_type": retrieve_ct,
        }
    )
    if retrieve_hint:
        failures.append(format_hint(retrieve_hint))

    if check_service:
        svc_code, svc_out = launchagent_service_status()
        checks.append(
            {
                "name": "launchagent_status",
                "code": svc_code,
                "ok": svc_code == 0,
                "detail": svc_out.splitlines()[:6],
            }
        )
        if svc_code != 0:
            failures.append(
                "[service_not_ready] LaunchAgent service not fully healthy "
                "→ inspect: ./scripts/crowley_bridge_service.py status"
            )

    connector = connector_process_running()
    checks.append({"name": "cloudflared_connector", "ok": connector})
    if not connector:
        failures.append(
            "[no_connector] cloudflared connector not running "
            "→ inspect: LaunchAgent service or start_chatgpt_bridge.sh"
        )

    auth = {"Authorization": f"Bearer {action_key}", "User-Agent": "Crowley-ChatGPT-Bridge-Verify/1.0"}
    public_headers = {"User-Agent": "Crowley-ChatGPT-Bridge-Verify/1.0"}

    if public_base:
        for path, expect_ok in (
            ("/api/actions/health", True),
            ("/", False),
            ("/api/health", False),
        ):
            url = f"{public_base.rstrip('/')}{path}"
            headers = auth if path == "/api/actions/health" else public_headers
            code, body = http_status(url, headers=headers, timeout=20.0)
            ok = (code == 200) if expect_ok else (code == 404)
            checks.append({"name": f"public{path}", "code": code, "ok": ok, "url": url})
            if not ok:
                hint = classify_http_failure(code, context=f"public {path}", body=body)
                failures.append(format_hint(hint))

        pub_retrieve_code, pub_retrieve_ct, pub_retrieve_hint = actions_retrieve_probe(
            public_base,
            action_key,
            timeout=30.0,
        )
        checks.append(
            {
                "name": "public/api/actions/retrieve.search",
                "code": pub_retrieve_code,
                "ok": pub_retrieve_hint is None,
                "content_type": pub_retrieve_ct,
            }
        )
        if pub_retrieve_hint:
            failures.append(format_hint(pub_retrieve_hint))

    status = "ok" if not failures else "fail"
    return {
        "status": status,
        "checks": checks,
        "failures": failures,
        "public_base": public_base or None,
    }


def print_verify_report(report: dict[str, Any]) -> int:
    print(json.dumps(report, indent=2))
    for line in report.get("failures") or []:
        print(line, file=sys.stderr)
    return 0 if report.get("status") == "ok" else 1
