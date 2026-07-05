#!/usr/bin/env python3
"""V3.9.15 — GitHub read proxy tests."""

from __future__ import annotations

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
from db_helpers import IsolatedDbTestCase  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

ACTIONS_KEY = "test-secret"
AUTH_HEADER = {"Authorization": f"Bearer {ACTIONS_KEY}"}


class GitHubReadTests(unittest.TestCase):
    def test_not_configured_returns_503_via_gateway(self) -> None:
        prior = os.environ.pop("CROWLEY_GITHUB_TOKEN", None)
        os.environ["CROWLEY_ACTION_KEY"] = ACTIONS_KEY
        try:
            with TestClient(crowley_app.app) as client:
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
                res = client.post(
                    "/api/actions/read",
                    headers=AUTH_HEADER,
                    json={"tool": "github.status", "args": {}},
                )
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json()["configured"])
        finally:
            os.environ.pop("CROWLEY_GITHUB_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
