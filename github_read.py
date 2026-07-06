"""V3.9.15 — read-only GitHub API proxy for ChatGPT Actions."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import certifi


DEFAULT_REPO = "adkinsd2261/crowley"
API_BASE = "https://api.github.com"


class GitHubNotConfiguredError(Exception):
    """Raised when CROWLEY_GITHUB_TOKEN is missing."""


def configured_token() -> str | None:
    token = os.environ.get("CROWLEY_GITHUB_TOKEN", "").strip()
    return token or None


def default_repo() -> str:
    return os.environ.get("CROWLEY_GITHUB_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def github_status() -> dict[str, object]:
    token = configured_token()
    repo = default_repo()
    if not token:
        raise GitHubNotConfiguredError("CROWLEY_GITHUB_TOKEN is not configured")
    payload = github_get(f"/repos/{repo}")
    return {
        "configured": True,
        "repo": repo,
        "default_branch": payload.get("default_branch"),
        "full_name": payload.get("full_name"),
        "private": payload.get("private"),
    }


def github_get(path: str, *, params: dict[str, str] | None = None) -> Any:
    token = configured_token()
    if not token:
        raise GitHubNotConfiguredError("CROWLEY_GITHUB_TOKEN is not configured")
    url = API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Crowley-GPT-Toolbelt",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub request failed: {exc.reason}") from exc


def read_file(*, path: str, ref: str | None = None) -> dict[str, object]:
    repo = default_repo()
    ref = ref or "main"
    encoded_path = urllib.parse.quote(path.lstrip("/"), safe="/")
    payload = github_get(f"/repos/{repo}/contents/{encoded_path}", params={"ref": ref})
    if not isinstance(payload, dict):
        raise RuntimeError("unexpected GitHub contents response")
    return {
        "path": payload.get("path"),
        "sha": payload.get("sha"),
        "size": payload.get("size"),
        "encoding": payload.get("encoding"),
        "content": payload.get("content"),
        "ref": ref,
    }


def search_code(*, query: str, ref: str | None = None) -> dict[str, object]:
    repo = default_repo()
    q = f"{query} repo:{repo}"
    if ref:
        q += f" ref:{ref}"
    payload = github_get("/search/code", params={"q": q, "per_page": "10"})
    return payload if isinstance(payload, dict) else {"items": payload}


def list_branches() -> dict[str, object]:
    repo = default_repo()
    payload = github_get(f"/repos/{repo}/branches", params={"per_page": "30"})
    return {"items": payload}


def list_pulls(*, state: str = "open") -> dict[str, object]:
    repo = default_repo()
    payload = github_get(
        f"/repos/{repo}/pulls",
        params={"state": state, "per_page": "20"},
    )
    return {"items": payload}


def get_pull(number: int) -> dict[str, object]:
    repo = default_repo()
    return github_get(f"/repos/{repo}/pulls/{int(number)}")


def list_issues(*, state: str = "open") -> dict[str, object]:
    repo = default_repo()
    payload = github_get(
        f"/repos/{repo}/issues",
        params={"state": state, "per_page": "20"},
    )
    return {"items": payload}


def get_issue(number: int) -> dict[str, object]:
    repo = default_repo()
    return github_get(f"/repos/{repo}/issues/{int(number)}")


def compare_refs(*, base: str, head: str) -> dict[str, object]:
    repo = default_repo()
    return github_get(f"/repos/{repo}/compare/{base}...{head}")


def list_commits(*, sha: str | None = None, path: str | None = None) -> dict[str, object]:
    repo = default_repo()
    params: dict[str, str] = {"per_page": "20"}
    if sha:
        params["sha"] = sha
    if path:
        params["path"] = path
    payload = github_get(f"/repos/{repo}/commits", params=params)
    return {"items": payload}


def list_workflow_runs(*, branch: str | None = None) -> dict[str, object]:
    repo = default_repo()
    params: dict[str, str] = {"per_page": "10"}
    if branch:
        params["branch"] = branch
    payload = github_get(f"/repos/{repo}/actions/runs", params=params)
    return payload if isinstance(payload, dict) else {"workflow_runs": payload}
