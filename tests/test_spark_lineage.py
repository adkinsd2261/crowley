#!/usr/bin/env python3
"""V4 T23 — spark audit trail and context lineage tests."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import context_orchestration  # noqa: E402
import crowley  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


INGEST_TEXT = (
    "Schema-first tickets keep V4 cognitive memory scope tight and reviewable. "
    "This input gives the test fixture enough material to extract one spark."
)


class SparkLineageTests(IsolatedDbTestCase):
    def tearDown(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        super().tearDown()

    def test_cognitive_ingest_populates_lineage_on_created_spark(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/cognitive/ingest?sync=1",
            json={"content": INGEST_TEXT, "source": "manual"},
        )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        spark_id = int(data["extraction"]["spark_ids"][0])
        memory_item_id = int(data["memory_item_id"])

        conn = crowley.connect_db()
        try:
            row = conn.execute(
                "SELECT source_memory_item_id, lineage_json FROM sparks WHERE id = ?",
                (spark_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        lineage = json.loads(str(row["lineage_json"]))
        self.assertEqual(int(row["source_memory_item_id"]), memory_item_id)
        self.assertEqual(int(lineage["memory_item_id"]), memory_item_id)
        self.assertEqual(lineage["dedup_action"], "inserted")
        self.assertTrue(str(lineage.get("extraction_id")))

    def test_dedup_merge_records_lineage_in_source_refs(self) -> None:
        spark = {
            "content": "Lineage merges should retain source receipt references.",
            "lane": "work",
            "why_keep": "Documents merge lineage for repeated evidence.",
            "worth_reason": "Keeps audit trails available after dedup.",
            "confidence": 0.8,
            "sensitivity": "normal",
        }
        conn = crowley.connect_db()
        try:
            first = sparks.upsert_spark_with_dedup(
                conn,
                spark,
                source_memory_item_id=1,
                project_id=None,
                trust_state="candidate",
                lineage_json={"extraction_id": "first"},
            )
            second = sparks.upsert_spark_with_dedup(
                conn,
                spark,
                source_memory_item_id=2,
                project_id=None,
                trust_state="candidate",
                lineage_json={"extraction_id": "second"},
            )
            self.assertEqual(first.spark_id, second.spark_id)
            self.assertEqual(second.action, "merged")
            row = conn.execute(
                "SELECT source_refs_json FROM sparks WHERE id = ?",
                (first.spark_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        refs = json.loads(str(row["source_refs_json"]))
        self.assertEqual(refs[-1]["dedup_action"], "merged")
        self.assertEqual(int(refs[-1]["memory_item_id"]), 2)
        self.assertEqual(refs[-1]["extraction_id"], "second")

    def test_context_trace_includes_retrieved_spark_lineage(self) -> None:
        conn = crowley.connect_db()
        try:
            project_id = crowley._active_project_id(conn)
            now = crowley._now_iso()
            cur = conn.execute(
                """
                INSERT INTO memory_items (
                    created_at, updated_at, project_id, memory_type, content, summary,
                    importance, source, pinned, status, confidence, metadata_json
                ) VALUES (?, ?, ?, 'event', ?, ?, 3, 'test', 0, 'active', 0.9, '{}')
                """,
                (
                    now,
                    now,
                    project_id,
                    "Lineage trace source receipt with enough concrete detail.",
                    "Lineage trace source receipt",
                ),
            )
            memory_item_id = int(cur.lastrowid)
            spark_id = sparks.insert_spark(
                conn,
                {
                    "content": "Lineage trace retrieval marker for cognitive context.",
                    "lane": "work",
                    "why_keep": "Supports trace lineage verification.",
                    "worth_reason": "Makes context output auditable.",
                    "confidence": 0.9,
                    "sensitivity": "normal",
                },
                source_memory_item_id=int(memory_item_id),
                project_id=project_id,
                trust_state="active",
                lineage_json={
                    "memory_item_id": int(memory_item_id),
                    "extraction_id": "trace-test",
                    "dedup_action": "inserted",
                },
            )
            for idx in range(9):
                sparks.insert_spark(
                    conn,
                    {
                        "content": f"Additional active lineage filler spark {idx}.",
                        "lane": "work",
                        "why_keep": "Raises active spark count above cold-start fallback.",
                        "worth_reason": "Keeps this test on spark lineage instead of fallback.",
                        "confidence": 0.7,
                        "sensitivity": "normal",
                    },
                    source_memory_item_id=int(memory_item_id),
                    project_id=project_id,
                    trust_state="active",
                    lineage_json={
                        "memory_item_id": int(memory_item_id),
                        "extraction_id": f"filler-{idx}",
                        "dedup_action": "inserted",
                    },
                )
            conn.commit()
            payload = context_orchestration.build_cognitive_context(
                "lineage trace retrieval marker",
                lanes="work",
                project_id=project_id,
                conn=conn,
            )
        finally:
            conn.close()

        trace_lineage = payload["trace"]["lineage"]
        match = [item for item in trace_lineage if int(item["spark_id"]) == spark_id]
        self.assertTrue(match, trace_lineage)
        self.assertEqual(match[0]["lineage"]["extraction_id"], "trace-test")
        self.assertEqual(int(match[0]["source_memory_item_id"]), int(memory_item_id))


if __name__ == "__main__":
    unittest.main()
