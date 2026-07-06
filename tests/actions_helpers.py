"""Shared helpers for ChatGPT Actions API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def boot_actions_session(client: TestClient, headers: dict[str, str]) -> None:
    res = client.post(
        "/api/actions/read",
        headers=headers,
        json={"tool": "agent.sync", "args": {"agent": "chatgpt"}},
    )
    if res.status_code != 200:
        raise AssertionError(f"agent.sync boot failed: {res.status_code} {res.text}")


def actions_headers(bearer: str, *, session: str = "unittest-actions") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {bearer}",
        "X-Crowley-Session": session,
    }
