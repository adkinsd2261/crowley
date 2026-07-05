#!/usr/bin/env python3
"""macOS LaunchAgent manager for the durable Crowley ChatGPT bridge connector."""

from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.crowley.chatgpt-bridge"
PLIST_NAME = f"{LABEL}.plist"
RUN_SCRIPT = ROOT / "scripts" / "run_durable_bridge.sh"
CONFIG_PATH = ROOT / "cloudflared" / "config.yml"
BRIDGE_DIR = ROOT / ".crowley" / "chatgpt_bridge"
SERVICE_LOG = BRIDGE_DIR / "service.log"
EXAMPLE_PLIST = ROOT / "launchd" / f"{PLIST_NAME}.example"
EXAMPLE_REPO_ROOT = Path("/path/to/crowley")


@dataclass(frozen=True)
class ServicePaths:
    repo_root: Path
    launch_agents_dir: Path
    installed_plist: Path
    domain_target: str


def service_paths(*, home: Path | None = None) -> ServicePaths:
    home = home or Path.home()
    launch_agents = home / "Library" / "LaunchAgents"
    uid = _launchctl_uid(home)
    return ServicePaths(
        repo_root=ROOT,
        launch_agents_dir=launch_agents,
        installed_plist=launch_agents / PLIST_NAME,
        domain_target=f"gui/{uid}",
    )


def _launchctl_uid(home: Path) -> int:
    try:
        return home.stat().st_uid
    except OSError:
        return 501


def cloudflared_binary() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared"):
        if Path(candidate).is_file():
            return candidate
    return None


def default_path_env() -> str:
    return "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def render_plist(*, repo_root: Path, run_script: Path, log_file: Path) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": ["/bin/bash", str(run_script.resolve())],
        "WorkingDirectory": str(repo_root.resolve()),
        "EnvironmentVariables": {"PATH": default_path_env()},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_file.resolve()),
        "StandardErrorPath": str(log_file.resolve()),
    }


def write_example_plist(*, repo_root: Path | None = None, output: Path | None = None) -> None:
    """Regenerate the committed example plist (dev/maintenance only — not called from install)."""
    repo_root = repo_root or EXAMPLE_REPO_ROOT
    output = output or EXAMPLE_PLIST
    run_script = repo_root / "scripts" / "run_durable_bridge.sh"
    log_file = repo_root / ".crowley" / "chatgpt_bridge" / "service.log"
    payload = render_plist(
        repo_root=repo_root,
        run_script=run_script,
        log_file=log_file,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        plistlib.dump(payload, handle)


def preflight() -> None:
    if not RUN_SCRIPT.is_file():
        raise FileNotFoundError(f"Missing run script: {RUN_SCRIPT}")
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {CONFIG_PATH} — copy cloudflared/config.yml.example and configure."
        )
    if cloudflared_binary() is None:
        raise RuntimeError("cloudflared not found in PATH. Install with: brew install cloudflared")


def _run_launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _service_loaded(paths: ServicePaths) -> bool:
    proc = _run_launchctl(["print", f"{paths.domain_target}/{LABEL}"])
    return proc.returncode == 0


def _service_state(paths: ServicePaths) -> str:
    proc = _run_launchctl(["print", f"{paths.domain_target}/{LABEL}"])
    if proc.returncode != 0:
        return "missing"
    output = proc.stdout
    if "state = running" in output:
        return "running"
    if "state = " in output:
        for line in output.splitlines():
            if line.strip().startswith("state ="):
                return line.split("=", 1)[1].strip()
    return "loaded"


def _connector_process_running() -> bool:
    config = str(CONFIG_PATH.resolve())
    patterns = (
        f"cloudflared tunnel --config {config} run",
        "cloudflared tunnel --config cloudflared/config.yml run",
    )
    for pattern in patterns:
        proc = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return True
    return False


def install(*, paths: ServicePaths | None = None) -> None:
    paths = paths or service_paths()
    preflight()
    paths.launch_agents_dir.mkdir(parents=True, exist_ok=True)
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    payload = render_plist(
        repo_root=paths.repo_root,
        run_script=RUN_SCRIPT,
        log_file=SERVICE_LOG,
    )
    with paths.installed_plist.open("wb") as handle:
        plistlib.dump(payload, handle)
    print(f"Installed LaunchAgent plist → {paths.installed_plist}")
    start(paths=paths)


def start(*, paths: ServicePaths | None = None) -> None:
    paths = paths or service_paths()
    preflight()
    if not paths.installed_plist.is_file():
        raise FileNotFoundError(
            f"LaunchAgent not installed. Run: {ROOT / 'scripts' / 'crowley_bridge_service.py'} install"
        )
    if _service_loaded(paths):
        proc = _run_launchctl(["kickstart", "-k", f"{paths.domain_target}/{LABEL}"])
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "launchctl kickstart failed")
        print(f"Restarted LaunchAgent service ({LABEL}).")
        return
    proc = _run_launchctl(["bootstrap", paths.domain_target, str(paths.installed_plist)])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "launchctl bootstrap failed")
    print(f"Loaded LaunchAgent service ({LABEL}).")


def stop(*, paths: ServicePaths | None = None) -> None:
    paths = paths or service_paths()
    if not paths.installed_plist.is_file():
        print("LaunchAgent plist not installed.")
        return
    if not _service_loaded(paths):
        print("LaunchAgent service is not loaded.")
        return
    proc = _run_launchctl(["bootout", paths.domain_target, str(paths.installed_plist)])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "launchctl bootout failed")
    print(f"Stopped LaunchAgent service ({LABEL}). Plist kept at {paths.installed_plist}")


def uninstall(*, paths: ServicePaths | None = None) -> None:
    paths = paths or service_paths()
    if _service_loaded(paths):
        stop(paths=paths)
    if paths.installed_plist.is_file():
        paths.installed_plist.unlink()
        print(f"Removed LaunchAgent plist ({paths.installed_plist}).")
    else:
        print("LaunchAgent plist not present.")
    print("Tunnel credentials in .crowley/cloudflared/ were not modified.")


def status(*, paths: ServicePaths | None = None) -> int:
    paths = paths or service_paths()
    lines: list[str] = []
    plist_state = "installed" if paths.installed_plist.is_file() else "missing"
    lines.append(f"plist: {plist_state} ({paths.installed_plist})")

    if paths.installed_plist.is_file() and _service_loaded(paths):
        lines.append(f"launchd: {_service_state(paths)}")
    elif paths.installed_plist.is_file():
        lines.append("launchd: not loaded")
    else:
        lines.append("launchd: n/a")

    connector = "running" if _connector_process_running() else "stopped"
    lines.append(f"cloudflared connector: {connector}")

    if CONFIG_PATH.is_file():
        lines.append(f"config: {CONFIG_PATH}")
    else:
        lines.append(f"config: missing ({CONFIG_PATH})")

    if SERVICE_LOG.is_file():
        lines.append(f"log: {SERVICE_LOG}")
    else:
        lines.append(f"log: (none yet) {SERVICE_LOG}")

    print("\n".join(lines))

    if plist_state == "missing":
        return 2
    if not _service_loaded(paths):
        return 1
    if connector != "running":
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install and manage the durable Crowley ChatGPT bridge LaunchAgent."
    )
    parser.add_argument(
        "command",
        choices=("install", "start", "stop", "status", "uninstall"),
        help="Service action",
    )
    args = parser.parse_args()

    try:
        if args.command == "install":
            install()
        elif args.command == "start":
            start()
        elif args.command == "stop":
            stop()
        elif args.command == "status":
            return status()
        elif args.command == "uninstall":
            uninstall()
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
