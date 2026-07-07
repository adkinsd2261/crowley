#!/usr/bin/env python3
"""V3.9.15 — GitHub read proxy tests."""

from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as crowley_app  # noqa: E402
import github_read  # noqa: E402
from actions_helpers import actions_headers, boot_actions_session  # noqa: E402
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ACTIONS_KEY = "test-secret"
AUTH_HEADER = actions_headers(ACTIONS_KEY, session="github-read")


class GitHubReadTests(unittest.TestCase):
    def test_not_configured_returns_503_via_gateway(self) -> None:
        prior = os.environ.pop("CROWLEY_GITHUB_TOKEN", None)
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY
        try:
            with TestClient(crowley_app.app) as client:
                boot_actions_session(client, AUTH_HEADER)
                res = client.post(
                    "/api/actions/read",
                    headers=AUTH_HEADER,
                    json={"tool": "github.status", "args": {}},
                )
            self.assertEqual(res.status_code, 503)
            self.assertEqual(res.json()["error"], "github_not_configured")
        finally:
            if prior is not None:
                os.environ["CROWLEY_GITHUB_TOKEN"] = prior

    @patch.object(github_read, "github_get")
    def test_status_ok_when_token_set(self, mock_get) -> None:
        mock_get.return_value = {
            "default_branch": "main",
            "full_name": "adkinsd2261/crowley",
            "private": True,
        }
        os.environ["CROWLEY_GITHUB_TOKEN"] = "test-token"
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY
        try:
            with TestClient(crowley_app.app) as client:
                boot_actions_session(client, AUTH_HEADER)
                res = client.post(
                    "/api/actions/read",
                    headers=AUTH_HEADER,
                    json={"tool": "github.status", "args": {}},
                )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json()["configured"])
            self.assertIn("github_meta", res.json())
        finally:
            os.environ.pop("CROWLEY_GITHUB_TOKEN", None)

    @patch.object(github_read, "github_get")
    def test_read_file_decodes_and_truncates(self, mock_get) -> None:
        raw = b"x" * (github_read.MAX_FILE_BYTES + 50)
        mock_get.return_value = {
            "path": "big.txt",
            "sha": "abc",
            "size": len(raw),
            "encoding": "base64",
            "content": base64.b64encode(raw).decode("ascii"),
        }
        result = github_read.read_file(path="big.txt")
        self.assertTrue(result["truncated"])
        self.assertEqual(len(str(result["content"])), github_read.MAX_FILE_BYTES)

    @patch.object(github_read, "github_get")
    def test_read_file_rejects_download_only_large_file(self, mock_get) -> None:
        mock_get.return_value = {
            "path": "crowley.py",
            "sha": "abc",
            "size": github_read.MAX_FILE_BYTES + 1,
            "download_url": "https://example.com/raw",
        }
        result = github_read.read_file(path="crowley.py")
        self.assertTrue(result["truncated"])
        self.assertIsNone(result["content"])

    @patch.object(github_read, "github_get")
    def test_search_code_slims_items_and_caps_query(self, mock_get) -> None:
        mock_get.return_value = {
            "total_count": 1,
            "items": [
                {
                    "name": "github_read.py",
                    "path": "github_read.py",
                    "sha": "sha",
                    "html_url": "https://github.com/example",
                    "repository": {"full_name": "adkinsd2261/crowley"},
                    "text_matches": [{"fragment": "x" * 5000}],
                }
            ],
        }
        result = github_read.search_code(query="def")
        self.assertEqual(len(result["items"]), 1)
        self.assertNotIn("text_matches", result["items"][0])
        self.assertIn("github_meta", result)

    @patch.object(github_read, "github_get")
    def test_github_dispatch_returns_structured_error_not_502(self, mock_get) -> None:
        mock_get.side_effect = github_read.GitHubReadError("rate limited")
        os.environ["CROWLEY_GITHUB_TOKEN"] = "test-token"
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY
        try:
            with TestClient(crowley_app.app) as client:
                boot_actions_session(client, AUTH_HEADER)
                res = client.post(
                    "/api/actions/read",
                    headers=AUTH_HEADER,
                    json={"tool": "github.file", "args": {"path": "README.md"}},
                )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"], "github_read_failed")
        finally:
            os.environ.pop("CROWLEY_GITHUB_TOKEN", None)

    @patch.object(github_read, "github_get")
    def test_compare_strips_patches(self, mock_get) -> None:
        mock_get.return_value = {
            "status": "ahead",
            "files": [
                {
                    "filename": "a.py",
                    "status": "modified",
                    "patch": "x" * 5000,
                    "additions": 1,
                    "deletions": 0,
                    "changes": 1,
                }
            ],
        }
        result = github_read.compare_refs(base="main", head="feature")
        self.assertNotIn("patch", result["files"][0])


if __name__ == "__main__":
    unittest.main()
