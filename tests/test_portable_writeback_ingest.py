"""V3.9.12 #78 — ingest candidate sparks from portable terminal writeback."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import app as crowley_app  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class PortableWritebackIngestTests(IsolatedDbTestCase):
    def test_ingest_valid_writeback(self) -> None:
        raw = (FIXTURES / "portable_writeback_valid.json").read_text()
        before = crowley.list_memory_items(limit=50, status="all")[1]
        result = crowley.ingest_terminal_writeback(raw)
        self.assertEqual(result["status"], "ok")
        after = crowley.list_memory_items(limit=50, status="all")[1]
        self.assertEqual(after - before, 3)
        session_id = result["session_receipt_id"]
        assert session_id is not None
        spark_ids = result["spark_ids"]
        self.assertEqual(len(spark_ids), 2)
        self.assertEqual(len(result["skipped_do_not_save"]), 2)

        conn = crowley.connect_db()
        try:
            session = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?",
                (session_id,),
            ).fetchone()
            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(str(session["memory_type"]), "summary")
            self.assertEqual(str(session["source"]), crowley.PORTABLE_TERMINAL_SOURCE)
            self.assertEqual(int(session["pinned"]), 0)
            session_meta = crowley._memory_item_metadata(session)
            self.assertEqual(session_meta.get("surface"), "chatgpt")
            self.assertEqual(session_meta.get("model"), "gpt-4.1")
            self.assertEqual(session_meta.get("provider"), "openai")

            for spark_id in spark_ids:
                row = conn.execute(
                    "SELECT * FROM memory_items WHERE id = ?",
                    (spark_id,),
                ).fetchone()
                self.assertIsNotNone(row)
                assert row is not None
                self.assertEqual(str(row["status"]), crowley.PORTABLE_SPARK_STATUS)
                self.assertEqual(int(row["pinned"]), 0)
                meta = crowley._memory_item_metadata(row)
                self.assertTrue(meta.get("candidate"))
                self.assertIn("lane", meta)
                self.assertIn("why_keep", meta)
                self.assertIn("worth_reason", meta)
                self.assertIn("sensitivity", meta)
                self.assertEqual(meta.get("session_receipt_id"), session_id)
        finally:
            conn.close()

    def test_sensitive_sparks_staged_not_pinned(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        result = crowley.ingest_terminal_writeback(payload)
        self.assertEqual(result["status"], "ok")
        conn = crowley.connect_db()
        try:
            for spark_id in result["spark_ids"]:
                row = conn.execute(
                    "SELECT * FROM memory_items WHERE id = ?",
                    (spark_id,),
                ).fetchone()
                assert row is not None
                meta = crowley._memory_item_metadata(row)
                if meta.get("sensitivity") in {"sensitive", "high"}:
                    self.assertEqual(str(row["status"]), "staged")
                    self.assertEqual(int(row["pinned"]), 0)
                    self.assertFalse(crowley._is_canon_memory_row(row))
        finally:
            conn.close()

    def test_staged_sparks_not_in_retrieval(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        result = crowley.ingest_terminal_writeback(payload)
        self.assertEqual(result["status"], "ok")
        spark_ids = set(result["spark_ids"])
        hits = crowley.retrieve_memories("paste-ready packets under 12k chars", limit=20)
        hit_ids = {int(item["id"]) for item in hits}
        self.assertFalse(spark_ids & hit_ids)

    def test_invalid_writeback_does_not_mutate_memory(self) -> None:
        before = crowley.list_memory_items(limit=50, status="all")[1]
        raw = (FIXTURES / "portable_writeback_invalid_spark.json").read_text()
        result = crowley.ingest_terminal_writeback(raw)
        self.assertEqual(result["status"], "error")
        after = crowley.list_memory_items(limit=50, status="all")[1]
        self.assertEqual(before, after)

    def test_do_not_save_not_persisted(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        result = crowley.ingest_terminal_writeback(payload)
        self.assertEqual(result["status"], "ok")
        conn = crowley.connect_db()
        try:
            rows = conn.execute(
                """
                SELECT content FROM memory_items
                WHERE source = ?
                """,
                (crowley.PORTABLE_TERMINAL_SOURCE,),
            ).fetchall()
            blob = " ".join(str(row["content"]) for row in rows).lower()
            self.assertNotIn("draft joke about ollama", blob)
            self.assertNotIn("full chat transcript", blob)
        finally:
            conn.close()

    def test_api_ingest_endpoint(self) -> None:
        client = TestClient(crowley_app.app)
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        res = client.post(
            "/api/portable/writeback/ingest",
            json={"writeback": payload},
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("session_receipt_id", data)
        self.assertEqual(len(data["spark_ids"]), 2)

    def test_ingest_handoff_preserves_metadata(self) -> None:
        result = crowley.ingest_handoff(
            "cursor",
            "note",
            (
                "Mid-session note on portable terminal ingest wiring for ticket #78 "
                "with enough content to pass validation gates."
            ),
            metadata={"surface": "chatgpt", "model": "gpt-4.1", "ticket": 78},
        )
        self.assertEqual(result["status"], "ok")
        memory_id = result["memory_item_id"]
        assert memory_id is not None
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT metadata_json FROM memory_items WHERE id = ?",
                (memory_id,),
            ).fetchone()
            assert row is not None
            meta = crowley._memory_item_metadata(row)
            self.assertEqual(meta.get("surface"), "chatgpt")
            self.assertEqual(meta.get("model"), "gpt-4.1")
            self.assertEqual(meta.get("ticket"), 78)
            self.assertEqual(meta.get("handoff_type"), "note")
        finally:
            conn.close()
