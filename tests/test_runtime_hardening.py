"""Fragile startup regression suite (V3.9.8 #51–#54)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import crowley  # noqa: E402
import app as crowley_app  # noqa: E402
from db_helpers import IsolatedDbTestCase, isolated_db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from test_chat_api import parse_sse_events  # noqa: E402


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_build_runtime_diagnostics_shape(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        os.environ["CROWLEY_EMBED_PROVIDER"] = "off"
        try:
            runtime = crowley.build_runtime_diagnostics()
        finally:
            os.environ.pop("CROWLEY_TEST_MODE", None)

        for key in ("embeddings", "vector_store", "retrieval", "model", "test_mode"):
            self.assertIn(key, runtime)
        self.assertEqual(runtime["embeddings"], "off")
        self.assertEqual(runtime["model"], "available")
        self.assertTrue(runtime["test_mode"])

    def test_probe_model_availability_test_mode(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        try:
            probe = crowley.probe_model_availability()
        finally:
            os.environ.pop("CROWLEY_TEST_MODE", None)
        self.assertEqual(probe["status"], "available")
        self.assertEqual(probe["provider"], "test")

    def test_probe_model_unavailable_without_providers(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        os.environ.pop("OPENAI_API_KEY", None)
        with mock.patch.object(crowley, "_probe_ollama_reachable", return_value=False):
            probe = crowley.probe_model_availability()
        self.assertEqual(probe["status"], "unavailable")


class FragileStartupTests(unittest.TestCase):
    def test_setup_db_with_embed_off_and_test_mode(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        os.environ["CROWLEY_EMBED_PROVIDER"] = "off"
        with isolated_db():
            rows = crowley.retrieve_memories("crowley project", limit=5)
        os.environ.pop("CROWLEY_TEST_MODE", None)
        self.assertIsInstance(rows, list)
        self.assertIn("keyword", crowley.get_last_retrieval_mode().lower())

    def test_sqlite_vec_failure_does_not_raise_on_retrieve(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        os.environ["CROWLEY_EMBED_PROVIDER"] = "off"
        with isolated_db():
            conn = crowley.connect_db()
            try:
                with mock.patch.object(crowley, "_try_load_sqlite_vec", return_value=False):
                    self.assertFalse(crowley._ensure_memory_vec_table(conn))
                rows = crowley.retrieve_memories("test query", limit=3)
            finally:
                conn.close()
        os.environ.pop("CROWLEY_TEST_MODE", None)
        self.assertIsInstance(rows, list)
        self.assertIn("keyword", crowley.get_last_retrieval_mode().lower())


class RuntimeHealthApiTests(IsolatedDbTestCase):
    def test_api_health_includes_runtime_block(self) -> None:
        with TestClient(crowley_app.app) as client:
            res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        runtime = body.get("runtime")
        self.assertIsInstance(runtime, dict)
        for key in ("embeddings", "vector_store", "retrieval", "model", "test_mode"):
            self.assertIn(key, runtime)
        self.assertEqual(body["version"], crowley.CROWLEY_VERSION)
        self.assertTrue(runtime["test_mode"])


class ReadOnlyRoutesTests(IsolatedDbTestCase):
    def test_world_and_context_without_model(self) -> None:
        with TestClient(crowley_app.app) as client:
            world = client.get("/api/world")
            context = client.get("/api/context")
        self.assertEqual(world.status_code, 200)
        self.assertEqual(context.status_code, 200)
        self.assertIn("state", world.json())
        ctx = context.json()
        self.assertIn("relevant_memories", ctx)
        self.assertIn("runtime", ctx["system_health"])


class NoModelChatIntegrationTests(unittest.TestCase):
    """Unmocked chat path when no provider is reachable (#51)."""

    _tmpdir: tempfile.TemporaryDirectory[str] | None = None

    def setUp(self) -> None:
        super().setUp()
        os.environ.pop("CROWLEY_TEST_MODE", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["CROWLEY_EMBED_PROVIDER"] = "off"
        self._tmpdir = tempfile.TemporaryDirectory(prefix="crowley-test-")
        crowley.set_db_path(Path(self._tmpdir.name) / "test.db")
        crowley.setup_db()

    def tearDown(self) -> None:
        try:
            crowley.reset_db_path()
        finally:
            if self._tmpdir is not None:
                self._tmpdir.cleanup()
                self._tmpdir = None
        super().tearDown()

    def test_chat_graceful_error_without_mock(self) -> None:
        with mock.patch.object(
            crowley,
            "_iter_ollama_tokens",
            side_effect=ConnectionError("Ollama not reachable"),
        ):
            with TestClient(crowley_app.app) as client:
                before = client.get("/api/messages").json()["messages"]
                res = client.post("/api/chat", json={"message": "hello without model"})
                after = client.get("/api/messages").json()["messages"]

        self.assertEqual(res.status_code, 200)
        events = parse_sse_events(res.text)
        self.assertEqual(events[0][0], "status")
        self.assertEqual(events[-1][0], "error")
        self.assertIn("API key", events[-1][1]["message"])
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[-1]["role"], "user")
        self.assertEqual(after[-1]["content"], "hello without model")


if __name__ == "__main__":
    unittest.main()
