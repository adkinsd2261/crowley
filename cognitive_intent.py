"""V4.2 T1 — deterministic cognitive ingest intent gate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import sparks

IntentKind = Literal["store", "ignore", "temporary"]

_GREETING_TOKENS = frozenset({
    "hey",
    "hi",
    "hello",
    "ok",
    "okay",
    "lol",
    "thanks",
    "thank",
    "you",
    "sure",
    "yep",
    "yeah",
    "k",
})
_TEMPORARY_MARKERS = (
    "remind me later",
    "remind me later today",
    "just for this session",
    "only for today",
    "temporary note",
    "don't store this",
    "do not store this",
    "later today only",
)
_SLASH_COMMAND_RE = re.compile(r"^\s*/(?:task|remember|note|help)\b", re.IGNORECASE)
_SUBSTANTIVE_MIN_CHARS = 40
_SUBSTANTIVE_MIN_WORDS = 6
_LOW_CONFIDENCE_THRESHOLD = 0.6
LOW_CONFIDENCE_THRESHOLD = _LOW_CONFIDENCE_THRESHOLD


@dataclass(frozen=True)
class MemoryIntentResult:
    intent: IntentKind
    confidence: float
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _is_noise_greeting(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    if not normalized:
        return True
    tokens = normalized.split()
    if tokens and all(token in _GREETING_TOKENS for token in tokens):
        return True
    return normalized in _GREETING_TOKENS


def _is_substantive(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) >= _SUBSTANTIVE_MIN_CHARS:
        return True
    words = _normalize_text(stripped).split()
    return len(words) >= _SUBSTANTIVE_MIN_WORDS


def is_all_noise_document(text: str) -> bool:
    """True when the entire paste is empty or greeting/noise only."""
    stripped = _normalize_text(str(text or ""))
    if not stripped or sparks._meaningful_char_count(stripped) < 4:
        return True
    return _is_noise_greeting(stripped)


def classify_ingest_precheck(text: str) -> MemoryIntentResult | None:
    """
    Hard blocks for long ingest only. Returns None to proceed to chunking.
    Does not classify temporary markers or partial noise on mixed documents.
    """
    stripped = _normalize_text(str(text or ""))
    security_errors = sparks._spark_content_security_errors(stripped)
    if security_errors:
        return MemoryIntentResult("ignore", 0.95, "content_security")
    if is_all_noise_document(text):
        return MemoryIntentResult("ignore", 0.85, "all_noise")
    return None


CHUNKED_INGEST_INTENT = MemoryIntentResult("store", 0.92, "chunked_ingest")


def classify_memory_intent(text: str) -> MemoryIntentResult:
    """Rules-first intent classification before spark extraction."""
    stripped = _normalize_text(str(text or ""))
    lowered = stripped.lower()

    security_errors = sparks._spark_content_security_errors(stripped)
    if security_errors:
        return MemoryIntentResult("ignore", 0.95, "content_security")

    if stripped.startswith("/") or _SLASH_COMMAND_RE.match(stripped):
        return MemoryIntentResult("ignore", 0.9, "slash_command")

    if not stripped or sparks._meaningful_char_count(stripped) < 4 or _is_noise_greeting(stripped):
        return MemoryIntentResult("ignore", 0.85, "noise_greeting")

    if any(marker in lowered for marker in _TEMPORARY_MARKERS):
        return MemoryIntentResult("temporary", 0.88, "temporary_marker")

    if _is_substantive(stripped):
        return MemoryIntentResult("store", 0.92, "substantive_content")

    return MemoryIntentResult("store", 0.45, "ambiguous_content")
