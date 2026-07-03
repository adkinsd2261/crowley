#!/usr/bin/env python3
"""Tests for openapi-chatgpt URL patching."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import patch_openapi_chatgpt as patcher  # noqa: E402


class PatchOpenApiChatGptTests(unittest.TestCase):
    def test_normalize_base_url_strips_path_and_slash(self) -> None:
        self.assertEqual(
            patcher.normalize_base_url("https://example.trycloudflare.com/"),
            "https://example.trycloudflare.com",
        )

    def test_patch_writes_server_url(self) -> None:
        template = {
            "openapi": "3.1.0",
            "servers": [{"url": "https://YOUR-CROWLEY-DOMAIN"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "openapi-chatgpt.json"
            out = root / "openapi-chatgpt.deployed.json"
            src.write_text(json.dumps(template), encoding="utf-8")
            patcher.patch_openapi(
                base_url="https://bridge.example.com",
                template=src,
                output=out,
            )
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["servers"][0]["url"], "https://bridge.example.com")


if __name__ == "__main__":
    unittest.main()
