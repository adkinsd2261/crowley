import json
import sqlite3
import tempfile
import unittest
from subprocess import CompletedProcess
from pathlib import Path
from unittest import mock

from scripts import crowley_backup as backup


class CrowleyBackupTests(unittest.TestCase):
    def _database(self, root: Path) -> Path:
        path = root / "source.db"
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE memory_items (id INTEGER PRIMARY KEY, content TEXT)"
        )
        connection.execute(
            "CREATE TABLE tickets (id INTEGER PRIMARY KEY, title TEXT)"
        )
        connection.execute("INSERT INTO memory_items(content) VALUES ('memory')")
        connection.execute("INSERT INTO tickets(title) VALUES ('ticket')")
        connection.commit()
        connection.close()
        return path

    def test_online_snapshot_is_consistent_and_manifested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            output = root / "snapshot"
            manifest = backup.create_snapshot(source_db=source, output_dir=output)

            self.assertEqual(manifest["database"]["quick_check"], "ok")
            self.assertEqual(manifest["database"]["table_counts"]["memory_items"], 1)
            self.assertEqual(manifest["database"]["table_counts"]["tickets"], 1)
            self.assertTrue((output / "state" / "crowley.db").is_file())
            self.assertTrue((output / "manifest.json").is_file())
            self.assertIn(".env", manifest["excluded_secrets"])

    def test_verify_restored_bundle_detects_valid_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            bundle = root / "restored" / "host" / "current"
            backup.create_snapshot(source_db=source, output_dir=bundle)

            result = backup.verify_restored_bundle(root / "restored")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["integrity_check"], "ok")
            self.assertEqual(result["table_counts"]["tickets"], 1)

    def test_verify_restored_bundle_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            bundle = root / "restored" / "current"
            backup.create_snapshot(source_db=source, output_dir=bundle)
            manifest = json.loads((bundle / "manifest.json").read_text())
            manifest["database"]["sha256"] = "0" * 64
            (bundle / "manifest.json").write_text(json.dumps(manifest))

            with self.assertRaises(backup.BackupError):
                backup.verify_restored_bundle(root / "restored")

    @unittest.skipUnless(backup.os.name == "nt", "DPAPI is Windows-only")
    def test_dpapi_round_trip(self):
        secret = b'{"RESTIC_PASSWORD":"not-printed"}'
        protected = backup._dpapi(secret, decrypt=False)
        self.assertNotEqual(protected, secret)
        self.assertEqual(backup._dpapi(protected, decrypt=True), secret)

    @unittest.skipUnless(
        backup.os.name == "nt" and backup.DEFAULT_RESTIC_WINDOWS.is_file(),
        "Windows restic installation is required",
    )
    def test_local_restic_backup_check_and_drill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self._database(root)
            runtime = root / "runtime"
            config_path = runtime / "config.json"
            secrets_path = runtime / "secrets.dpapi"
            staging = runtime / "staging" / "current"
            drills = runtime / "drills"
            repository = root / "repository"

            with mock.patch.multiple(
                backup,
                ROOT=root,
                RUNTIME_DIR=runtime,
                CONFIG_PATH=config_path,
                SECRETS_PATH=secrets_path,
                STAGING_DIR=staging,
                DRILLS_DIR=drills,
                LOG_PATH=runtime / "backup.log",
            ), mock.patch.dict(
                backup.os.environ,
                {"CROWLEY_DB_PATH": str(source)},
                clear=False,
            ):
                runtime.mkdir(parents=True)
                config_path.write_text(
                    json.dumps(
                        {
                            "repository": str(repository),
                            "restic_path": str(backup.DEFAULT_RESTIC_WINDOWS),
                            "host": "test-host",
                        }
                    ),
                    encoding="utf-8",
                )
                backup.save_secrets(
                    {
                        "RESTIC_PASSWORD": "test-only-restic-password",
                        "AWS_ACCESS_KEY_ID": "test",
                        "AWS_SECRET_ACCESS_KEY": "test",
                    }
                )

                backup.init_repository()
                backup.backup("test")
                backup.check_repository(read_data=True)
                backup.drill()

                reports = list(drills.glob("*.json"))
                self.assertEqual(len(reports), 1)
                report = json.loads(reports[0].read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "ok")
                self.assertEqual(report["integrity_check"], "ok")
                self.assertEqual(report["table_counts"]["memory_items"], 1)
                self.assertFalse(any(path.is_dir() for path in drills.iterdir()))

    def test_restic_environment_does_not_mutate_process_environment(self):
        with mock.patch.dict(backup.os.environ, {"KEEP": "yes"}, clear=True):
            result = backup.restic_environment(
                {"repository": "local:test"},
                {
                    "RESTIC_PASSWORD": "secret",
                    "AWS_ACCESS_KEY_ID": "id",
                    "AWS_SECRET_ACCESS_KEY": "key",
                },
            )
            self.assertEqual(result["RESTIC_REPOSITORY"], "local:test")
            self.assertEqual(result["KEEP"], "yes")
            self.assertNotIn("RESTIC_REPOSITORY", backup.os.environ)

    @mock.patch("scripts.crowley_backup.run_restic")
    @mock.patch("scripts.crowley_backup.create_snapshot")
    @mock.patch("scripts.crowley_backup.load_config")
    def test_backup_uses_portable_archive_root(self, load_config, create, run):
        load_config.return_value = {"host": "test-host"}
        create.return_value = {
            "created_at": "2026-07-28T00:00:00+00:00",
            "database": {"sha256": "abc", "table_counts": {"tickets": 2}},
        }
        run.return_value = CompletedProcess(
            args=["restic"],
            returncode=0,
            stdout='{"message_type":"summary","snapshot_id":"snapshot"}\n',
            stderr="",
        )

        backup.backup("manual")

        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["backup", "current"])
        self.assertEqual(run.call_args.kwargs["cwd"], backup.STAGING_DIR.parent)
        self.assertNotIn(str(backup.STAGING_DIR), args)

    @mock.patch("scripts.crowley_backup.run_restic")
    def test_restore_allows_only_windows_parent_timestamp_warning(self, run):
        run.return_value = CompletedProcess(
            args=["restic"],
            returncode=1,
            stdout="Summary: Restored 7 / 8 files/dirs",
            stderr=(
                'failed to restore timestamp of "C:\\\\Users": Access is denied.\n'
                "Fatal: There were 1 errors"
            ),
        )
        with mock.patch.object(backup.os, "name", "nt"):
            backup.restore_snapshot("latest", Path("target"))

    @mock.patch("scripts.crowley_backup.run_restic")
    def test_restore_rejects_other_restic_errors(self, run):
        run.return_value = CompletedProcess(
            args=["restic"],
            returncode=1,
            stdout="",
            stderr="Fatal: pack file is missing",
        )
        with self.assertRaises(backup.BackupError):
            backup.restore_snapshot("latest", Path("target"))


if __name__ == "__main__":
    unittest.main()
