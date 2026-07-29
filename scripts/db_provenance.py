#!/usr/bin/env python3
"""Read-only Crowley database metadata inspection and R1 preserve workflow.

Does not export row contents. Does not call setup_db or mutate the live database.
Reuses scripts.crowley_backup for online snapshots and checksum helpers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

try:
    from scripts import crowley_backup as backup
except ImportError:  # pragma: no cover - script execution fallback
    import crowley_backup as backup  # type: ignore

ROOT = backup.ROOT
ARTIFACTS_DIR = ROOT / ".crowley" / "artifacts"
PROVENANCE_SCHEMA = 1


class ProvenanceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def assert_safe_output_path(
    output: Path,
    *,
    source_db: Path,
    root: Path | None = None,
) -> Path:
    """Reject outputs that collide with the live DB or escape artifact containment."""
    target = output.expanduser().resolve()
    source = source_db.expanduser().resolve()
    root_path = (root or ROOT).expanduser().resolve()
    artifacts = (root_path / ".crowley" / "artifacts").resolve()

    if target == source:
        raise ProvenanceError("--output collides with the live database path")
    try:
        if source.exists() and target.exists() and target.samefile(source):
            raise ProvenanceError("--output collides with the live database path")
    except OSError:
        pass
    if target.name.lower() == source.name.lower() and target.parent == source.parent:
        raise ProvenanceError("--output collides with the live database path")
    if target == root_path:
        raise ProvenanceError("--output cannot be the repository root")
    if target == artifacts:
        raise ProvenanceError("--output cannot be the managed artifacts root")

    if _is_relative_to(target, root_path):
        if not _is_relative_to(target, artifacts):
            raise ProvenanceError(
                "--output inside the repository must be under .crowley/artifacts"
            )
    return target


def assert_safe_snapshot_dir(
    snapshot_dir: Path,
    *,
    source_db: Path,
    root: Path | None = None,
    replace: bool = False,
) -> Path:
    """Delegate fail-closed snapshot destination policy to crowley_backup."""
    # Keep root patchability for tests by temporarily aligning backup roots when needed.
    try:
        return backup.assert_safe_snapshot_output(
            snapshot_dir, source_db=source_db, replace=replace
        )
    except backup.BackupError as exc:
        raise ProvenanceError(str(exc)) from exc


def unique_snapshot_dir(prefix: str = "prechange") -> Path:
    """Return a new non-existing path under .crowley/artifacts with a UTC stamp."""
    try:
        return backup.unique_bundle_dir(prefix)
    except backup.BackupError as exc:
        raise ProvenanceError(str(exc)) from exc


def _try_load_sqlite_vec(connection: sqlite3.Connection) -> str | None:
    """Load sqlite-vec when installed so vec0 virtual tables are readable.

    Returns None on success, or a short reason string when unavailable.
    Does not import crowley (avoids setup_db / live mutation).
    """
    try:
        import sqlite_vec
    except ImportError as exc:
        return f"import_error: {exc}"
    if not hasattr(connection, "enable_load_extension"):
        return "connection_cannot_load_extensions"
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
    except (AttributeError, OSError, sqlite3.Error) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _connect_readonly(db_path: Path) -> tuple[sqlite3.Connection, str | None]:
    if not db_path.is_file():
        raise ProvenanceError(f"Database not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    vec_status = _try_load_sqlite_vec(connection)
    return connection, vec_status


def _schema_objects(connection: sqlite3.Connection) -> dict[str, Any]:
    objects: dict[str, Any] = {
        "table": [],
        "virtual_table": [],
        "index": [],
        "trigger": [],
        "view": [],
    }
    rows = connection.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    for obj_type, name, sql in rows:
        key = str(obj_type)
        sql_text = (sql or "").upper()
        if key == "table" and "VIRTUAL TABLE" in sql_text:
            objects["virtual_table"].append(str(name))
            objects["table"].append(str(name))
        elif key in objects:
            objects[key].append(str(name))
    return objects


def _table_column_fingerprint(connection: sqlite3.Connection, tables: list[str]) -> str:
    """Hash of table + column metadata only (no row values)."""
    digest = hashlib.sha256()
    for table in tables:
        digest.update(table.encode("utf-8"))
        digest.update(b"\0")
        columns = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        for col in columns:
            # cid, name, type, notnull, dflt_value, pk — schema only
            digest.update("|".join("" if part is None else str(part) for part in col).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def _all_table_counts(
    connection: sqlite3.Connection,
    tables: list[str],
) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for table in tables:
        try:
            counts[table] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
        except sqlite3.Error:
            # Virtual tables (e.g. vec0) may be unreadable without their extension.
            counts[table] = None
    return counts


def inspect_database(db_path: Path) -> dict[str, Any]:
    """Return metadata-only provenance for a SQLite database.

    Counts are included (not row payloads). No SELECT of content columns.
    """
    resolved = db_path.expanduser().resolve()
    stat = resolved.stat()
    connection, vec_status = _connect_readonly(resolved)
    try:
        objects = _schema_objects(connection)
        tables = objects["table"]
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        integrity_check = str(
            connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        schema_fingerprint = _table_column_fingerprint(connection, tables)
        table_counts = _all_table_counts(connection, tables)
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    finally:
        connection.close()

    return {
        "schema_version": PROVENANCE_SCHEMA,
        "inspected_at": utc_now(),
        "mode": "read_only",
        "exports_row_content": False,
        "file": {
            "path": str(resolved),
            "size_bytes": stat.st_size,
            "mtime_utc": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "sha256": backup.sha256_file(resolved),
        },
        "sqlite": {
            "user_version": user_version,
            "journal_mode": journal_mode,
            "page_count": page_count,
            "page_size": page_size,
            "quick_check": quick_check,
            "integrity_check": integrity_check,
            "schema_fingerprint": schema_fingerprint,
            "objects": objects,
            "table_counts": table_counts,
            "sqlite_vec": "loaded" if vec_status is None else f"unavailable:{vec_status}",
        },
        "repository": {
            "git_commit": backup._git("rev-parse", "HEAD"),
            "git_branch": backup._git("branch", "--show-current"),
            "git_dirty": bool(backup._git("status", "--porcelain")),
        },
        "note": (
            "Checkpointed recovery tooling is inventoried separately; "
            "this artifact is not a recovery lock."
        ),
    }


def write_provenance(
    report: dict[str, Any],
    *,
    output: Path | None = None,
    source_db: Path | None = None,
) -> Path:
    if output is None:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = ARTIFACTS_DIR / f"db_provenance_{stamp}.json"
    else:
        if source_db is None:
            raise ProvenanceError("--output requires a source database for path checks")
        output = assert_safe_output_path(output, source_db=source_db)
        output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def verify_snapshot_integrity(snapshot_db: Path) -> str:
    connection, _vec_status = _connect_readonly(snapshot_db)
    try:
        result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()
    if result.lower() != "ok":
        raise ProvenanceError(f"Snapshot integrity_check failed: {result}")
    return result


def preserve(
    *,
    source_db: Path,
    snapshot_dir: Path,
    provenance_path: Path | None = None,
) -> dict[str, Any]:
    """Inspect live DB, create online snapshot, integrity-check copy, prove schema stable.

    Public R1 path is immutable: never replaces an existing snapshot destination.
    Uses read-only opens only. Concurrent writers (e.g. a running bus) may change the
    live file bytes or row counts; those are reported. Schema fingerprint / user_version
    must not change during this workflow. Fixture tests prove the tool itself does not
    mutate an idle database.
    """
    source = source_db.expanduser().resolve()
    if provenance_path is not None:
        provenance_path = assert_safe_output_path(provenance_path, source_db=source)

    before = inspect_database(source)
    before_hash = before["file"]["sha256"]
    before_fingerprint = before["sqlite"]["schema_fingerprint"]
    before_user_version = before["sqlite"]["user_version"]

    try:
        manifest = backup.create_snapshot(
            source_db=source,
            output_dir=snapshot_dir,
            replace=False,
        )
    except backup.BackupError as exc:
        raise ProvenanceError(str(exc)) from exc
    snapshot_dir = Path(manifest.get("bundle_dir") or snapshot_dir).resolve()
    snapshot_db = snapshot_dir / "state" / "crowley.db"
    integrity = str(
        manifest.get("database", {}).get("integrity_check")
        or verify_snapshot_integrity(snapshot_db)
    )

    after = inspect_database(source)
    after_hash = after["file"]["sha256"]
    if after["sqlite"]["schema_fingerprint"] != before_fingerprint:
        raise ProvenanceError("Schema fingerprint changed during preserve")
    if after["sqlite"]["user_version"] != before_user_version:
        raise ProvenanceError("PRAGMA user_version changed during preserve")

    report = {
        "schema_version": PROVENANCE_SCHEMA,
        "preserved_at": utc_now(),
        "schema_unchanged": True,
        "live_file_unchanged": before_hash == after_hash,
        "live_sha256_before": before_hash,
        "live_sha256_after": after_hash,
        "provenance": before,
        "snapshot": {
            "output_dir": str(snapshot_dir),
            "manifest_sha256_db": manifest["database"]["sha256"],
            "manifest_sha256": manifest.get("manifest_sha256"),
            "quick_check": manifest["database"]["quick_check"],
            "integrity_check": integrity,
            "replace": False,
        },
        "not_recovery_lock": True,
    }
    path = write_provenance(report, output=provenance_path, source_db=source)
    report["artifact_path"] = str(path)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_cmd = sub.add_parser(
        "inspect",
        help="Read-only metadata/provenance report (no row content).",
    )
    inspect_cmd.add_argument("--db", help="Database path (default: crowley.db / CROWLEY_DB_PATH)")
    inspect_cmd.add_argument("--output", help="Write JSON report to this path")

    preserve_cmd = sub.add_parser(
        "preserve",
        help="Inspect + online snapshot + integrity check; prove live DB unchanged.",
    )
    preserve_cmd.add_argument("--db", help="Database path")
    preserve_cmd.add_argument(
        "--snapshot-dir",
        required=True,
        help=(
            "New directory for the pre-change snapshot bundle. Must not already exist. "
            "Prefer a unique path under .crowley/artifacts."
        ),
    )
    preserve_cmd.add_argument("--output", help="Provenance/preserve status JSON path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db = backup.database_path(getattr(args, "db", None))

    try:
        if args.command == "inspect":
            report = inspect_database(db)
            path = write_provenance(
                report,
                output=Path(args.output) if args.output else None,
                source_db=db,
            )
            print(json.dumps({"artifact_path": str(path), "report": report}, indent=2))
            return 0

        if args.command == "preserve":
            report = preserve(
                source_db=db,
                snapshot_dir=Path(args.snapshot_dir),
                provenance_path=Path(args.output) if args.output else None,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
    except (ProvenanceError, backup.BackupError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
