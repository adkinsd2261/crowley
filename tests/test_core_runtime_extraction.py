#!/usr/bin/env python3
"""V4.1 — core/runtime extraction compatibility tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crowley  # noqa: E402
import crowley_core  # noqa: E402
import model_runtime  # noqa: E402


class CoreRuntimeExtractionTests(unittest.TestCase):
    def tearDown(self) -> None:
        crowley.reset_db_path()
        os.environ.pop("CROWLEY_TEST_MODE", None)
        os.environ.pop("CROWLEY_EMBED_PROVIDER", None)
        model_runtime.set_brain_settings_path(None)
        model_runtime.reset_model_provider_setting()

    def test_db_path_facade_updates_core_runtime(self) -> None:
        with tempfile.TemporaryDirectory(prefix="crowley-core-test-") as tmp:
            db_path = Path(tmp) / "crowley-test.db"
            self.assertEqual(crowley.set_db_path(db_path), db_path)
            self.assertEqual(crowley_core.get_db_path(), db_path)
            conn = crowley.connect_db()
            try:
                conn.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY)")
            finally:
                conn.close()
            self.assertTrue(db_path.exists())

    def test_model_runtime_stub_is_facade_compatible(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        messages = [{"role": "user", "content": "hi"}]
        self.assertEqual(list(model_runtime.iter_model_tokens(messages)), [crowley.TEST_MODE_STUB_REPLY])
        self.assertEqual(list(crowley.iter_model_tokens(messages)), [crowley.TEST_MODE_STUB_REPLY])

    def test_crowley_patch_points_still_control_nonstream_model_call(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        with tempfile.TemporaryDirectory(prefix="crowley-brain-test-") as tmp:
            crowley.set_brain_settings_path(Path(tmp) / "brain.json")
            crowley.reset_model_provider_setting()
            crowley.set_model_provider_setting("openai")
            with mock.patch.object(crowley, "_has_openai_key", return_value=True):
                with mock.patch.object(crowley, "_call_openai", return_value="patched") as call_mock:
                    reply = crowley.call_model(
                        [{"role": "user", "content": "hi"}],
                        stream=False,
                        quiet=True,
                    )
            self.assertEqual(reply, "patched")
            call_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
