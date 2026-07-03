#!/usr/bin/env python3
"""Crowley V3.9.13 — local web transport layer (FastAPI). Engine logic lives in crowley.py."""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Iterator, Literal

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import crowley
from chatgpt_actions import router as actions_router

HOST = "127.0.0.1"
PORT = 8765
STATIC_DIR = Path(__file__).parent / "static"

SLASH_COMMAND_HINT = (
    "Slash commands are for the terminal, not web chat. "
    "Run: python crowley.py — then use /state, /task, /remember, and similar commands."
)

CHAT_USER_ERROR_MESSAGES = {
    "model unavailable": (
        "Crowley couldn't reach the model. Check your API key or Ollama, then try again."
    ),
    "empty response": (
        "Crowley didn't get a response back. Try again in a moment."
    ),
}


def chat_error_message(error: str) -> str:
    """Map internal chat errors to clear user-facing copy."""
    return CHAT_USER_ERROR_MESSAGES.get(error, error)

app = FastAPI(title="Crowley", docs_url=None, redoc_url=None)
app.include_router(actions_router)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class IngestRequest(BaseModel):
    source: Literal["cursor", "chatgpt", "codex", "manual", "crowley"]
    type: Literal[
        "builder_handoff",
        "architect_handoff",
        "session_summary",
        "project_update",
        "qa_result",
        "note",
    ]
    project: str = "crowley"
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class CreateTicketRequest(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    assignee: Literal["codex", "cursor", "crowley", "mr_go", "unassigned"] = "unassigned"
    priority: int = Field(default=2, ge=1, le=4)
    parent_id: int | None = None
    blocked_by_ticket_id: int | None = None
    source: Literal["codex", "cursor", "crowley", "mr_go", "manual", "system"] = "manual"
    actor: str = "system"
    status: Literal["open", "claimed", "in_progress", "blocked", "done", "cancelled"] = "open"


class UpdateTicketRequest(BaseModel):
    actor: str = Field(min_length=1)
    status: Literal["open", "claimed", "in_progress", "blocked", "done", "cancelled"] | None = None
    assignee: Literal["codex", "cursor", "crowley", "mr_go", "unassigned"] | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    description: str | None = None
    blocked_by_ticket_id: int | None = None
    clear_blocked_by: bool = False
    comment: str | None = None
    linked_memory_id: int | None = None


class CancelTicketRequest(BaseModel):
    actor: str = Field(min_length=1)
    comment: str = Field(min_length=1)


class ActivityPulseRequest(BaseModel):
    agent: Literal["cursor", "codex", "crowley", "mr_go"]
    verb: Literal[
        "session_start",
        "claimed",
        "working",
        "note",
        "handoff",
        "minted",
        "closed",
    ]
    summary: str | None = None
    ticket_id: int | None = None


@app.on_event("startup")
def on_startup() -> None:
    crowley.setup_db()


class BrainSettingRequest(BaseModel):
    provider: Literal["auto", "openai", "ollama", "anthropic"]
    model: str | None = None


class PortableWritebackParseRequest(BaseModel):
    text: str | None = None
    writeback: dict[str, object] | None = None


@app.get("/api/brain")
def api_brain_get() -> JSONResponse:
    return JSONResponse(crowley.get_brain_snapshot())


@app.post("/api/brain")
def api_brain_set(body: BrainSettingRequest) -> JSONResponse:
    try:
        crowley.set_brain_config(body.provider, body.model)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(crowley.get_brain_snapshot())


@app.get("/api/health")
def api_health() -> JSONResponse:
    db_status = _database_status()
    health = crowley._context_system_health()
    status = "ok" if db_status == "ok" else "degraded"
    if health.get("embed_provider") == "off":
        status = "degraded" if status == "ok" else status
    return JSONResponse(
        {
            "status": status,
            "version": crowley.CROWLEY_VERSION,
            "release_label": crowley.CROWLEY_RELEASE_LABEL,
            "brain": crowley._brain_banner_label(),
            "brain_config": crowley.get_brain_snapshot(),
            "provider": crowley.get_model_provider(),
            "db": db_status,
            "embed_provider": health.get("embed_provider"),
            "sqlite_vec": health.get("sqlite_vec"),
            "retrieval_mode": health.get("retrieval_mode"),
            "runtime": health.get("runtime"),
        }
    )


@app.get("/api/portable/packet")
def api_portable_packet(
    surface: str = Query("chatgpt", min_length=1),
    project: str | None = Query(None),
) -> JSONResponse:
    try:
        packet = crowley.build_portable_context_packet(
            surface, project_slug=project
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


@app.post("/api/portable/writeback/parse")
def api_portable_writeback_parse(
    body: PortableWritebackParseRequest,
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


@app.post("/api/portable/writeback/ingest")
def api_portable_writeback_ingest(
    body: PortableWritebackParseRequest,
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


@app.get("/api/metrics/summary")
def api_metrics_summary() -> JSONResponse:
    return JSONResponse(crowley.get_metrics_summary_24h())


@app.get("/api/messages")
def api_messages(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    rows = crowley.list_recent_messages(limit)
    return JSONResponse(
        {"messages": [crowley.row_to_dict(row) for row in rows]}
    )


@app.get("/api/context")
def api_context(
    q: str = Query(crowley.CONTEXT_DEFAULT_QUERY),
    limit: int = Query(8, ge=1, le=50),
    project: str | None = Query(None),
) -> JSONResponse:
    try:
        bundle = crowley.build_context_bundle(q=q, limit=limit, project_slug=project)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse(bundle)


@app.get("/api/retrieve")
def api_retrieve(
    q: str = Query(..., min_length=1),
    limit: int = Query(8, ge=1, le=50),
) -> JSONResponse:
    return JSONResponse(crowley.retrieve_memories_api(q=q, limit=limit))


@app.get("/api/events/recent")
def api_events_recent(limit: int = Query(20, ge=1, le=50)) -> JSONResponse:
    return JSONResponse(crowley.list_recent_agent_events_api(limit=limit))


@app.get("/api/agent/sync")
def api_agent_sync(
    agent: Literal["cursor", "codex", "chatgpt"] = Query(...),
    limit: int = Query(20, ge=1, le=50),
) -> JSONResponse:
    try:
        return JSONResponse(crowley.build_agent_sync_bundle(agent=agent, limit=limit))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/activity/pulse")
def api_activity_pulse(body: ActivityPulseRequest) -> JSONResponse:
    project = crowley.get_active_project()
    if project is None:
        return JSONResponse({"error": "no active project"}, status_code=400)
    result = crowley.record_activity_pulse(
        body.agent,
        body.verb,
        project_id=int(project["id"]),
        ticket_id=body.ticket_id,
        summary=body.summary,
    )
    if result is None:
        return JSONResponse({"error": "pulse not recorded"}, status_code=400)
    return JSONResponse({"ok": True, "pulse": result}, status_code=201)


@app.post("/api/ingest")
def api_ingest(body: IngestRequest) -> JSONResponse:
    try:
        result = crowley.ingest_handoff(
            source=body.source,
            handoff_type=body.type,
            content=body.content,
            project=body.project,
            metadata=body.metadata,
        )
    except crowley.IngestHandoffError as exc:
        return JSONResponse({"status": "error", "error": exc.message}, status_code=400)
    except ValueError as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=404)
    if result.get("status") != "ok":
        return JSONResponse(result, status_code=500)
    return JSONResponse(result)


@app.get("/api/bus/health")
def api_bus_health() -> JSONResponse:
    return JSONResponse(crowley.bus_health())


@app.get("/api/world")
def api_world() -> JSONResponse:
    return JSONResponse(crowley.build_world_dashboard())


@app.get("/api/tasks")
def api_tasks(status: str = Query("open")) -> JSONResponse:
    rows = crowley.list_tasks(status=status)
    return JSONResponse({"tasks": [crowley.row_to_dict(row) for row in rows]})


@app.post("/api/tasks/{task_id}/done")
def api_task_done(task_id: int) -> JSONResponse:
    task = crowley.get_task_by_id(task_id)
    if task is None:
        return JSONResponse({"error": f"task not found: {task_id}"}, status_code=404)
    if str(task["status"]) == "done":
        return JSONResponse({"ok": True, "task_id": task_id, "already_done": True})
    if not crowley.complete_task(task_id):
        return JSONResponse({"error": "task unchanged"}, status_code=400)
    return JSONResponse({"ok": True, "task_id": task_id})


@app.get("/api/tickets")
def api_tickets(
    status: str = Query("open"),
    assignee: str | None = Query(None),
    priority: int | None = Query(None, ge=1, le=4),
    parent_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    project = crowley.get_active_project()
    project_id = int(project["id"]) if project is not None else None
    open_only = status.strip().lower() == "open"
    status_filter = None if open_only else status
    rows = crowley.list_tickets(
        project_id=project_id,
        status=status_filter,
        open_only=open_only,
        assignee=assignee,
        priority_max=priority,
        parent_id=parent_id,
        limit=limit,
        offset=offset,
    )
    total = crowley.count_tickets(
        project_id=project_id,
        status=None if open_only else status_filter,
        open_only=open_only,
        assignee=assignee,
    )
    return JSONResponse(
        {
            "tickets": [crowley.row_to_dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


@app.get("/api/tickets/{ticket_id}")
def api_ticket_detail(ticket_id: int) -> JSONResponse:
    detail = crowley.get_ticket_detail(ticket_id)
    if detail is None:
        return JSONResponse({"error": f"ticket not found: {ticket_id}"}, status_code=404)
    return JSONResponse(detail)


@app.post("/api/tickets")
def api_ticket_create(body: CreateTicketRequest) -> JSONResponse:
    try:
        result = crowley.create_ticket(
            body.title,
            description=body.description,
            assignee=body.assignee,
            priority=body.priority,
            parent_id=body.parent_id,
            blocked_by_ticket_id=body.blocked_by_ticket_id,
            source=body.source,
            actor=body.actor,
            status=body.status,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result, status_code=201)


@app.patch("/api/tickets/{ticket_id}")
def api_ticket_update(ticket_id: int, body: UpdateTicketRequest) -> JSONResponse:
    try:
        result = crowley.update_ticket(
            ticket_id,
            actor=body.actor,
            status=body.status,
            assignee=body.assignee,
            priority=body.priority,
            description=body.description,
            blocked_by_ticket_id=body.blocked_by_ticket_id,
            comment=body.comment,
            linked_memory_id=body.linked_memory_id,
            clear_blocked_by=body.clear_blocked_by,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse(result)


@app.post("/api/tickets/{ticket_id}/done")
def api_ticket_done(ticket_id: int, actor: str = Query("system")) -> JSONResponse:
    row = crowley.get_ticket_by_id(ticket_id)
    if row is None:
        return JSONResponse({"error": f"ticket not found: {ticket_id}"}, status_code=404)
    if str(row["status"]) == "done":
        return JSONResponse({"ok": True, "ticket_id": ticket_id, "already_done": True})
    try:
        result = crowley.complete_ticket(ticket_id, actor=actor)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, **result})


@app.post("/api/tickets/{ticket_id}/cancel")
def api_ticket_cancel(ticket_id: int, body: CancelTicketRequest) -> JSONResponse:
    row = crowley.get_ticket_by_id(ticket_id)
    if row is None:
        return JSONResponse({"error": f"ticket not found: {ticket_id}"}, status_code=404)
    if str(row["status"]) == "cancelled":
        return JSONResponse(
            {"ok": True, "ticket_id": ticket_id, "already_cancelled": True}
        )
    try:
        result = crowley.cancel_ticket(
            ticket_id,
            actor=body.actor,
            comment=body.comment,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, **result})


@app.get("/api/loops")
def api_loops() -> JSONResponse:
    project = crowley.get_active_project()
    if project is None:
        return JSONResponse({"loops": []})
    rows = crowley.list_open_loops(int(project["id"]))
    return JSONResponse({"loops": [crowley.row_to_dict(row) for row in rows]})


@app.get("/api/decisions")
def api_decisions(limit: int = Query(10, ge=1, le=50)) -> JSONResponse:
    project = crowley.get_active_project()
    if project is None:
        return JSONResponse({"decisions": []})
    rows = crowley.list_decisions(int(project["id"]), limit=limit)
    return JSONResponse({"decisions": [crowley.row_to_dict(row) for row in rows]})


@app.get("/api/sparks")
def api_sparks(limit: int = Query(10, ge=1, le=50)) -> JSONResponse:
    rows = crowley.list_recent_summary_sparks(limit=limit)
    return JSONResponse({"sparks": [crowley.row_to_dict(row) for row in rows]})


@app.get("/api/memory-items")
def api_memory_items(
    q: str | None = Query(None),
    source: str | None = Query(None),
    memory_type: str | None = Query(None),
    status: str = Query("active"),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    rows, total = crowley.list_memory_items(
        q=q,
        source=source,
        memory_type=memory_type,
        status=status,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(
        {
            "items": [crowley._memory_item_api_dict(row) for row in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "filters": {
                "q": q or "",
                "source": source or "",
                "memory_type": memory_type or "",
                "status": status,
            },
        }
    )


@app.post("/api/consolidate")
def api_consolidate(
    run_type: str = Query("all"),
    dry_run: bool = Query(False),
) -> JSONResponse:
    try:
        result = crowley.consolidate_memories(run_type, dry_run=dry_run)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result)


@app.get("/api/memory/hygiene")
@app.get("/api/hygiene")
def api_memory_hygiene() -> JSONResponse:
    return JSONResponse(crowley.memory_hygiene_report_api())


@app.get("/api/diagnostics")
def api_diagnostics() -> StreamingResponse:
    return StreamingResponse(
        _diagnostics_sse_stream(),
        media_type="text/event-stream",
        headers=_sse_headers(),
    )


@app.post("/api/chat")
def api_chat(body: ChatRequest) -> StreamingResponse:
    message = body.message.strip()
    if not message:
        return StreamingResponse(
            _sse_once("error", {"message": "Message cannot be empty."}),
            media_type="text/event-stream",
        )
    if crowley.is_slash_command(message):
        return StreamingResponse(
            _sse_once("error", {"message": SLASH_COMMAND_HINT}),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        _chat_sse_stream(message),
        media_type="text/event-stream",
        headers=_sse_headers(),
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


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _sse_once(event: str, data: dict[str, object]) -> Iterator[str]:
    yield _sse_event(event, data)


def _sse_headers() -> dict[str, str]:
    return {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _chat_sse_stream(message: str) -> Iterator[str]:
    yield _sse_event("status", {"phase": "thinking"})

    token_queue: queue.Queue[object] = queue.Queue()
    done_sentinel = object()
    result_holder: list[crowley.ChatTurnResult] = []

    def on_token(token: str) -> None:
        token_queue.put(token)

    def worker() -> None:
        try:
            result_holder.append(
                crowley.chat_turn(message, on_token=on_token, quiet_errors=True)
            )
        finally:
            token_queue.put(done_sentinel)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while True:
        item = token_queue.get()
        if item is done_sentinel:
            break
        yield _sse_event("token", {"text": str(item)})

    thread.join(timeout=600)

    if not result_holder:
        crowley.record_system_metric("chat_error", label="no_result")
        yield _sse_event("error", {"message": "Chat turn failed. Try again."})
        return

    result = result_holder[0]
    if result.error:
        crowley.record_system_metric("chat_error", label=str(result.error)[:80])
        yield _sse_event("error", {"message": chat_error_message(result.error)})
        return

    yield _sse_event(
        "done",
        {
            "reply": result.reply,
            "user_message_id": result.user_message_id,
            "assistant_message_id": result.assistant_message_id,
        },
    )


def _diagnostics_sse_stream() -> Iterator[str]:
    yield _sse_event("status", {"phase": "thinking"})

    parts: list[str] = []
    try:
        for token in crowley.iter_diagnostics_tokens():
            parts.append(token)
            yield _sse_event("token", {"text": token})
    except Exception as exc:
        yield _sse_event("error", {"message": str(exc)})
        return

    reply = "".join(parts).strip()
    if not reply:
        yield _sse_event("error", {"message": "Diagnostics returned no content."})
        return

    yield _sse_event("done", {"reply": reply})


if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host=HOST, port=PORT)
