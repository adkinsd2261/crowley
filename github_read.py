"""V3.9.15 — read-only GitHub API proxy for ChatGPT Actions."""

from __future__ import annotations

import base64
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import certifi


DEFAULT_REPO = "adkinsd2261/crowley"
API_BASE = "https://api.github.com"

MAX_FILE_BYTES = 100_000
MAX_GITHUB_RESPONSE_BYTES = 512_000
MAX_GITHUB_PAYLOAD_BYTES = 180_000
MAX_SEARCH_QUERY_LEN = 256
MAX_SEARCH_RESULTS = 10
MAX_COMPARE_FILES = 40
GITHUB_REQUEST_TIMEOUT = 10
GITHUB_RETRY_ATTEMPTS = 2
GITHUB_RETRY_BACKOFF_SEC = 0.35

GITHUB_ENVELOPE_VERSION = "github_env_v1"


class GitHubNotConfiguredError(Exception):
    """Raised when CROWLEY_GITHUB_TOKEN is missing."""


class GitHubReadError(Exception):
    """Structured GitHub read failure."""


def configured_token() -> str | None:
    token = os.environ.get("CROWLEY_GITHUB_TOKEN", "").strip()
    return token or None


def default_repo() -> str:
    return os.environ.get("CROWLEY_GITHUB_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())


def payload_bytes(payload: object) -> int:
    return len(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def apply_github_envelope(payload: dict[str, object]) -> dict[str, object]:
    """Bound GitHub tool responses to keep Actions/tunnel responses small."""
    out = dict(payload)
    if payload_bytes(out) <= MAX_GITHUB_PAYLOAD_BYTES:
        meta = out.get("github_meta")
        if not isinstance(meta, dict):
            meta = {}
            out["github_meta"] = meta
        meta.setdefault("envelope", GITHUB_ENVELOPE_VERSION)
        meta.setdefault("payload_bytes", payload_bytes(out))
        meta.setdefault("truncated", False)
        return out

    truncated = False
    for key in ("content", "items", "files", "workflow_runs"):
        value = out.get(key)
        if isinstance(value, list) and len(value) > 1:
            out[key] = value[: max(1, len(value) // 2)]
            truncated = True
    if isinstance(out.get("content"), str) and len(out["content"]) > MAX_FILE_BYTES // 2:
        out["content"] = str(out["content"])[: MAX_FILE_BYTES // 2]
        truncated = True

    out["github_meta"] = {
        "envelope": GITHUB_ENVELOPE_VERSION,
        "payload_bytes": payload_bytes(out),
        "max_payload_bytes": MAX_GITHUB_PAYLOAD_BYTES,
        "truncated": truncated,
    }
    return out


def github_status() -> dict[str, object]:
    token = configured_token()
    repo = default_repo()
    if not token:
        raise GitHubNotConfiguredError("CROWLEY_GITHUB_TOKEN is not configured")
    payload = github_get(f"/repos/{repo}")
    return apply_github_envelope(
        {
            "configured": True,
            "repo": repo,
            "default_branch": payload.get("default_branch"),
            "full_name": payload.get("full_name"),
            "private": payload.get("private"),
        }
    )


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
    last_error: Exception | None = None
    for attempt in range(GITHUB_RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(
                request,
                timeout=GITHUB_REQUEST_TIMEOUT,
                context=_ssl_context(),
            ) as response:
                raw = response.read(MAX_GITHUB_RESPONSE_BYTES + 1)
            if len(raw) > MAX_GITHUB_RESPONSE_BYTES:
                raise GitHubReadError(
                    f"GitHub response exceeds {MAX_GITHUB_RESPONSE_BYTES} bytes"
                )
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read(1024).decode("utf-8", errors="replace")
            retryable = exc.code >= 500 or exc.code == 403
            last_error = GitHubReadError(f"GitHub HTTP {exc.code}: {body[:500]}")
            if retryable and attempt + 1 < GITHUB_RETRY_ATTEMPTS:
                time.sleep(GITHUB_RETRY_BACKOFF_SEC)
                continue
            raise last_error from exc
        except urllib.error.URLError as exc:
            last_error = GitHubReadError(f"GitHub request failed: {exc.reason}")
            if attempt + 1 < GITHUB_RETRY_ATTEMPTS:
                time.sleep(GITHUB_RETRY_BACKOFF_SEC)
                continue
            raise last_error from exc
        except TimeoutError as exc:
            last_error = GitHubReadError("GitHub request timed out")
            if attempt + 1 < GITHUB_RETRY_ATTEMPTS:
                time.sleep(GITHUB_RETRY_BACKOFF_SEC)
                continue
            raise last_error from exc
        except json.JSONDecodeError as exc:
            raise GitHubReadError("GitHub returned invalid JSON") from exc
    if last_error is not None:
        raise last_error
    raise GitHubReadError("GitHub request failed")


def read_file(*, path: str, ref: str | None = None) -> dict[str, object]:
    repo = default_repo()
    ref = ref or "main"
    encoded_path = urllib.parse.quote(path.lstrip("/"), safe="/")
    payload = github_get(f"/repos/{repo}/contents/{encoded_path}", params={"ref": ref})
    if not isinstance(payload, dict):
        raise GitHubReadError("unexpected GitHub contents response")

    size = int(payload.get("size") or 0)
    if payload.get("download_url") and size > MAX_FILE_BYTES:
        return apply_github_envelope(
            {
                "path": payload.get("path"),
                "sha": payload.get("sha"),
                "size": size,
                "content": None,
                "ref": ref,
                "truncated": True,
                "message": (
                    f"File exceeds {MAX_FILE_BYTES} byte cap; request a smaller path "
                    "or use github.commits/github.search_code."
                ),
            }
        )

    encoding = str(payload.get("encoding") or "")
    content = payload.get("content")
    truncated = False
    text_content: str | None = None
    if content and encoding == "base64":
        raw = base64.b64decode(str(content))
        if len(raw) > MAX_FILE_BYTES:
            raw = raw[:MAX_FILE_BYTES]
            truncated = True
        text_content = raw.decode("utf-8", errors="replace")
    elif isinstance(content, str):
        text_content = content
        if len(text_content) > MAX_FILE_BYTES:
            text_content = text_content[:MAX_FILE_BYTES]
            truncated = True

    return apply_github_envelope(
        {
            "path": payload.get("path"),
            "sha": payload.get("sha"),
            "size": size,
            "content": text_content,
            "ref": ref,
            "truncated": truncated,
            "max_bytes": MAX_FILE_BYTES,
        }
    )


def _slim_code_search_item(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        return {"summary": str(item)[:200]}
    return {
        "name": item.get("name"),
        "path": item.get("path"),
        "sha": item.get("sha"),
        "html_url": item.get("html_url"),
        "repository": (
            item.get("repository", {}).get("full_name")
            if isinstance(item.get("repository"), dict)
            else None
        ),
    }


def search_code(*, query: str, ref: str | None = None) -> dict[str, object]:
    repo = default_repo()
    trimmed_query = str(query or "").strip()
    if not trimmed_query:
        raise GitHubReadError("search query is required")
    if len(trimmed_query) > MAX_SEARCH_QUERY_LEN:
        trimmed_query = trimmed_query[:MAX_SEARCH_QUERY_LEN]
    q = f"{trimmed_query} repo:{repo}"
    if ref:
        q += f" ref:{ref}"
    payload = github_get(
        "/search/code",
        params={"q": q, "per_page": str(MAX_SEARCH_RESULTS)},
    )
    if not isinstance(payload, dict):
        raise GitHubReadError("unexpected GitHub search response")
    items = payload.get("items")
    slim_items = [
        _slim_code_search_item(item)
        for item in (items if isinstance(items, list) else [])[:MAX_SEARCH_RESULTS]
    ]
    return apply_github_envelope(
        {
            "total_count": payload.get("total_count"),
            "items": slim_items,
            "truncated": bool(
                isinstance(items, list) and len(items) > len(slim_items)
            ),
            "query": trimmed_query,
        }
    )


def list_branches() -> dict[str, object]:
    repo = default_repo()
    payload = github_get(f"/repos/{repo}/branches", params={"per_page": "30"})
    items = payload if isinstance(payload, list) else []
    slim = [
        {"name": row.get("name"), "commit_sha": (row.get("commit") or {}).get("sha")}
        for row in items
        if isinstance(row, dict)
    ]
    return apply_github_envelope({"items": slim})


def list_pulls(*, state: str = "open") -> dict[str, object]:
    repo = default_repo()
    payload = github_get(
        f"/repos/{repo}/pulls",
        params={"state": state, "per_page": "20"},
    )
    items = payload if isinstance(payload, list) else []
    slim = [
        {
            "number": row.get("number"),
            "title": row.get("title"),
            "state": row.get("state"),
            "user": (row.get("user") or {}).get("login") if isinstance(row.get("user"), dict) else None,
            "html_url": row.get("html_url"),
        }
        for row in items
        if isinstance(row, dict)
    ]
    return apply_github_envelope({"items": slim})


def get_pull(number: int) -> dict[str, object]:
    repo = default_repo()
    payload = github_get(f"/repos/{repo}/pulls/{int(number)}")
    if not isinstance(payload, dict):
        raise GitHubReadError("unexpected GitHub pull response")
    return apply_github_envelope(
        {
            "number": payload.get("number"),
            "title": payload.get("title"),
            "state": payload.get("state"),
            "body": _clip_text(payload.get("body"), 4000),
            "user": (
                (payload.get("user") or {}).get("login")
                if isinstance(payload.get("user"), dict)
                else None
            ),
            "head": (
                (payload.get("head") or {}).get("ref")
                if isinstance(payload.get("head"), dict)
                else None
            ),
            "base": (
                (payload.get("base") or {}).get("ref")
                if isinstance(payload.get("base"), dict)
                else None
            ),
            "html_url": payload.get("html_url"),
        }
    )


def list_issues(*, state: str = "open") -> dict[str, object]:
    repo = default_repo()
    payload = github_get(
        f"/repos/{repo}/issues",
        params={"state": state, "per_page": "20"},
    )
    items = payload if isinstance(payload, list) else []
    slim = [
        {
            "number": row.get("number"),
            "title": row.get("title"),
            "state": row.get("state"),
            "user": (row.get("user") or {}).get("login") if isinstance(row.get("user"), dict) else None,
            "html_url": row.get("html_url"),
        }
        for row in items
        if isinstance(row, dict)
    ]
    return apply_github_envelope({"items": slim})


def get_issue(number: int) -> dict[str, object]:
    repo = default_repo()
    payload = github_get(f"/repos/{repo}/issues/{int(number)}")
    if not isinstance(payload, dict):
        raise GitHubReadError("unexpected GitHub issue response")
    return apply_github_envelope(
        {
            "number": payload.get("number"),
            "title": payload.get("title"),
            "state": payload.get("state"),
            "body": _clip_text(payload.get("body"), 4000),
            "user": (
                (payload.get("user") or {}).get("login")
                if isinstance(payload.get("user"), dict)
                else None
            ),
            "html_url": payload.get("html_url"),
        }
    )


def compare_refs(*, base: str, head: str) -> dict[str, object]:
    repo = default_repo()
    payload = github_get(f"/repos/{repo}/compare/{base}...{head}")
    if not isinstance(payload, dict):
        raise GitHubReadError("unexpected GitHub compare response")
    files = payload.get("files")
    slim_files: list[dict[str, object]] = []
    truncated = False
    if isinstance(files, list):
        if len(files) > MAX_COMPARE_FILES:
            truncated = True
        for row in files[:MAX_COMPARE_FILES]:
            if not isinstance(row, dict):
                continue
            slim_files.append(
                {
                    "filename": row.get("filename"),
                    "status": row.get("status"),
                    "additions": row.get("additions"),
                    "deletions": row.get("deletions"),
                    "changes": row.get("changes"),
                }
            )
    return apply_github_envelope(
        {
            "status": payload.get("status"),
            "ahead_by": payload.get("ahead_by"),
            "behind_by": payload.get("behind_by"),
            "total_commits": payload.get("total_commits"),
            "files": slim_files,
            "truncated": truncated,
        }
    )


def list_commits(*, sha: str | None = None, path: str | None = None) -> dict[str, object]:
    repo = default_repo()
    params: dict[str, str] = {"per_page": "20"}
    if sha:
        params["sha"] = sha
    if path:
        params["path"] = path
    payload = github_get(f"/repos/{repo}/commits", params=params)
    items = payload if isinstance(payload, list) else []
    slim = [
        {
            "sha": row.get("sha"),
            "message": _clip_text((row.get("commit") or {}).get("message"), 300),
            "author": (
                (row.get("commit") or {}).get("author", {}).get("name")
                if isinstance(row.get("commit"), dict)
                else None
            ),
            "html_url": row.get("html_url"),
        }
        for row in items
        if isinstance(row, dict)
    ]
    return apply_github_envelope({"items": slim})


def list_workflow_runs(*, branch: str | None = None) -> dict[str, object]:
    repo = default_repo()
    params: dict[str, str] = {"per_page": "10"}
    if branch:
        params["branch"] = branch
    payload = github_get(f"/repos/{repo}/actions/runs", params=params)
    if not isinstance(payload, dict):
        raise GitHubReadError("unexpected GitHub workflow runs response")
    runs = payload.get("workflow_runs")
    slim = [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "status": row.get("status"),
            "conclusion": row.get("conclusion"),
            "head_branch": row.get("head_branch"),
            "html_url": row.get("html_url"),
        }
        for row in (runs if isinstance(runs, list) else [])
        if isinstance(row, dict)
    ]
    return apply_github_envelope({"workflow_runs": slim})


def _clip_text(value: object, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
