"""V3.9.12 #77 — portable terminal writeback schema and parser."""

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


class PortableWritebackTests(IsolatedDbTestCase):
    def test_valid_writeback_json(self) -> None:
        raw = (FIXTURES / "portable_writeback_valid.json").read_text()
        result = crowley.parse_terminal_writeback(raw)
        self.assertTrue(result.ok, result.errors)
        assert result.writeback is not None
        self.assertEqual(result.writeback["format"], crowley.PORTABLE_WRITEBACK_FORMAT)
        session = result.writeback["session"]
        assert isinstance(session, dict)
        self.assertEqual(session["surface"], "chatgpt")
        sparks = result.writeback["sparks"]
        assert isinstance(sparks, list)
        self.assertEqual(len(sparks), 2)
        self.assertEqual(sparks[0]["lane"], "work")
        self.assertIn("do_not_save", result.writeback)
        self.assertFalse(result.writeback["do_not_save_persist"])

    def test_valid_writeback_from_fenced_markdown(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        fenced = (
            "Session recap below.\n\n```json\n"
            + json.dumps(payload, indent=2)
            + "\n```\n"
        )
        result = crowley.parse_terminal_writeback(fenced)
        self.assertTrue(result.ok, result.errors)

    def test_rejects_incomplete_spark(self) -> None:
        raw = (FIXTURES / "portable_writeback_invalid_spark.json").read_text()
        result = crowley.parse_terminal_writeback(raw)
        self.assertFalse(result.ok)
        joined = " ".join(result.errors)
        self.assertIn("why_keep", joined)
        self.assertIn("confidence", joined)
        self.assertIn("sensitivity", joined)

    def test_rejects_invalid_lane(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        sparks = payload["sparks"]
        assert isinstance(sparks, list)
        sparks[0]["lane"] = "fantasy"
        result = crowley.parse_terminal_writeback(payload)
        self.assertFalse(result.ok)
        self.assertTrue(any("lane must be one of" in err for err in result.errors))

    def test_rejects_confidence_out_of_range(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        sparks = payload["sparks"]
        assert isinstance(sparks, list)
        sparks[0]["confidence"] = 1.5
        result = crowley.parse_terminal_writeback(payload)
        self.assertFalse(result.ok)
        self.assertTrue(any("confidence must be between" in err for err in result.errors))

    def test_all_lanes_accepted(self) -> None:
        for lane in crowley.PORTABLE_WRITEBACK_LANES:
            payload = {
                "session": {"summary": f"Lane check for {lane}."},
                "sparks": [
                    {
                        "content": f"Spark in {lane} lane.",
                        "lane": lane,
                        "why_keep": "Lane coverage test.",
                        "confidence": 0.5,
                        "sensitivity": "normal",
                    }
                ],
            }
            result = crowley.parse_terminal_writeback(payload)
            self.assertTrue(result.ok, f"{lane}: {result.errors}")

    def test_do_not_save_parsed_not_persisted(self) -> None:
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        result = crowley.parse_terminal_writeback(payload)
        self.assertTrue(result.ok, result.errors)
        assert result.writeback is not None
        do_not_save = result.writeback["do_not_save"]
        assert isinstance(do_not_save, list)
        self.assertEqual(len(do_not_save), 2)
        self.assertFalse(result.writeback["do_not_save_persist"])

    def test_invalid_input_does_not_mutate_memory(self) -> None:
        before = len(crowley.list_memory_items(limit=500))
        raw = (FIXTURES / "portable_writeback_invalid_spark.json").read_text()
        result = crowley.parse_terminal_writeback(raw)
        self.assertFalse(result.ok)
        after = len(crowley.list_memory_items(limit=500))
        self.assertEqual(before, after)

    def test_api_parse_valid_object(self) -> None:
        client = TestClient(crowley_app.app)
        payload = json.loads((FIXTURES / "portable_writeback_valid.json").read_text())
        res = client.post("/api/portable/writeback/parse", json={"writeback": payload})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertIn("writeback", data)

    def test_api_parse_invalid_returns_errors(self) -> None:
        client = TestClient(crowley_app.app)
        payload = json.loads(
            (FIXTURES / "portable_writeback_invalid_spark.json").read_text()
        )
        res = client.post("/api/portable/writeback/parse", json={"writeback": payload})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data["ok"])
        self.assertTrue(data["errors"])

    def test_contract_lists_sensitivities(self) -> None:
        contract = crowley.portable_writeback_contract()
        allowed = contract.get("allowed_sensitivities")
        assert isinstance(allowed, list)
        self.assertIn("normal", allowed)
        self.assertIn("sensitive", allowed)
