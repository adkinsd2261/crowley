#!/usr/bin/env python3
"""V4 acceptance tests 1 and 5 — messy input and noise resistance (V4.2 #357)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import crowley  # noqa: E402
import spark_extraction  # noqa: E402
import sparks  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v4_acceptance"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def _validated_sparks_from_fixture(per_lane: dict[str, dict]) -> list[dict[str, object]]:
    validated: list[dict[str, object]] = []
    for raw in per_lane.values():
        result = sparks.validate_spark(raw)
        assert result.ok, result.errors
        assert result.spark is not None
        validated.append(result.spark)
    return spark_extraction.canonicalize_spark_batch(validated)


class V4AcceptanceInputTests(IsolatedDbTestCase):
    """Acceptance 1 + 5 for V4.2 Input Intelligence lock."""

    def tearDown(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        spark_extraction.clear_extraction_cache()
        super().tearDown()

    def test_messy_multi_domain_input(self) -> None:
        """Acceptance 1: multi-domain ingest yields multiple lane-tagged sparks."""
        fixture = _load("messy_multi_domain_input.json")
        os.environ["CROWLEY_TEST_MODE"] = "1"
        os.environ.setdefault("CROWLEY_EMBED_PROVIDER", "off")

        batch = _validated_sparks_from_fixture(fixture["extraction_fixture_per_lane"])
        mock_result = spark_extraction.SparkExtractionResult(
            ok=True,
            sparks=batch,
            errors=[],
            attempts=1,
        )

        client = TestClient(crowley_app.app)
        with mock.patch.object(
            spark_extraction,
            "extract_sparks_from_text",
            return_value=mock_result,
        ):
            res = client.post(
                "/api/cognitive/ingest?sync=1",
                json={"content": fixture["raw_text"], "source": "manual"},
            )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        memory_item_id = int(data["memory_item_id"])
        spark_ids = data["extraction"]["spark_ids"]
        self.assertGreaterEqual(len(spark_ids), int(fixture["expected_min_sparks"]))

        conn = crowley.connect_db()
        try:
            rows = conn.execute(
                """
                SELECT id, content, lane, trust_state, lineage_json
                FROM sparks
                WHERE source_memory_item_id = ?
                """,
                (memory_item_id,),
            ).fetchall()
        finally:
            conn.close()

        self.assertGreaterEqual(len(rows), int(fixture["expected_min_sparks"]))
        lanes = {str(row["lane"]) for row in rows}
        expected_lanes = set(fixture["expected_lanes"])
        self.assertGreaterEqual(len(lanes & expected_lanes), 2, lanes)
        self.assertTrue(lanes.issubset(expected_lanes | {"operating_style"}), lanes)

        fixture_by_content = {
            str(raw["content"]): raw
            for raw in fixture["extraction_fixture_per_lane"].values()
        }
        for row in rows:
            content = str(row["content"])
            self.assertLessEqual(len(content), sparks.SPARK_CONTENT_MAX_LEN)
            self.assertIn(content, fixture_by_content)
            lineage = json.loads(str(row["lineage_json"] or "{}"))
            self.assertEqual(int(lineage.get("memory_item_id")), memory_item_id)
            # Re-validate persisted spark fields against validate_spark contract.
            seed = fixture_by_content[content]
            revalidated = sparks.validate_spark(
                {
                    "content": content,
                    "lane": row["lane"],
                    "why_keep": seed["why_keep"],
                    "worth_reason": seed["worth_reason"],
                    "confidence": seed["confidence"],
                    "spark_type": seed.get("spark_type"),
                    "certainty": seed.get("certainty"),
                }
            )
            self.assertTrue(revalidated.ok, revalidated.errors)

        # Distinct lanes from the multi-domain paste (not a single catch-all).
        self.assertGreaterEqual(len(lanes), 2)

    def test_mixed_noise_does_not_discard_useful_sections(self) -> None:
        """Acceptance 1 criterion: temporary/noise chunks must not drop useful ones."""
        os.environ["CROWLEY_TEST_MODE"] = "1"
        os.environ.setdefault("CROWLEY_EMBED_PROVIDER", "off")
        text = (
            ROOT / "tests" / "fixtures" / "cognitive_chunking_mixed_topic.txt"
        ).read_text(encoding="utf-8")
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/cognitive/ingest?sync=1",
            json={"content": text, "source": "manual"},
        )
        self.assertEqual(res.status_code, 201, res.text)
        data = res.json()
        extraction = data["extraction"]
        self.assertTrue(extraction["ok"], extraction)
        self.assertGreaterEqual(extraction["chunking"]["chunk_count"], 2)
        self.assertGreaterEqual(extraction["chunking"]["chunks_skipped_intent"], 1)
        self.assertGreaterEqual(len(extraction["spark_ids"]), 1)

        memory_item_id = int(data["memory_item_id"])
        conn = crowley.connect_db()
        try:
            meta_row = conn.execute(
                "SELECT metadata_json FROM memory_items WHERE id = ?",
                (memory_item_id,),
            ).fetchone()
            spark_rows = conn.execute(
                """
                SELECT content, lane, lineage_json FROM sparks
                WHERE source_memory_item_id = ?
                """,
                (memory_item_id,),
            ).fetchall()
        finally:
            conn.close()

        assert meta_row is not None
        meta = json.loads(str(meta_row["metadata_json"] or "{}"))
        self.assertFalse(meta.get("non_retrieval"))
        self.assertGreaterEqual(int(meta.get("spark_count", 0)), 1)
        self.assertTrue(spark_rows)
        for row in spark_rows:
            lineage = json.loads(str(row["lineage_json"] or "{}"))
            self.assertEqual(int(lineage.get("memory_item_id")), memory_item_id)
            self.assertIn("chunk_index", lineage)
            self.assertLessEqual(len(str(row["content"])), sparks.SPARK_CONTENT_MAX_LEN)

    def test_noise_ignore_temporary(self) -> None:
        """Acceptance 5: ignore/temporary inputs do not pollute active retrieval."""
        fixture = _load("noise_ignore_temporary.json")
        os.environ["CROWLEY_TEST_MODE"] = "1"
        os.environ.setdefault("CROWLEY_EMBED_PROVIDER", "off")
        client = TestClient(crowley_app.app)

        for item in fixture["inputs"]:
            text = str(item["text"])
            intent = str(item["intent"])
            self.assertIn(intent, ("ignore", "temporary", "store"))

            res = client.post(
                "/api/cognitive/ingest?sync=1",
                json={"content": text, "source": "manual"},
            )
            self.assertEqual(res.status_code, 201, res.text)
            data = res.json()
            memory_item_id = int(data["memory_item_id"])
            self.assertEqual(data["intent"]["intent"], intent, data)

            conn = crowley.connect_db()
            try:
                spark_count = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM sparks
                    WHERE source_memory_item_id = ?
                    """,
                    (memory_item_id,),
                ).fetchone()
                active_count = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM sparks
                    WHERE source_memory_item_id = ? AND trust_state = 'active'
                    """,
                    (memory_item_id,),
                ).fetchone()
            finally:
                conn.close()

            assert spark_count is not None and active_count is not None
            if intent == "ignore":
                self.assertEqual(int(spark_count["n"]), int(item["expect_spark_count"]))
                self.assertEqual(int(active_count["n"]), 0)
            elif intent == "temporary":
                self.assertEqual(
                    int(active_count["n"]),
                    int(item["expect_active_spark_count"]),
                )
                self.assertEqual(int(spark_count["n"]), 0)
            else:
                self.assertGreaterEqual(
                    int(spark_count["n"]),
                    int(item["expect_spark_count_min"]),
                )
                self.assertGreaterEqual(int(active_count["n"]), 1)

            # Noise/temporary receipts must not appear in legacy retrieval hits.
            if intent in {"ignore", "temporary"}:
                hits = crowley.retrieve_memories(text, limit=20)
                self.assertNotIn(memory_item_id, [int(hit["id"]) for hit in hits])


if __name__ == "__main__":
    unittest.main()
