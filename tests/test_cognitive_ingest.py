#!/usr/bin/env python3
"""V4 T5 — cognitive ingest endpoint and pipeline tests."""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import cognitive_ingest  # noqa: E402
import crowley  # noqa: E402
import spark_extraction  # noqa: E402
import sparks  # noqa: E402
import system_integrity  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

INGEST_TEXT = (
    "Crowley cognitive ingest should persist a receipt and extract durable sparks "
    "from school and therapy notes without blocking the HTTP response."
)


class CognitiveIngestTests(IsolatedDbTestCase):
    def tearDown(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        super().tearDown()

    def test_sync_mode_completes_extraction(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/cognitive/ingest?sync=1",
            json={"content": INGEST_TEXT, "source": "cursor"},
        )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        memory_item_id = data["memory_item_id"]
        extraction = data["extraction"]
        self.assertTrue(extraction["ok"], extraction)
        self.assertGreaterEqual(len(extraction["spark_ids"]), 1)

        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM sparks WHERE source_memory_item_id = ?",
                (memory_item_id,),
            ).fetchone()
            assert row is not None
            self.assertGreaterEqual(int(row["n"]), 1)
        finally:
            conn.close()

    def test_sync_mode_links_sparks_to_receipt(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/cognitive/ingest?sync=1",
            json={"content": INGEST_TEXT},
        )
        data = res.json()
        memory_item_id = int(data["memory_item_id"])
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT trust_state FROM sparks WHERE source_memory_item_id = ? LIMIT 1",
                (memory_item_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["trust_state"], "candidate")

    def test_receipt_created_synchronously_async(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        client = TestClient(crowley_app.app)
        with mock.patch.object(cognitive_ingest, "_spawn_extraction_worker") as spawn_mock:
            res = client.post("/api/cognitive/ingest", json={"content": INGEST_TEXT})
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["status"], "accepted")
        memory_item_id = data["memory_item_id"]
        spawn_mock.assert_called_once()

        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT id, metadata_json FROM memory_items WHERE id = ?",
                (memory_item_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        assert row is not None
        meta = json.loads(str(row["metadata_json"] or "{}"))
        self.assertEqual(meta.get("extraction_status"), "queued")

    def test_async_worker_updates_metadata_on_complete(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        with mock.patch.object(cognitive_ingest, "_spawn_extraction_worker"):
            result = cognitive_ingest.ingest_cognitive_content(INGEST_TEXT, sync=False)
        memory_item_id = int(result["memory_item_id"])
        conn = crowley.connect_db()
        try:
            project_id = crowley._active_project_id(conn)
        finally:
            conn.close()
        cognitive_ingest._run_extraction_pipeline(
            memory_item_id,
            INGEST_TEXT,
            project_id=project_id,
        )
        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT metadata_json FROM memory_items WHERE id = ?",
                (memory_item_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        meta = json.loads(str(row["metadata_json"] or "{}"))
        self.assertEqual(meta.get("extraction_status"), "complete")
        self.assertGreaterEqual(int(meta.get("spark_count", 0)), 1)

    def test_extraction_failure_preserves_receipt(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        client = TestClient(crowley_app.app)
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            with mock.patch(
                "spark_extraction.extract_sparks_from_text",
                return_value=mock.Mock(ok=False, sparks=[], errors=["bad batch"], attempts=2),
            ):
                res = client.post(
                    "/api/cognitive/ingest?sync=1",
                    json={"content": INGEST_TEXT},
                )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        memory_item_id = data["memory_item_id"]
        self.assertFalse(data["extraction"]["ok"])
        conn = crowley.connect_db()
        try:
            receipt = conn.execute(
                "SELECT id FROM memory_items WHERE id = ?",
                (memory_item_id,),
            ).fetchone()
            spark_count = conn.execute("SELECT COUNT(*) AS n FROM sparks").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(receipt)
        assert spark_count is not None
        self.assertEqual(int(spark_count["n"]), 0)

    def test_dispatch_invariant_blocks_cognitive_ingest(self) -> None:
        client = TestClient(crowley_app.app)
        broken = {
            "context": "dispatch",
            "ok": False,
            "violations": [{"invariant": "handoff_ticket_parity", "severity": "error"}],
        }
        with mock.patch.object(system_integrity, "run_invariant_checks", return_value=broken):
            res = client.post("/api/cognitive/ingest", json={"content": INGEST_TEXT})
        self.assertEqual(res.status_code, 428)
        self.assertEqual(res.json().get("error"), "invariant_violation")

    def test_no_partial_spark_insert_on_failure(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        memory_item_id = cognitive_ingest._save_cognitive_receipt(
            INGEST_TEXT,
            project_id=int(crowley.get_active_project()["id"]),
            source="cursor",
            metadata=None,
            extraction_status="processing",
        )
        assert memory_item_id is not None
        project_id = crowley._active_project_id(crowley.connect_db())
        calls = {"n": 0}

        def flaky_insert(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("simulated insert failure")
            return sparks.insert_spark(*args, **kwargs)

        fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "spark_extraction_valid.json").read_text()
        )
        with mock.patch.object(
            spark_extraction,
            "extract_sparks_from_text",
            return_value=mock.Mock(
                ok=True,
                sparks=[
                    {
                        "content": "First valid spark for transaction rollback test case.",
                        "lane": "work",
                        "why_keep": "Covers atomic insert behavior.",
                        "worth_reason": "Prevents partial persistence.",
                        "confidence": 0.7,
                        "sensitivity": "normal",
                    },
                    fixture[0],
                ],
                errors=[],
                attempts=1,
            ),
        ):
            with mock.patch.object(sparks, "insert_spark", side_effect=flaky_insert):
                result = cognitive_ingest._run_extraction_pipeline(
                    int(memory_item_id),
                    INGEST_TEXT,
                    project_id=project_id,
                )
        self.assertFalse(result["ok"])
        conn = crowley.connect_db()
        try:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM sparks WHERE source_memory_item_id = ?",
                (memory_item_id,),
            ).fetchone()
            row = conn.execute(
                "SELECT metadata_json FROM memory_items WHERE id = ?",
                (memory_item_id,),
            ).fetchone()
        finally:
            conn.close()
        assert count is not None
        self.assertEqual(int(count["n"]), 0)
        assert row is not None
        meta = json.loads(str(row["metadata_json"] or "{}"))
        self.assertEqual(meta.get("extraction_status"), "failed")

    def test_existing_ingest_endpoint_unchanged(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/ingest",
            json={
                "source": "cursor",
                "type": "note",
                "content": (
                    "Smoke check that legacy ingest still accepts notes after "
                    "cognitive ingest endpoint was added to the transport layer."
                ),
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get("status"), "ok")


if __name__ == "__main__":
    unittest.main()
