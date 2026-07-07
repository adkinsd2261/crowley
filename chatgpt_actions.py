"""V3.9.13+ — authenticated Actions API for ChatGPT Custom GPTs."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import actions_tool_registry as registry
import crowley
import workflow

router = APIRouter(prefix="/api/actions", tags=["actions"])


class ActionsWritebackRequest(BaseModel):
    text: str | None = None
    writeback: dict[str, object] | None = None


class ActionsInvokeRequest(BaseModel):
    tool: str
    args: dict[str, object] | None = None


def configured_action_key() -> str | None:
    key = os.environ.get("CROWLEY_ACTION_KEY", "").strip()
    return key or None


def require_actions_bearer(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    expected = configured_action_key()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "actions_api_disabled",
                "message": (
                    "CROWLEY_ACTION_KEY is not configured. "
                    "Set it in the environment to enable /api/actions/*."
                ),
            },
        )
    token_candidate = ""
    if authorization and authorization.strip():
        raw_auth = authorization.strip()
        scheme, _, token = raw_auth.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            token_candidate = token.strip()
        elif not token:
            # Allow raw token in Authorization for compatibility with some clients.
            token_candidate = raw_auth
        else:
            # If a scheme is present but isn't Bearer, treat whole value as token so
            # callers get invalid_token instead of missing auth.
            token_candidate = raw_auth
    elif x_api_key and x_api_key.strip():
        raw_key = x_api_key.strip()
        scheme, _, token = raw_key.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            token_candidate = token.strip()
        else:
            token_candidate = raw_key

    if not token_candidate:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "authorization_required",
                "message": (
                    "Provide CROWLEY_ACTION_KEY via Authorization: Bearer <key> "
                    "or X-API-Key: <key>."
                ),
            },
        )
    if not hmac.compare_digest(token_candidate, expected):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token",
                "message": "Actions API token is invalid.",
            },
        )


def _database_status() -> str:
    try:
        conn = crowley.connect_db()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return "ok"
    except Exception:
        return "error"


def _safe_runtime_block() -> dict[str, object]:
    health = crowley._context_system_health()
    runtime = health.get("runtime")
    safe: dict[str, object] = {
        "embed_provider": health.get("embed_provider"),
        "retrieval_mode": health.get("retrieval_mode"),
        "sqlite_vec": health.get("sqlite_vec"),
    }
    if isinstance(runtime, dict):
        safe["test_mode"] = runtime.get("test_mode")
        safe["model"] = runtime.get("model")
    return safe


def _resolve_session_key(
    x_crowley_session: Annotated[str | None, Header(alias="X-Crowley-Session")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    token: str | None = None
    if authorization:
        _, _, token = authorization.partition(" ")
        token = token.strip() or None
    return workflow.normalize_session_key(x_crowley_session, bearer_token=token)


def _resolve_agent_id(
    x_crowley_agent: Annotated[str | None, Header(alias="X-Crowley-Agent")] = None,
) -> str:
    import agent_identity

    return agent_identity.normalize_agent_id(x_crowley_agent, fallback_source="chatgpt")


def _invoke_response(
    kind: registry.ToolKind,
    tool: str,
    args: dict[str, object] | None,
    *,
    session_key: str,
    agent_id: str,
) -> JSONResponse:
    body, status = registry.dispatch(
        kind, tool, args, session_key=session_key, agent_id=agent_id
    )
    return JSONResponse(body, status_code=status)


@router.get("/health")
def actions_health(_auth: None = Depends(require_actions_bearer)) -> JSONResponse:
    db_status = _database_status()
    status = "ok" if db_status == "ok" else "degraded"
    return JSONResponse(
        {
            "status": status,
            "version": crowley.CROWLEY_VERSION,
            "release_label": crowley.CROWLEY_RELEASE_LABEL,
            "actions_api": "enabled",
            "auth": "bearer",
            "db": db_status,
            "runtime": _safe_runtime_block(),
            "gateway": ["catalog", "read", "write"],
        }
    )


@router.get("/catalog")
def actions_catalog(_auth: None = Depends(require_actions_bearer)) -> JSONResponse:
    return JSONResponse(registry.catalog_payload())


@router.post("/read")
def actions_read(
    body: ActionsInvokeRequest,
    session_key: Annotated[str, Depends(_resolve_session_key)],
    agent_id: Annotated[str, Depends(_resolve_agent_id)],
    _auth: None = Depends(require_actions_bearer),
) -> JSONResponse:
    return _invoke_response(
        "read", body.tool, body.args, session_key=session_key, agent_id=agent_id
    )


@router.post("/write")
def actions_write(
    body: ActionsInvokeRequest,
    session_key: Annotated[str, Depends(_resolve_session_key)],
    agent_id: Annotated[str, Depends(_resolve_agent_id)],
    _auth: None = Depends(require_actions_bearer),
) -> JSONResponse:
    return _invoke_response(
        "write", body.tool, body.args, session_key=session_key, agent_id=agent_id
    )


# --- Legacy V3.9.13 aliases (deprecated; delegate to registry) ---


@router.get("/context")
def actions_context(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    q: str = Query(crowley.CONTEXT_DEFAULT_QUERY),
    limit: int = Query(8, ge=1, le=50),
    project: str | None = Query(None),
) -> JSONResponse:
    return _invoke_response(
        "read", "context.get", {"q": q, "limit": limit, "project": project},
        session_key=session_key, agent_id="chatgpt",
    )


@router.get("/retrieve")
def actions_retrieve(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=50),
) -> JSONResponse:
    return _invoke_response(
        "read", "retrieve.search", {"q": q, "limit": limit},
        session_key=session_key, agent_id="chatgpt",
    )


@router.get("/portable/packet")
def actions_portable_packet(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    project: str | None = Query(None),
) -> JSONResponse:
    return _invoke_response(
        "read", "portable.packet", {"project": project},
        session_key=session_key, agent_id="chatgpt",
    )


@router.post("/writeback/parse")
def actions_writeback_parse(
    body: ActionsWritebackRequest,
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
) -> JSONResponse:
    payload: dict[str, object] = {}
    if body.writeback is not None:
        payload["writeback"] = body.writeback
    if body.text:
        payload["text"] = body.text
    return _invoke_response(
        "write", "writeback.parse", payload, session_key=session_key, agent_id="chatgpt"
    )


@router.post("/writeback/ingest")
def actions_writeback_ingest(
    body: ActionsWritebackRequest,
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    project: str = Query("crowley", min_length=1),
) -> JSONResponse:
    payload: dict[str, object] = {"project": project}
    if body.writeback is not None:
        payload["writeback"] = body.writeback
    if body.text:
        payload["text"] = body.text
    return _invoke_response(
        "write", "writeback.ingest", payload, session_key=session_key, agent_id="chatgpt"
    )


@router.get("/writeback/acceptance")
def actions_writeback_acceptance(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    refresh: bool = Query(False),
    apply: bool = Query(False),
) -> JSONResponse:
    return _invoke_response(
        "read",
        "writeback.acceptance",
        {"refresh": refresh, "apply": apply},
        session_key=session_key,
        agent_id="chatgpt",
    )


@router.get("/agent/sync")
def actions_agent_sync(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    agent: str = Query("chatgpt", min_length=1),
    limit: int = Query(20, ge=1, le=50),
) -> JSONResponse:
    return _invoke_response(
        "read",
        "agent.sync",
        {"agent": agent, "limit": limit},
        session_key=session_key,
        agent_id="chatgpt",
    )


@router.get("/agent/deep_sync")
def actions_agent_deep_sync(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    section: str = Query(..., min_length=1),
    agent: str = Query("chatgpt", min_length=1),
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
) -> JSONResponse:
    return _invoke_response(
        "read",
        "agent.deep_sync",
        {
            "agent": agent,
            "section": section,
            "cursor": cursor,
            "limit": limit,
        },
        session_key=session_key,
        agent_id="chatgpt",
    )


@router.get("/github/status")
def actions_github_status(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
) -> JSONResponse:
    return _invoke_response(
        "read",
        "github.status",
        {},
        session_key=session_key,
        agent_id="chatgpt",
    )


@router.get("/github/file")
def actions_github_file(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    path: str = Query(..., min_length=1),
    ref: str | None = Query(None),
) -> JSONResponse:
    return _invoke_response(
        "read",
        "github.file",
        {"path": path, "ref": ref},
        session_key=session_key,
        agent_id="chatgpt",
    )


@router.get("/github/search_code")
def actions_github_search_code(
    session_key: Annotated[str, Depends(_resolve_session_key)],
    _auth: None = Depends(require_actions_bearer),
    q: str = Query(..., min_length=1),
    ref: str | None = Query(None),
) -> JSONResponse:
    return _invoke_response(
        "read",
        "github.search_code",
        {"q": q, "ref": ref},
        session_key=session_key,
        agent_id="chatgpt",
    )
