"""V4.2 T3 — rules-first document chunking for long cognitive ingest."""

from __future__ import annotations

import re
from dataclasses import dataclass

CHUNK_THRESHOLD_CHARS = 4096
MAX_CHUNK_CHARS = 3500
MAX_CHUNKS = 8
MIN_CHUNK_CHARS = 80

_HEADING_SPLIT_RE = re.compile(r"(?m)(?=^#{1,6}\s)")
_HRULE_SPLIT_RE = re.compile(r"(?m)^---+\s*$")


@dataclass(frozen=True)
class CognitiveChunk:
    index: int
    text: str
    break_reason: str  # single | heading | paragraph | size_limit


@dataclass(frozen=True)
class ChunkingResult:
    chunks: list[CognitiveChunk]
    truncated: bool
    omitted_chunk_count: int


def _split_on_headings(text: str) -> list[str]:
    if not re.search(r"(?m)^#{1,6}\s", text):
        return [text.strip()] if text.strip() else []
    parts = _HEADING_SPLIT_RE.split(text)
    return [part.strip() for part in parts if part.strip()]


def _split_on_hrules(segments: list[str]) -> list[str]:
    out: list[str] = []
    for segment in segments:
        for part in _HRULE_SPLIT_RE.split(segment):
            stripped = part.strip()
            if stripped:
                out.append(stripped)
    return out


def _split_on_paragraphs(segments: list[str]) -> list[str]:
    out: list[str] = []
    for segment in segments:
        for part in re.split(r"\n\n+", segment):
            stripped = part.strip()
            if stripped:
                out.append(stripped)
    return out


def _merge_small_segments(segments: list[str]) -> list[str]:
    if not segments:
        return []
    merged = [segments[0]]
    for segment in segments[1:]:
        if len(segment) < MIN_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]}\n\n{segment}"
        else:
            merged.append(segment)
    return merged


def _segment_break_reason(segment: str) -> str:
    if re.match(r"(?m)^#{1,6}\s", segment):
        return "heading"
    return "paragraph"


def _pack_segment(segment: str) -> list[tuple[str, str]]:
    if len(segment) <= MAX_CHUNK_CHARS:
        return [(segment, _segment_break_reason(segment))]

    pieces: list[tuple[str, str]] = []
    start = 0
    while start < len(segment):
        end = min(start + MAX_CHUNK_CHARS, len(segment))
        if end < len(segment):
            cut = segment.rfind("\n\n", start, end)
            if cut <= start:
                cut = segment.rfind(" ", start, end)
            if cut > start:
                end = cut
        piece = segment[start:end].strip()
        if piece:
            reason = "size_limit" if end < len(segment) else _segment_break_reason(piece)
            pieces.append((piece, reason))
        if end <= start:
            end = min(start + MAX_CHUNK_CHARS, len(segment))
            piece = segment[start:end].strip()
            if piece:
                pieces.append((piece, "size_limit"))
            start = end
        else:
            start = end
    return pieces


def chunk_cognitive_text(text: str) -> ChunkingResult:
    """Split long ingest text into bounded chunks for per-chunk intent + extraction."""
    stripped = str(text or "").strip()
    if len(stripped) <= CHUNK_THRESHOLD_CHARS:
        return ChunkingResult(
            chunks=[CognitiveChunk(0, stripped, "single")],
            truncated=False,
            omitted_chunk_count=0,
        )

    segments = _split_on_headings(stripped)
    segments = _split_on_hrules(segments)
    segments = _split_on_paragraphs(segments)
    segments = _merge_small_segments(segments)

    packed: list[tuple[str, str]] = []
    for segment in segments:
        packed.extend(_pack_segment(segment))

    if not packed:
        return ChunkingResult(
            chunks=[CognitiveChunk(0, stripped, "single")],
            truncated=False,
            omitted_chunk_count=0,
        )

    truncated = len(packed) > MAX_CHUNKS
    omitted = max(0, len(packed) - MAX_CHUNKS)
    if truncated:
        packed = packed[:MAX_CHUNKS]

    chunks = [
        CognitiveChunk(index=index, text=chunk_text, break_reason=reason)
        for index, (chunk_text, reason) in enumerate(packed)
    ]
    return ChunkingResult(
        chunks=chunks,
        truncated=truncated,
        omitted_chunk_count=omitted,
    )
