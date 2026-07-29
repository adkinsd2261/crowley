#!/usr/bin/env python3
"""Encrypted Crowley disaster recovery with restic.

The live SQLite database is never copied directly. A consistent online backup is
created first, then restic encrypts and uploads the recovery bundle.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import getpass
import hashlib
import json
import os
import platform
import secrets as secrets_module
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / ".crowley" / "backup"
CONFIG_PATH = RUNTIME_DIR / "config.json"
SECRETS_PATH = RUNTIME_DIR / "secrets.dpapi"
STAGING_DIR = RUNTIME_DIR / "staging" / "current"
DRILLS_DIR = RUNTIME_DIR / "drills"
LOG_PATH = RUNTIME_DIR / "backup.log"
SCHEMA_VERSION = 1
DEFAULT_RESTIC_WINDOWS = (
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Restic"
    / "restic.exe"
)
RECOVERY_TABLES = (
    "memory_items",
    "tickets",
    "agent_activity",
    "project_state",
    "sparks",
    "spark_links",
    "patterns",
    "tasks",
    "open_loops",
    "decisions",
)


class BackupError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def database_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("CROWLEY_DB_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else ROOT / "crowley.db"


def _table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    available = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    counts: dict[str, int] = {}
    for table in RECOVERY_TABLES:
        if table in available:
            counts[table] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
    return counts


def create_snapshot(
    *,
    source_db: Path,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    if not source_db.is_file():
        raise BackupError(f"Crowley database not found: {source_db}")

    if output_dir is None:
        output_dir = STAGING_DIR
    if output_dir.exists():
        shutil.rmtree(output_dir)
    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    snapshot_db = state_dir / "crowley.db"

    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True, timeout=30)
    destination = sqlite3.connect(snapshot_db)
    try:
        source.backup(destination)
        destination.commit()
        integrity = str(destination.execute("PRAGMA quick_check").fetchone()[0])
        counts = _table_counts(destination)
    finally:
        destination.close()
        source.close()

    if integrity.lower() != "ok":
        raise BackupError(f"SQLite snapshot quick_check failed: {integrity}")

    processed = ROOT / ".crowley" / "processed"
    if processed.is_dir():
        shutil.copytree(processed, state_dir / "processed", dirs_exist_ok=True)
    for name in ("brain.json", "writeback_acceptance_report.json"):
        source_file = ROOT / ".crowley" / name
        if source_file.is_file():
            shutil.copy2(source_file, state_dir / name)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "source_db": str(source_db),
        "database": {
            "relative_path": "state/crowley.db",
            "size_bytes": snapshot_db.stat().st_size,
            "sha256": sha256_file(snapshot_db),
            "quick_check": integrity,
            "table_counts": counts,
        },
        "repository": {
            "git_commit": _git("rev-parse", "HEAD"),
            "git_branch": _git("branch", "--show-current"),
            "git_dirty": bool(_git("status", "--porcelain")),
        },
        "machine": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "excluded_secrets": [
            ".env",
            ".crowley/cloudflared",
            ".crowley/backup/secrets.dpapi",
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_ulong),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise BackupError("DPAPI secret storage is currently supported on Windows only")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = _DataBlob()
    description = ctypes.c_wchar_p("Crowley encrypted backup credentials")
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if decrypt:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
    else:
        ok = crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            description,
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def save_secrets(secrets: dict[str, str]) -> None:
    payload = json.dumps(secrets, sort_keys=True).encode("utf-8")
    protected = _dpapi(payload, decrypt=False)
    SECRETS_PATH.write_bytes(base64.b64encode(protected))


def load_secrets() -> dict[str, str]:
    if not SECRETS_PATH.is_file():
        raise BackupError(
            f"Backup credentials are not configured. Run: {Path(sys.executable).name} "
            "scripts/crowley_backup.py configure"
        )
    protected = base64.b64decode(SECRETS_PATH.read_bytes(), validate=True)
    payload = _dpapi(protected, decrypt=True)
    values = json.loads(payload.decode("utf-8"))
    if not isinstance(values, dict):
        raise BackupError("Invalid backup secret payload")
    required = ("RESTIC_PASSWORD", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
    missing = [key for key in required if not str(values.get(key, "")).strip()]
    if missing:
        raise BackupError(f"Backup credentials missing: {', '.join(missing)}")
    return {str(key): str(value) for key, value in values.items()}


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        raise BackupError("Backup is not configured. Run the configure command first.")
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not str(value.get("repository", "")).strip():
        raise BackupError(f"Invalid backup config: {CONFIG_PATH}")
    return value


def read_windows_clipboard_secret() -> str:
    if os.name != "nt":
        raise BackupError("Clipboard secret import is available on Windows only")
    command = ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            raise BackupError("Could not read the Windows clipboard")
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


def restic_path(config: dict[str, Any]) -> Path:
    configured = str(config.get("restic_path", "")).strip()
    if configured:
        candidate = Path(configured)
    elif os.name == "nt" and DEFAULT_RESTIC_WINDOWS.is_file():
        candidate = DEFAULT_RESTIC_WINDOWS
    else:
        discovered = shutil.which("restic")
        candidate = Path(discovered) if discovered else Path("restic")
    if not candidate.is_file():
        raise BackupError(f"restic executable not found: {candidate}")
    return candidate


def restic_environment(
    config: dict[str, Any],
    secrets: dict[str, str],
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(secrets)
    env["RESTIC_REPOSITORY"] = str(config["repository"])
    env.setdefault("AWS_DEFAULT_REGION", "auto")
    return env


def run_restic(
    args: list[str],
    *,
    capture: bool = False,
    check: bool = True,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    config = load_config()
    secrets = load_secrets()
    command = [str(restic_path(config)), *args]
    result = subprocess.run(
        command,
        cwd=cwd,
        env=restic_environment(config, secrets),
        text=True,
        capture_output=capture,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise BackupError(f"restic failed ({result.returncode}): {detail}")
    return result


def configure(
    repository_override: str | None = None,
    *,
    generate_password: bool = False,
    reuse_password: bool = False,
    reuse_access_key: bool = False,
    secret_from_clipboard: bool = False,
) -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    print("Crowley encrypted backup configuration")
    print("Secrets are sealed to this Windows user with DPAPI.")
    repository = (repository_override or "").strip()
    if repository:
        print(f"Restic repository URL: {repository}")
    else:
        repository = input(
            "Restic repository URL "
            "(s3:https://<ACCOUNT_ID>.r2.cloudflarestorage.com/<BUCKET>): "
        ).strip()
    if not repository.startswith("s3:https://"):
        raise BackupError("Expected an encrypted HTTPS S3 repository URL")
    existing_secrets: dict[str, str] = {}
    if reuse_password or reuse_access_key:
        existing_secrets = load_secrets()
    if reuse_access_key:
        access_key = existing_secrets["AWS_ACCESS_KEY_ID"]
        print("Reusing the previously saved R2 Access Key ID.")
    else:
        access_key = input("R2 Access Key ID: ").strip()
    if secret_from_clipboard:
        print("Reading R2 Secret Access Key from the Windows clipboard...")
        secret_key = read_windows_clipboard_secret().strip()
        print("Windows clipboard cleared.")
    else:
        secret_key = getpass.getpass("R2 Secret Access Key: ").strip()
    if len(access_key) != 32:
        raise BackupError(
            f"R2 Access Key ID should be 32 characters; received {len(access_key)}"
        )
    if len(secret_key) != 64:
        raise BackupError(
            f"R2 Secret Access Key should be 64 characters; received {len(secret_key)}"
        )
    print("R2 Secret Access Key received: 64 characters.")
    if reuse_password:
        restic_password = existing_secrets["RESTIC_PASSWORD"]
        print("Reusing the previously generated restic repository password.")
    elif generate_password:
        restic_password = secrets_module.token_urlsafe(32)
    else:
        restic_password = getpass.getpass("New/restored restic repository password: ")
        confirm = getpass.getpass("Confirm restic repository password: ")
        if restic_password != confirm:
            raise BackupError("Repository passwords do not match")
    if len(restic_password) < 20:
        raise BackupError("Use a repository password of at least 20 characters")
    if not access_key or not secret_key:
        raise BackupError("R2 credentials cannot be empty")

    config = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "restic_path": str(DEFAULT_RESTIC_WINDOWS),
        "host": socket.gethostname(),
        "configured_at": utc_now(),
        "schedule": {"backup_minutes": 60, "check_time": "03:00"},
    }
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    save_secrets(
        {
            "AWS_ACCESS_KEY_ID": access_key,
            "AWS_SECRET_ACCESS_KEY": secret_key,
            "RESTIC_PASSWORD": restic_password,
        }
    )
    print(f"Configured: {CONFIG_PATH}")
    print("")
    print("CRITICAL: Save these three items outside this laptop:")
    print("1. Repository URL")
    print("2. R2 Access Key ID + Secret Access Key")
    print("3. Restic repository password")
    print("Use a password manager plus one offline recovery copy.")
    if generate_password:
        print("")
        print("GENERATED RESTIC PASSWORD - SAVE THIS NOW:")
        print(restic_password)
        print("This password is not stored anywhere recoverable outside this Windows user.")
    return 0


def repository_initialized() -> bool:
    result = run_restic(["snapshots", "--json"], capture=True, check=False)
    if result.returncode == 0:
        return True
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if "unable to open config file" in combined or "repository does not exist" in combined:
        return False
    raise BackupError(combined.strip())


def init_repository() -> int:
    if repository_initialized():
        print("Restic repository already initialized.")
        return 0
    run_restic(["init"])
    print("Restic repository initialized.")
    return 0


def backup(tag: str) -> int:
    config = load_config()
    manifest = create_snapshot(source_db=database_path())
    result = run_restic(
        [
            "backup",
            "current",
            "--host",
            str(config.get("host") or socket.gethostname()),
            "--tag",
            "crowley",
            "--tag",
            tag,
            "--json",
        ],
        capture=True,
        cwd=STAGING_DIR.parent,
    )
    summary: dict[str, Any] = {}
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("message_type") == "summary":
            summary = item
    print(
        json.dumps(
            {
                "status": "ok",
                "created_at": manifest["created_at"],
                "database_sha256": manifest["database"]["sha256"],
                "table_counts": manifest["database"]["table_counts"],
                "snapshot_id": summary.get("snapshot_id"),
                "files_new": summary.get("files_new"),
                "data_added": summary.get("data_added"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def check_repository(read_data: bool) -> int:
    args = ["check"]
    if read_data:
        args.append("--read-data")
    run_restic(args)
    print("Crowley backup repository check passed.")
    return 0


def _find_manifest(target: Path) -> Path:
    manifests = sorted(target.rglob("manifest.json"))
    if len(manifests) != 1:
        raise BackupError(
            f"Expected exactly one restored manifest under {target}; found {len(manifests)}"
        )
    return manifests[0]


def restore_snapshot(snapshot: str, target: Path) -> None:
    result = run_restic(
        ["restore", snapshot, "--target", str(target), "--tag", "crowley"],
        capture=True,
        check=False,
    )
    if result.returncode == 0:
        return
    combined = f"{result.stdout}\n{result.stderr}"
    windows_timestamp_only = (
        os.name == "nt"
        and "failed to restore timestamp" in combined
        and "Summary: Restored" in combined
        and "Fatal: There were 1 errors" in combined
    )
    if not windows_timestamp_only:
        raise BackupError(
            f"restic restore failed ({result.returncode}): {combined.strip()}"
        )
    print(
        "WARNING: Windows refused a synthetic parent-directory timestamp; "
        "restored files will still be hash and SQLite integrity checked.",
        file=sys.stderr,
    )


def verify_restored_bundle(target: Path) -> dict[str, Any]:
    manifest_path = _find_manifest(target)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    db_path = manifest_path.parent / str(manifest["database"]["relative_path"])
    if not db_path.is_file():
        raise BackupError(f"Restored database missing: {db_path}")
    actual_hash = sha256_file(db_path)
    if actual_hash != manifest["database"]["sha256"]:
        raise BackupError("Restored database SHA-256 does not match manifest")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        counts = _table_counts(connection)
    finally:
        connection.close()
    if integrity.lower() != "ok":
        raise BackupError(f"Restored database integrity_check failed: {integrity}")
    return {
        "status": "ok",
        "manifest": str(manifest_path),
        "database": str(db_path),
        "sha256": actual_hash,
        "integrity_check": integrity,
        "table_counts": counts,
    }


def restore(snapshot: str, target: Path) -> int:
    target = target.expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise BackupError(f"Restore target must be empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    restore_snapshot(snapshot, target)
    result = verify_restored_bundle(target)
    print(json.dumps(result, indent=2, sort_keys=True))
    print("Live crowley.db was not changed.")
    return 0


def drill() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = DRILLS_DIR / stamp
    target.mkdir(parents=True, exist_ok=False)
    try:
        restore_snapshot("latest", target)
        result = verify_restored_bundle(target)
        result["drilled_at"] = utc_now()
        report_path = DRILLS_DIR / f"{stamp}.json"
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        print(f"Drill report: {report_path}")
    finally:
        shutil.rmtree(target, ignore_errors=True)
    return 0


def status() -> int:
    config = load_config()
    result = run_restic(["snapshots", "--json", "--tag", "crowley"], capture=True)
    snapshots = json.loads(result.stdout or "[]")
    latest = snapshots[-1] if snapshots else None
    print(
        json.dumps(
            {
                "repository": config["repository"],
                "configured": True,
                "snapshot_count": len(snapshots),
                "latest": latest,
                "scheduled_task": windows_schedule_status(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _write_windows_wrappers() -> tuple[Path, Path]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    python = Path(sys.executable).resolve()
    script = Path(__file__).resolve()
    backup_cmd = RUNTIME_DIR / "run-backup.cmd"
    check_cmd = RUNTIME_DIR / "run-check.cmd"
    backup_cmd.write_text(
        "@echo off\r\n"
        f'"{python}" "{script}" backup --tag scheduled '
        f'>> "{LOG_PATH}" 2>&1\r\n',
        encoding="utf-8",
    )
    check_cmd.write_text(
        "@echo off\r\n"
        f'"{python}" "{script}" check '
        f'>> "{LOG_PATH}" 2>&1\r\n',
        encoding="utf-8",
    )
    return backup_cmd, check_cmd


def install_windows_schedule() -> int:
    if os.name != "nt":
        raise BackupError("Windows scheduling is available on Windows only")
    load_config()
    load_secrets()
    backup_cmd, check_cmd = _write_windows_wrappers()
    commands = [
        [
            "schtasks",
            "/Create",
            "/TN",
            "Crowley Encrypted Backup",
            "/TR",
            str(backup_cmd),
            "/SC",
            "HOURLY",
            "/MO",
            "1",
            "/F",
        ],
        [
            "schtasks",
            "/Create",
            "/TN",
            "Crowley Backup Integrity Check",
            "/TR",
            str(check_cmd),
            "/SC",
            "DAILY",
            "/ST",
            "03:00",
            "/F",
        ],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise BackupError((result.stderr or result.stdout).strip())
    print("Installed hourly encrypted backup and daily repository check tasks.")
    return 0


def windows_schedule_status() -> dict[str, bool] | None:
    if os.name != "nt":
        return None
    result: dict[str, bool] = {}
    for name in ("Crowley Encrypted Backup", "Crowley Backup Integrity Check"):
        query = subprocess.run(
            ["schtasks", "/Query", "/TN", name],
            capture_output=True,
            text=True,
            check=False,
        )
        result[name] = query.returncode == 0
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    configure_parser = sub.add_parser(
        "configure",
        help="Interactively configure R2 and encrypted secrets.",
    )
    configure_parser.add_argument(
        "--repository",
        help="Pre-fill the non-secret restic repository URL.",
    )
    password_group = configure_parser.add_mutually_exclusive_group()
    password_group.add_argument(
        "--generate-password",
        action="store_true",
        help="Generate and display a strong restic password once after configuration.",
    )
    password_group.add_argument(
        "--reuse-password",
        action="store_true",
        help="Reuse the restic password from the existing DPAPI secret file.",
    )
    configure_parser.add_argument(
        "--reuse-access-key",
        action="store_true",
        help="Reuse the R2 Access Key ID from the existing DPAPI secret file.",
    )
    configure_parser.add_argument(
        "--secret-from-clipboard",
        action="store_true",
        help="Read the R2 Secret Access Key from Windows clipboard, then clear it.",
    )
    sub.add_parser("init", help="Initialize the configured restic repository.")
    snapshot = sub.add_parser("snapshot", help="Create a consistent local recovery bundle.")
    snapshot.add_argument("--db")
    snapshot.add_argument("--output")
    backup_parser = sub.add_parser("backup", help="Snapshot and upload Crowley state.")
    backup_parser.add_argument("--tag", default="manual")
    check = sub.add_parser("check", help="Check repository integrity.")
    check.add_argument("--read-data", action="store_true")
    restore_parser = sub.add_parser("restore", help="Restore to an isolated directory.")
    restore_parser.add_argument("--snapshot", default="latest")
    restore_parser.add_argument("--target", required=True)
    sub.add_parser("drill", help="Restore latest, verify it, then remove drill data.")
    sub.add_parser("status", help="Show snapshots and schedule state.")
    sub.add_parser("install-schedule", help="Install Windows backup tasks.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "configure":
            return configure(
                args.repository,
                generate_password=args.generate_password,
                reuse_password=args.reuse_password,
                reuse_access_key=args.reuse_access_key,
                secret_from_clipboard=args.secret_from_clipboard,
            )
        if args.command == "init":
            return init_repository()
        if args.command == "snapshot":
            manifest = create_snapshot(
                source_db=database_path(args.db),
                output_dir=Path(args.output).resolve() if args.output else STAGING_DIR,
            )
            print(json.dumps(manifest, indent=2, sort_keys=True))
            return 0
        if args.command == "backup":
            return backup(args.tag)
        if args.command == "check":
            return check_repository(args.read_data)
        if args.command == "restore":
            return restore(args.snapshot, Path(args.target))
        if args.command == "drill":
            return drill()
        if args.command == "status":
            return status()
        if args.command == "install-schedule":
            return install_windows_schedule()
    except (BackupError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
