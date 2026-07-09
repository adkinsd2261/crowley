#!/usr/bin/env python3
"""V4.1 — read-only secret hygiene audit tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import security_hygiene  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402


RAW_SK = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"
RAW_BEARER = "Bearer super-secret-token-here-abc123"


class SecretHygieneUnitTests(unittest.TestCase):
    def test_scan_text_reports_redacted_excerpts_only(self) -> None:
        findings = security_hygiene.scan_text_for_secrets(
            f"token={RAW_SK} and auth {RAW_BEARER}",
            source="unit",
            field="content",
            record_id="row-1",
        )

        self.assertGreaterEqual(len(findings), 2)
        payload = [finding.to_dict() for finding in findings]
        rendered = str(payload)
        self.assertIn("[REDACTED-OPENAI-STYLE-KEY]", rendered)
        self.assertIn("[REDACTED-BEARER-TOKEN]", rendered)
        self.assertNotIn(RAW_SK, rendered)
        self.assertNotIn(RAW_BEARER, rendered)


class SecretHygieneReportTests(IsolatedDbTestCase):
    def _insert_memory(self, content: str, summary: str = "Secret hygiene probe") -> int:
        conn = crowley.connect_db()
        try:
            now = crowley._now_iso()
            project = crowley.get_active_project()
            project_id = int(project["id"]) if project is not None else None
            cur = conn.execute(
                """
                INSERT INTO memory_items (
                    created_at, updated_at, project_id, memory_type, content,
                    summary, importance, source, pinned, status, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    now,
                    project_id,
                    "event",
                    content,
                    summary,
                    2,
                    "manual",
                    0,
                    "active",
                    1.0,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def test_report_detects_memory_item_secret_without_leaking_value(self) -> None:
        memory_id = self._insert_memory(f"Operator pasted {RAW_SK} by mistake.")
        report = security_hygiene.secret_hygiene_report(include_logs=False)

        self.assertEqual(report["status"], "ok")
        self.assertTrue(report["read_only"])
        findings = report["findings"]
        self.assertTrue(any(item["record_id"] == str(memory_id) for item in findings))
        rendered = str(report)
        self.assertIn("[REDACTED-OPENAI-STYLE-KEY]", rendered)
        self.assertNotIn(RAW_SK, rendered)

    def test_report_is_read_only_for_passed_connection(self) -> None:
        self._insert_memory(f"Authorization header leaked: {RAW_BEARER}")
        conn = crowley.connect_db()
        try:
            before = conn.total_changes
            report = security_hygiene.secret_hygiene_report(
                conn=conn,
                include_logs=False,
            )
            after = conn.total_changes
        finally:
            conn.close()

        self.assertGreaterEqual(int(report["counts"]["total"]), 1)
        self.assertEqual(after, before)

    def test_report_scans_explicit_log_paths_with_redaction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="crowley-secret-hygiene-") as tmp:
            log_path = Path(tmp) / "service.log"
            log_path.write_text(
                f"bridge started with Authorization: {RAW_BEARER}\n",
                encoding="utf-8",
            )
            report = security_hygiene.secret_hygiene_report(
                include_logs=True,
                log_paths=[log_path],
            )

        self.assertEqual(report["scanned"]["log_files"], 1)
        rendered = str(report)
        self.assertIn("[REDACTED-BEARER-TOKEN]", rendered)
        self.assertNotIn(RAW_BEARER, rendered)


if __name__ == "__main__":
    unittest.main()
