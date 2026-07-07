"""Runtime guards for ChatGPT Actions tool dispatch."""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any, Callable

ToolHandler = Callable[[dict[str, Any]], tuple[dict[str, Any], int | None]]

DEFAULT_TOOL_TIMEOUT_SECONDS = 30
TOOL_TIMEOUT_SECONDS: dict[str, int] = {
    "agent.sync": 45,
    "agent.deep_sync": 60,
    "writeback.ingest": 90,
    "writeback.acceptance": 60,
    "handoff.ingest": 60,
    "note.ingest": 60,
    "qa.bundle": 45,
    "retrieve.search": 30,
    "inspect.invariant_checks": 45,
}

HEAVY_TOOLS: frozenset[str] = frozenset(TOOL_TIMEOUT_SECONDS.keys())
_HEAVY_TOOL_SLOTS = 2
_heavy_semaphore = threading.Semaphore(_HEAVY_TOOL_SLOTS)
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="actions-tool",
)


def tool_timeout_seconds(tool_name: str) -> int:
    return int(TOOL_TIMEOUT_SECONDS.get(tool_name, DEFAULT_TOOL_TIMEOUT_SECONDS))


def invoke_tool_handler(
    tool_name: str,
    handler: ToolHandler,
    args: dict[str, Any],
) -> tuple[dict[str, Any] | None, int | None, str | None]:
    """Run a tool handler with concurrency + timeout guards.

    Returns (body, status, error_code). error_code is set on timeout/busy.
    """
    timeout = tool_timeout_seconds(tool_name)
    heavy = tool_name in HEAVY_TOOLS
    acquired = True
    if heavy:
        acquired = _heavy_semaphore.acquire(timeout=5)
        if not acquired:
            return (
                None,
                503,
                "server_busy",
            )

    try:
        future = _executor.submit(handler, args)
        body, status = future.result(timeout=timeout)
        return body, status, None
    except concurrent.futures.TimeoutError:
        future.cancel()
        return None, 504, "tool_timeout"
    except Exception:
        raise
    finally:
        if heavy and acquired:
            _heavy_semaphore.release()
