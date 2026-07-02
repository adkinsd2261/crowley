"""CROWLEY_TEST_MODE foundation (V3.9.8 #50)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import crowley


class TestModeTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        os.environ.pop("CROWLEY_EMBED_PROVIDER", None)

    def test_is_test_mode_reads_env(self) -> None:
        os.environ.pop("CROWLEY_TEST_MODE", None)
        self.assertFalse(crowley.is_test_mode())
        os.environ["CROWLEY_TEST_MODE"] = "1"
        self.assertTrue(crowley.is_test_mode())
        os.environ["CROWLEY_TEST_MODE"] = "true"
        self.assertTrue(crowley.is_test_mode())

    def test_embed_provider_forced_off_in_test_mode(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        os.environ["CROWLEY_EMBED_PROVIDER"] = "local"
        self.assertEqual(crowley._memory_embed_provider(), "off")

    def test_iter_model_tokens_stub(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        tokens = list(crowley.iter_model_tokens([{"role": "user", "content": "hi"}]))
        self.assertEqual(tokens, [crowley.TEST_MODE_STUB_REPLY])

    def test_call_model_stream_stub(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        captured: list[str] = []

        reply = crowley.call_model(
            [{"role": "user", "content": "hi"}],
            stream=True,
            quiet=True,
            on_token=captured.append,
        )

        self.assertEqual(reply, crowley.TEST_MODE_STUB_REPLY)
        self.assertEqual(captured, [crowley.TEST_MODE_STUB_REPLY])

    def test_call_model_non_stream_stub(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        reply = crowley.call_model(
            [{"role": "user", "content": "hi"}],
            stream=False,
            quiet=True,
        )
        self.assertEqual(reply, crowley.TEST_MODE_STUB_REPLY)

    def test_test_mode_skips_network_providers(self) -> None:
        os.environ["CROWLEY_TEST_MODE"] = "1"
        with mock.patch.object(crowley, "_iter_ollama_tokens") as ollama_mock:
            with mock.patch.object(crowley, "_iter_openai_tokens") as openai_mock:
                list(crowley.iter_model_tokens([{"role": "user", "content": "hi"}]))
        ollama_mock.assert_not_called()
        openai_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
