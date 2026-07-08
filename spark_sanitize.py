"""V4 T19 — prompt injection sanitization for cognitive memory text."""

from __future__ import annotations

import re
from typing import Any

import sparks

MEMORY_DATA_BEGIN = "<<<MEMORY_DATA>>>"
MEMORY_DATA_END = "<<<END_MEMORY_DATA>>>"
NEUTRALIZED_INSTRUCTION = "[neutralized instruction]"

_EXTRA_INSTRUCTION_MARKERS = (
    "forget everything",
    "you are now",
)

_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def unwrap_memory_data(text: str) -> str:
    """Strip one outer MEMORY_DATA delimiter pair when present."""
    body = str(text or "").strip()
    if not body.startswith(MEMORY_DATA_BEGIN) or not body.endswith(MEMORY_DATA_END):
        return str(text or "")
    inner = body[len(MEMORY_DATA_BEGIN) :].strip()
    if inner.endswith(MEMORY_DATA_END):
        inner = inner[: -len(MEMORY_DATA_END)].strip()
    return inner


def is_wrapped_memory_data(text: str) -> bool:
    body = str(text or "").strip()
    return body.startswith(MEMORY_DATA_BEGIN) and body.endswith(MEMORY_DATA_END)


def _instruction_markers() -> tuple[str, ...]:
    return sparks._SPARK_INSTRUCTION_MARKERS + _EXTRA_INSTRUCTION_MARKERS


def neutralize_instructions(text: str) -> str:
    """Replace instruction-like marker phrases with a neutral token."""
    result = str(text or "")
    for marker in sorted(_instruction_markers(), key=len, reverse=True):
        pattern = re.compile(re.escape(marker), re.IGNORECASE)
        result = pattern.sub(NEUTRALIZED_INSTRUCTION, result)
    return result


def redact_secrets(text: str) -> str:
    """Redact API key and bearer token patterns from memory text."""
    result = _SK_KEY_RE.sub("sk-[REDACTED]", str(text or ""))
    return _BEARER_RE.sub("Bearer [REDACTED]", result)


def wrap_memory_data(text: str) -> str:
    """Wrap sanitized memory text in deterministic delimiters."""
    if is_wrapped_memory_data(text):
        return str(text or "").strip()
    body = str(text or "")
    if not body:
        return f"{MEMORY_DATA_BEGIN}\n{MEMORY_DATA_END}"
    return f"{MEMORY_DATA_BEGIN}\n{body}\n{MEMORY_DATA_END}"


def sanitize_memory_text(text: str) -> str:
    """Full output pipeline: neutralize, redact, then delimiter-wrap."""
    body = unwrap_memory_data(str(text or ""))
    return wrap_memory_data(redact_secrets(neutralize_instructions(body)))


def _sanitize_field(value: object) -> str:
    return sanitize_memory_text(str(value or ""))


def sanitize_cognitive_context_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with injectable text fields sanitized (output-only)."""
    result = dict(payload)

    for key in ("core_sparks", "supporting_sparks"):
        items = result.get(key)
        if not isinstance(items, list):
            continue
        sanitized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            copy = dict(item)
            if "content" in copy:
                copy["content"] = _sanitize_field(copy["content"])
            sanitized.append(copy)
        result[key] = sanitized

    patterns = result.get("patterns")
    if isinstance(patterns, list):
        sanitized_patterns: list[dict[str, Any]] = []
        for item in patterns:
            if not isinstance(item, dict):
                continue
            copy = dict(item)
            if "content" in copy:
                copy["content"] = _sanitize_field(copy["content"])
            if "reasoning" in copy:
                copy["reasoning"] = _sanitize_field(copy["reasoning"])
            sanitized_patterns.append(copy)
        result["patterns"] = sanitized_patterns

    fallback = result.get("memory_fallback")
    if isinstance(fallback, list):
        sanitized_fallback: list[dict[str, Any]] = []
        for item in fallback:
            if not isinstance(item, dict):
                continue
            copy = dict(item)
            if "content" in copy:
                copy["content"] = _sanitize_field(copy["content"])
            sanitized_fallback.append(copy)
        result["memory_fallback"] = sanitized_fallback

    return result
