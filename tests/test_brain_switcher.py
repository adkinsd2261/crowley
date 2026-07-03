"""Runtime brain switcher API and UI contract tests."""

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
from fastapi.testclient import TestClient  # noqa: E402


class BrainSwitcherApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="crowley-brain-test-")
        self._brain_path = Path(self._tmpdir.name) / "brain.json"
        crowley.set_brain_settings_path(self._brain_path)
        crowley.reset_model_provider_setting()
        os.environ["CROWLEY_TEST_MODE"] = "1"

    def tearDown(self) -> None:
        crowley.reset_model_provider_setting()
        crowley.set_brain_settings_path(None)
        os.environ.pop("CROWLEY_TEST_MODE", None)
        self._tmpdir.cleanup()

    def test_get_brain_defaults_to_auto(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.get("/api/brain")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "auto")
        self.assertIn("providers", data)
        self.assertGreaterEqual(len(data["providers"]), 4)

    def test_post_brain_persists_provider_and_model(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.post(
            "/api/brain",
            json={"provider": "ollama", "model": "dolphin-mistral:latest"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["provider"], "ollama")
        self.assertEqual(data["model"], "dolphin-mistral:latest")
        saved = json.loads(self._brain_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["provider"], "ollama")
        self.assertEqual(saved["model"], "dolphin-mistral:latest")

    def test_post_brain_rejects_invalid_provider(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.post("/api/brain", json={"provider": "gemini"})
        self.assertIn(res.status_code, (400, 422))

    def test_health_includes_brain_config(self) -> None:
        client = TestClient(crowley_app.app)
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("brain_config", data)
        self.assertEqual(data["brain_config"]["provider"], "auto")

    def test_set_brain_config_resolves_ollama_model(self) -> None:
        crowley.set_brain_config("ollama", "custom-model")
        self.assertEqual(crowley.get_model_provider_setting(), "ollama")
        self.assertEqual(crowley.get_active_model_name(), "custom-model")

    def test_list_ollama_models_parses_tags(self) -> None:
        payload = json.dumps(
            {"models": [{"name": "dolphin:latest"}, {"name": "llama3.1:8b"}]}
        ).encode("utf-8")

        class _Resp:
            status = 200

            def read(self) -> bytes:
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args: object) -> None:
                return None

        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            models = crowley.list_ollama_models()
        self.assertEqual(models, ["dolphin:latest", "llama3.1:8b"])

    def test_auto_mode_prefers_openai_when_key_present(self) -> None:
        crowley.reset_model_provider_setting()
        with mock.patch.object(crowley, "_has_openai_key", return_value=True):
            self.assertEqual(crowley.get_model_provider(), "openai")

    def test_ollama_chunk_text_reads_thinking_fallback(self) -> None:
        chunk = {"message": {"content": "", "thinking": "reasoning"}}
        self.assertEqual(crowley._ollama_chunk_text(chunk), "reasoning")
        chunk2 = {"message": {"content": "hello", "thinking": "reasoning"}}
        self.assertEqual(crowley._ollama_chunk_text(chunk2), "hello")


class BrainSwitcherUiTests(unittest.TestCase):
    def test_ui_contains_brain_switcher(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
        for token in (
            'id="brain-switcher"',
            'id="brain-switcher-trigger"',
            'id="brain-switcher-menu"',
            "header-version-badge",
        ):
            self.assertIn(token, html)
        for token in (
            "renderBrainSwitcher",
            "setBrainSelection",
            "syncBrainMenuPosition",
            "/api/brain",
            "data-brain-provider",
            "brain-switcher-section",
        ):
            self.assertIn(token, js)
        for token in (
            ".brain-switcher",
            ".brain-switcher-orb",
            ".brain-switcher-menu",
            ".hidden",
            "z-index: 200",
            "position: fixed",
        ):
            self.assertIn(token, css)


if __name__ == "__main__":
    unittest.main()
