"""V3.9.13 — narrow authenticated Actions API for ChatGPT Custom GPTs."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import crowley

router = APIRouter(prefix="/api/actions", tags=["actions"])


class ActionsWritebackRequest(BaseModel):
    text: str | None = None
    writeback: dict[str, object] | None = None


def configured_action_key() -> str | None:
    key = os.environ.get("CROWLEY_ACTION_KEY", "").strip()
    return key or None


def require_actions_bearer(
    authorization: Annotated[str | None, Header()] = None,
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
    if not authorization or not authorization.strip():
        raise HTTPException(
            status_code=401,
            detail={
                "error": "authorization_required",
                "message": "Authorization: Bearer <CROWLEY_ACTION_KEY> is required.",
            },
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_authorization_scheme",
                "message": "Authorization must use the Bearer scheme.",
            },
        )
    if not hmac.compare_digest(token.strip(), expected):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_token",
                "message": "Bearer token is invalid.",
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
        }
    )


@router.get("/context")
def actions_context(
    _auth: None = Depends(require_actions_bearer),
    q: str = Query(crowley.CONTEXT_DEFAULT_QUERY),
    limit: int = Query(8, ge=1, le=50),
    project: str | None = Query(None),
) -> JSONResponse:
    try:
        bundle = crowley.build_context_bundle(q=q, limit=limit, project_slug=project)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse(bundle)


@router.get("/retrieve")
def actions_retrieve(
    _auth: None = Depends(require_actions_bearer),
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=50),
) -> JSONResponse:
    return JSONResponse(crowley.retrieve_memories_api(q=q, limit=limit))


@router.get("/portable/packet")
def actions_portable_packet(
    _auth: None = Depends(require_actions_bearer),
    project: str | None = Query(None),
) -> JSONResponse:
    try:
        packet = crowley.build_portable_context_packet(
            "chatgpt", project_slug=project
        )
        markdown = crowley.render_portable_context_packet_markdown(packet)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse(
        {
            "packet": packet,
            "markdown": markdown,
            "char_count": len(markdown),
            "trimmed": bool(packet.get("trimmed")),
        }
    )


@router.post("/writeback/parse")
def actions_writeback_parse(
    body: ActionsWritebackRequest,
    _auth: None = Depends(require_actions_bearer),
) -> JSONResponse:
    if body.writeback is not None:
        result = crowley.parse_terminal_writeback(body.writeback)
    elif body.text:
        result = crowley.parse_terminal_writeback(body.text)
    else:
        return JSONResponse(
            {"ok": False, "errors": ["text or writeback object is required"]},
            status_code=400,
        )
    if not result.ok:
        return JSONResponse(
            {"ok": False, "errors": result.errors},
            status_code=400,
        )
    return JSONResponse({"ok": True, "writeback": result.writeback})


@router.post("/writeback/ingest")
def actions_writeback_ingest(
    body: ActionsWritebackRequest,
    _auth: None = Depends(require_actions_bearer),
    project: str = Query("crowley", min_length=1),
) -> JSONResponse:
    try:
        if body.writeback is not None:
            result = crowley.ingest_terminal_writeback(body.writeback, project=project)
        elif body.text:
            result = crowley.ingest_terminal_writeback(body.text, project=project)
        else:
            return JSONResponse(
                {"status": "error", "errors": ["text or writeback object is required"]},
                status_code=400,
            )
    except ValueError as exc:
        return JSONResponse({"status": "error", "errors": [str(exc)]}, status_code=404)
    if result.get("status") != "ok":
        return JSONResponse(result, status_code=400)
    return JSONResponse(result, status_code=201)
