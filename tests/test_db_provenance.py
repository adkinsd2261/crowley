"""Focused tests for V4.3.3R R1 read-only provenance and preserve workflow."""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import crowley_backup as backup
from scripts import db_provenance as provenance


class DbProvenanceTests(unittest.TestCase):
    def _database(self, root: Path) -> Path:
        path = root / "source.db"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE memory_items (id INTEGER PRIMARY KEY, content TEXT)"
        )
        connection.execute(
            "CREATE TABLE tickets (id INTEGER PRIMARY KEY, title TEXT)"
        )
        connection.execute(
            "CREATE INDEX idx_tickets_title ON tickets(title)"
        )
        connection.execute("INSERT INTO memory_items(content) VALUES ('secret-row')")
        connection.execute("INSERT INTO tickets(title) VALUES ('ticket')")
        connection.execute("PRAGMA user_version = 42")
        connection.commit()
        connection.close()
        return path

    def test_inspect_is_metadata_only_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            before = backup.sha256_file(source)

            report = provenance.inspect_database(source)

            self.assertEqual(report["exports_row_content"], False)
            self.assertEqual(report["mode"], "read_only")
            self.assertEqual(report["sqlite"]["user_version"], 42)
            self.assertEqual(report["sqlite"]["quick_check"].lower(), "ok")
            self.assertEqual(report["sqlite"]["integrity_check"].lower(), "ok")
            self.assertEqual(report["sqlite"]["table_counts"]["memory_items"], 1)
            self.assertIn("memory_items", report["sqlite"]["objects"]["table"])
            self.assertEqual(report["sqlite"]["objects"]["virtual_table"], [])
            self.assertIn("idx_tickets_title", report["sqlite"]["objects"]["index"])
            self.assertTrue(report["sqlite"]["schema_fingerprint"])
            self.assertIn("sqlite_vec", report["sqlite"])
            serialized = json.dumps(report)
            self.assertNotIn("secret-row", serialized)
            self.assertEqual(backup.sha256_file(source), before)

    def test_inspect_reports_unavailable_vec_without_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            before = backup.sha256_file(source)
            with mock.patch.object(
                provenance, "_try_load_sqlite_vec", return_value="forced_unavailable"
            ):
                report = provenance.inspect_database(source)
            self.assertTrue(
                report["sqlite"]["sqlite_vec"].startswith("unavailable:")
            )
            self.assertEqual(report["sqlite"]["table_counts"]["tickets"], 1)
            self.assertEqual(backup.sha256_file(source), before)

    def test_write_provenance_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            report = provenance.inspect_database(source)
            out = root / "artifacts" / "prov.json"
            path = provenance.write_provenance(
                report, output=out, source_db=source
            )
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["sqlite"]["table_counts"]["tickets"], 1)
            self.assertFalse(loaded["exports_row_content"])

    def test_rejects_destructive_snapshot_dir_and_output_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            artifacts = repo / ".crowley" / "artifacts"
            artifacts.mkdir(parents=True)
            data_dir = repo / "data"
            data_dir.mkdir()
            live = data_dir / "crowley.db"
            connection = sqlite3.connect(live)
            connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
            connection.commit()
            connection.close()
            before = backup.sha256_file(live)

            with mock.patch.multiple(
                backup,
                ROOT=repo.resolve(),
                ARTIFACTS_DIR=artifacts.resolve(),
                RUNTIME_DIR=(repo / ".crowley" / "backup").resolve(),
            ), mock.patch.object(provenance, "ROOT", repo.resolve()), mock.patch.object(
                provenance, "ARTIFACTS_DIR", artifacts.resolve()
            ):
                with self.assertRaisesRegex(provenance.ProvenanceError, "repository root"):
                    provenance.assert_safe_snapshot_dir(repo.resolve(), source_db=live)
                with self.assertRaisesRegex(provenance.ProvenanceError, "live database"):
                    provenance.assert_safe_snapshot_dir(data_dir.resolve(), source_db=live)
                with self.assertRaisesRegex(provenance.ProvenanceError, "strict descendant|artifacts"):
                    provenance.assert_safe_snapshot_dir(
                        repo / "not-artifacts", source_db=live
                    )
                with self.assertRaisesRegex(provenance.ProvenanceError, "collides"):
                    provenance.assert_safe_output_path(live, source_db=live)
                with self.assertRaisesRegex(provenance.ProvenanceError, "artifacts"):
                    provenance.assert_safe_output_path(
                        repo / "out.json", source_db=live
                    )
                with self.assertRaisesRegex(provenance.ProvenanceError, "live database"):
                    provenance.preserve(
                        source_db=live,
                        snapshot_dir=data_dir,
                        provenance_path=artifacts / "status.json",
                    )
                with mock.patch("sys.stdout", new_callable=io.StringIO), mock.patch(
                    "sys.stderr", new_callable=io.StringIO
                ):
                    rc = provenance.main(
                        [
                            "inspect",
                            "--db",
                            str(live),
                            "--output",
                            str(live),
                        ]
                    )
                self.assertEqual(rc, 1)

                ok_dir = provenance.assert_safe_snapshot_dir(
                    artifacts / "prechange", source_db=live
                )
                ok_out = provenance.assert_safe_output_path(
                    artifacts / "status.json", source_db=live
                )
                self.assertEqual(ok_dir, (artifacts / "prechange").resolve())
                self.assertEqual(ok_out, (artifacts / "status.json").resolve())

            self.assertEqual(backup.sha256_file(live), before)

    def test_rejects_existing_external_dir_and_preserves_prior_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            artifacts = repo / ".crowley" / "artifacts"
            artifacts.mkdir(parents=True)
            live = self._database(repo)

            # Unrelated existing directory outside the repo
            external = Path(tmp) / "unrelated_existing"
            external.mkdir()
            marker = external / "do-not-delete.txt"
            marker.write_text("keep-me", encoding="utf-8")

            with mock.patch.multiple(
                backup,
                ROOT=repo.resolve(),
                ARTIFACTS_DIR=artifacts.resolve(),
                RUNTIME_DIR=(repo / ".crowley" / "backup").resolve(),
            ), mock.patch.object(provenance, "ROOT", repo.resolve()), mock.patch.object(
                provenance, "ARTIFACTS_DIR", artifacts.resolve()
            ):
                with self.assertRaisesRegex(provenance.ProvenanceError, "already exists"):
                    provenance.assert_safe_snapshot_dir(external, source_db=live)
                with self.assertRaisesRegex(
                    provenance.ProvenanceError, "verified Crowley|strict descendants"
                ):
                    provenance.assert_safe_snapshot_dir(
                        external, source_db=live, replace=True
                    )
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep-me")

                # Artifacts root itself must never be a replace target
                with self.assertRaisesRegex(provenance.ProvenanceError, "managed bundle root"):
                    provenance.assert_safe_snapshot_dir(
                        artifacts, source_db=live, replace=True
                    )
                root_marker = artifacts / "artifacts-root-marker.txt"
                root_marker.write_text("root-keep", encoding="utf-8")
                self.assertEqual(root_marker.read_text(encoding="utf-8"), "root-keep")

                # Prior snapshot must stay intact; public preserve never replaces
                prior = artifacts / "prechange_prior"
                prior.mkdir()
                prior_marker = prior / "prior-evidence.txt"
                prior_marker.write_text("evidence", encoding="utf-8")
                with self.assertRaisesRegex(provenance.ProvenanceError, "already exists"):
                    provenance.assert_safe_snapshot_dir(prior, source_db=live)
                with self.assertRaisesRegex(provenance.ProvenanceError, "verified Crowley"):
                    provenance.assert_safe_snapshot_dir(
                        prior, source_db=live, replace=True
                    )
                self.assertEqual(prior_marker.read_text(encoding="utf-8"), "evidence")

                fresh = artifacts / "prechange_fresh"
                report = provenance.preserve(
                    source_db=live,
                    snapshot_dir=fresh,
                    provenance_path=artifacts / "status.json",
                )
                self.assertTrue(report["schema_unchanged"])
                self.assertTrue(report["snapshot"]["manifest_sha256"])
                self.assertTrue((fresh / "state" / "crowley.db").is_file())
                self.assertTrue((fresh / "manifest.sha256").is_file())
                self.assertEqual(prior_marker.read_text(encoding="utf-8"), "evidence")
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep-me")
                self.assertEqual(root_marker.read_text(encoding="utf-8"), "root-keep")

    def test_preserve_snapshot_integrity_and_live_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            before = backup.sha256_file(source)
            snap = root / "prechange"
            status_path = root / "preserve_status.json"

            report = provenance.preserve(
                source_db=source,
                snapshot_dir=snap,
                provenance_path=status_path,
            )

            self.assertTrue(report["schema_unchanged"])
            self.assertTrue(report["live_file_unchanged"])
            self.assertEqual(report["live_sha256_before"], before)
            self.assertEqual(report["live_sha256_after"], before)
            self.assertEqual(report["snapshot"]["integrity_check"].lower(), "ok")
            self.assertEqual(report["snapshot"]["quick_check"].lower(), "ok")
            self.assertTrue((snap / "state" / "crowley.db").is_file())
            self.assertTrue(status_path.is_file())
            self.assertEqual(backup.sha256_file(source), before)

            # Snapshot holds data; provenance status must not embed row payloads
            status_text = status_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-row", status_text)

    def test_cli_inspect_and_preserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            inspect_out = root / "inspect.json"
            snap = root / "snap"
            preserve_out = root / "preserve.json"

            with mock.patch("sys.stdout", new_callable=io.StringIO):
                rc = provenance.main(
                    ["inspect", "--db", str(source), "--output", str(inspect_out)]
                )
            self.assertEqual(rc, 0)
            self.assertTrue(inspect_out.is_file())

            before = backup.sha256_file(source)
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                rc = provenance.main(
                    [
                        "preserve",
                        "--db",
                        str(source),
                        "--snapshot-dir",
                        str(snap),
                        "--output",
                        str(preserve_out),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertTrue(preserve_out.is_file())
            self.assertEqual(backup.sha256_file(source), before)


if __name__ == "__main__":
    unittest.main()
