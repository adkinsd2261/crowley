#!/usr/bin/env python3
"""Tests for openapi-chatgpt URL patching."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import patch_openapi_chatgpt as patcher  # noqa: E402


def object_schemas_missing_properties(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    if isinstance(node, dict):
        if node.get("type") == "object" and "$ref" not in node and "properties" not in node:
            yield path
        for key, value in node.items():
            yield from object_schemas_missing_properties(value, path + (str(key),))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from object_schemas_missing_properties(item, path + (str(index),))


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

    def test_chatgpt_openapi_object_schemas_define_properties(self) -> None:
        payload = json.loads((ROOT / "openapi-chatgpt.json").read_text(encoding="utf-8"))
        missing = list(object_schemas_missing_properties(payload))
        self.assertEqual(missing, [], f"object schemas missing properties: {missing}")


if __name__ == "__main__":
    unittest.main()
