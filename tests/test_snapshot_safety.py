"""System-level sentinel tests for the shared snapshot safety contract (R1)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import crowley_backup as backup
from scripts import db_provenance as provenance


class SnapshotSafetySystemTests(unittest.TestCase):
    def _live_db(self, repo: Path) -> Path:
        data = repo / "data"
        data.mkdir(parents=True)
        path = data / "crowley.db"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE memory_items (id INTEGER PRIMARY KEY, content TEXT)"
        )
        connection.execute("INSERT INTO memory_items(content) VALUES ('live-secret')")
        connection.execute("PRAGMA user_version = 7")
        connection.commit()
        connection.close()
        return path

    def _sentinels(self, repo: Path, artifacts: Path, external: Path) -> dict[str, Path]:
        mapping = {
            "repo_root": repo / "REPO_ROOT_SENTINEL.txt",
            "git": (repo / ".git" / "GIT_SENTINEL.txt"),
            "env": repo / ".env",
            "venv": (repo / "venv" / "VENV_SENTINEL.txt"),
            "db_parent": (repo / "data" / "DB_PARENT_SENTINEL.txt"),
            "artifacts_root": artifacts / "ARTIFACTS_ROOT_SENTINEL.txt",
            "prior_bundle": artifacts / "prior_bundle" / "PRIOR_SENTINEL.txt",
            "external": external / "EXTERNAL_SENTINEL.txt",
        }
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        (repo / "venv").mkdir(parents=True, exist_ok=True)
        (artifacts / "prior_bundle").mkdir(parents=True, exist_ok=True)
        external.mkdir(parents=True, exist_ok=True)
        for key, path in mapping.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"sentinel:{key}", encoding="utf-8")
        return mapping

    def _assert_sentinels(self, sentinels: dict[str, Path]) -> None:
        for key, path in sentinels.items():
            self.assertTrue(path.is_file(), msg=f"missing sentinel {key}")
            self.assertEqual(path.read_text(encoding="utf-8"), f"sentinel:{key}")

    def test_public_paths_reject_dangerous_targets_and_preserve_sentinels(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            repo = base / "repo"
            artifacts = repo / ".crowley" / "artifacts"
            staging_root = repo / ".crowley" / "backup" / "staging"
            artifacts.mkdir(parents=True)
            staging_root.mkdir(parents=True)
            live = self._live_db(repo)
            external = base / "outside_existing"
            sentinels = self._sentinels(repo, artifacts, external)
            before = backup.sha256_file(live)

            with mock.patch.multiple(
                backup,
                ROOT=repo.resolve(),
                ARTIFACTS_DIR=artifacts.resolve(),
                RUNTIME_DIR=(repo / ".crowley" / "backup").resolve(),
                STAGING_DIR=(staging_root / "current").resolve(),
            ), mock.patch.object(provenance, "ROOT", repo.resolve()), mock.patch.object(
                provenance, "ARTIFACTS_DIR", artifacts.resolve()
            ):
                dangerous = [
                    repo,
                    repo / ".git",
                    repo / "venv",
                    live.parent,
                    artifacts,
                    staging_root,
                    external,
                ]
                for target in dangerous:
                    with self.assertRaises(backup.BackupError):
                        backup.create_snapshot(
                            source_db=live,
                            output_dir=target,
                            replace=True,
                        )
                    with self.assertRaises(provenance.ProvenanceError):
                        provenance.preserve(
                            source_db=live,
                            snapshot_dir=target,
                            provenance_path=artifacts / "status.json",
                        )

                # Prior bundle: rejected without replace; sentinel survives
                with self.assertRaises(backup.BackupError):
                    backup.create_snapshot(
                        source_db=live,
                        output_dir=artifacts / "prior_bundle",
                        replace=False,
                    )
                self.assertEqual(
                    sentinels["prior_bundle"].read_text(encoding="utf-8"),
                    "sentinel:prior_bundle",
                )

                self._assert_sentinels(sentinels)

                # Normal unique managed snapshot succeeds without mutating live DB
                unique = artifacts / "bundle_ok"
                manifest = backup.create_snapshot(
                    source_db=live, output_dir=unique, replace=False
                )
                self.assertEqual(manifest["database"]["quick_check"].lower(), "ok")
                self.assertEqual(
                    manifest["database"]["integrity_check"].lower(), "ok"
                )
                self.assertTrue((unique / "state" / "crowley.db").is_file())
                self.assertNotIn(
                    "live-secret",
                    (unique / "manifest.json").read_text(encoding="utf-8"),
                )

                report = provenance.preserve(
                    source_db=live,
                    snapshot_dir=artifacts / "bundle_preserve",
                    provenance_path=artifacts / "preserve_status.json",
                )
                self.assertTrue(report["schema_unchanged"])
                self.assertEqual(report["provenance"]["sqlite"]["user_version"], 7)

                # Default no-output path allocates under artifacts
                with mock.patch.object(
                    backup, "unique_bundle_dir", return_value=artifacts / "auto_unique"
                ):
                    auto = backup.create_snapshot(source_db=live)
                self.assertTrue(
                    (artifacts / "auto_unique" / "manifest.json").is_file()
                )
                self.assertEqual(
                    auto["bundle_dir"], str((artifacts / "auto_unique").resolve())
                )

            self._assert_sentinels(sentinels)
            self.assertEqual(backup.sha256_file(live), before)

    def test_stage_failure_does_not_clobber_prior_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            artifacts = repo / ".crowley" / "artifacts"
            artifacts.mkdir(parents=True)
            live = self._live_db(repo)
            prior = artifacts / "prior"
            with mock.patch.multiple(
                backup,
                ROOT=repo.resolve(),
                ARTIFACTS_DIR=artifacts.resolve(),
                RUNTIME_DIR=(repo / ".crowley" / "backup").resolve(),
            ):
                backup.create_snapshot(source_db=live, output_dir=prior)
                marker = prior / "PRIOR_OK.txt"
                marker.write_text("keep", encoding="utf-8")
                before_manifest = (prior / "manifest.json").read_text(encoding="utf-8")
                before_sha = (prior / "manifest.sha256").read_text(encoding="utf-8")

                def boom(*_a, **_k):
                    raise backup.BackupError("injected build failure")

                with mock.patch.object(backup, "_build_snapshot_tree", side_effect=boom):
                    with self.assertRaises(backup.BackupError):
                        backup.create_snapshot(
                            source_db=live, output_dir=prior, replace=True
                        )
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
                self.assertEqual(
                    (prior / "manifest.json").read_text(encoding="utf-8"),
                    before_manifest,
                )
                self.assertEqual(
                    (prior / "manifest.sha256").read_text(encoding="utf-8"),
                    before_sha,
                )
                partials = list(artifacts.glob(".partial-*"))
                self.assertEqual(partials, [])

    def test_refuses_preexisting_partial_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            artifacts = repo / ".crowley" / "artifacts"
            artifacts.mkdir(parents=True)
            live = self._live_db(repo)
            final = artifacts / "bundle"
            # Predictable collision name used by older implementations
            partial = artifacts / f".partial-{final.name}-deadbeef"
            partial.mkdir()
            marker = partial / "STAGING_SENTINEL.txt"
            marker.write_text("do-not-delete", encoding="utf-8")
            with mock.patch.multiple(
                backup,
                ROOT=repo.resolve(),
                ARTIFACTS_DIR=artifacts.resolve(),
                RUNTIME_DIR=(repo / ".crowley" / "backup").resolve(),
            ), mock.patch(
                "scripts.crowley_backup.secrets_module.token_hex",
                return_value="deadbeef",
            ):
                with self.assertRaisesRegex(backup.BackupError, "staging path"):
                    backup.create_snapshot(source_db=live, output_dir=final)
            self.assertEqual(marker.read_text(encoding="utf-8"), "do-not-delete")
            self.assertTrue(partial.is_dir())

    def test_manifest_checksum_covers_manifest_json_not_just_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            artifacts = repo / ".crowley" / "artifacts"
            artifacts.mkdir(parents=True)
            live = self._live_db(repo)
            out = artifacts / "hashed"
            with mock.patch.multiple(
                backup,
                ROOT=repo.resolve(),
                ARTIFACTS_DIR=artifacts.resolve(),
                RUNTIME_DIR=(repo / ".crowley" / "backup").resolve(),
            ):
                manifest = backup.create_snapshot(source_db=live, output_dir=out)
            file_sha = backup.sha256_file(out / "manifest.json")
            sidecar = (out / "manifest.sha256").read_text(encoding="utf-8").strip()
            self.assertEqual(manifest["manifest_sha256"], file_sha)
            self.assertEqual(sidecar, file_sha)
            self.assertNotEqual(manifest["manifest_sha256"], manifest["database"]["sha256"])

    def test_replace_requires_verified_crowley_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            artifacts = repo / ".crowley" / "artifacts"
            artifacts.mkdir(parents=True)
            live = self._live_db(repo)
            fake = artifacts / "not_a_bundle"
            fake.mkdir()
            (fake / "noise.txt").write_text("nope", encoding="utf-8")
            with mock.patch.multiple(
                backup,
                ROOT=repo.resolve(),
                ARTIFACTS_DIR=artifacts.resolve(),
                RUNTIME_DIR=(repo / ".crowley" / "backup").resolve(),
            ):
                with self.assertRaisesRegex(backup.BackupError, "verified Crowley"):
                    backup.create_snapshot(
                        source_db=live, output_dir=fake, replace=True
                    )
                self.assertEqual((fake / "noise.txt").read_text(encoding="utf-8"), "nope")

                real = artifacts / "real_bundle"
                first = backup.create_snapshot(source_db=live, output_dir=real)
                second = backup.create_snapshot(
                    source_db=live, output_dir=real, replace=True
                )
                self.assertTrue(backup.is_crowley_bundle(real))
                self.assertNotEqual(first["manifest_sha256"], second["manifest_sha256"])
                self.assertTrue((real / "manifest.sha256").is_file())


if __name__ == "__main__":
    unittest.main()
