"""V3.9.12 #79 — portable terminal local CLI workflow."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from db_helpers import IsolatedDbTestCase  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ENV = {
    **dict(__import__("os").environ),
    "CROWLEY_TEST_MODE": "1",
    "CROWLEY_EMBED_PROVIDER": "off",
}


class PortableTerminalCliTests(IsolatedDbTestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "import_portable_writeback.py"), *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=ENV,
            check=False,
        )

    def test_export_script_prints_markdown(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "export_portable_packet.py"),
                "--surface",
                "chatgpt",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=ENV,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Crowley portable context packet", proc.stdout)

    def test_import_script_happy_path(self) -> None:
        fixture = FIXTURES / "portable_writeback_valid.json"
        proc = self._run(str(fixture))
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        self.assertIn("Session receipt: memory_item #", proc.stdout)
        self.assertIn("Saved sparks: 2", proc.stdout)
        self.assertIn("Skipped do_not_save: 2", proc.stdout)
        self.assertIn("Rejected sparks: 0", proc.stdout)

    def test_import_script_json_output(self) -> None:
        fixture = FIXTURES / "portable_writeback_valid.json"
        proc = self._run(str(fixture), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertIn("session_receipt_id", data)
        self.assertEqual(len(data["spark_ids"]), 2)

    def test_import_script_invalid_writeback(self) -> None:
        fixture = FIXTURES / "portable_writeback_invalid_spark.json"
        proc = self._run(str(fixture))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Import failed", proc.stderr)

    def test_import_script_parse_only(self) -> None:
        fixture = FIXTURES / "portable_writeback_valid.json"
        proc = self._run(str(fixture), "--parse-only")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("valid", proc.stdout.lower())

    def test_import_script_missing_file(self) -> None:
        proc = self._run("does-not-exist.json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not found", proc.stderr.lower())

    def test_import_script_stdin(self) -> None:
        payload = (FIXTURES / "portable_writeback_valid.json").read_text()
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "import_portable_writeback.py"),
                "-",
            ],
            input=payload,
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=ENV,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Saved sparks: 2", proc.stdout)
