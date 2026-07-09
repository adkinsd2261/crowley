"""V4 T4/T5 — LLM spark extraction with strict JSON + validate_spark gate."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import crowley
import sparks

MAX_SPARKS_PER_EXTRACTION = 5
MIN_TOTAL_CONTENT_LENGTH = 40
MAX_RETRY_ERROR_CHARS = 500

# Bump when _build_attempt_*_messages prompts change (invalidates cache fingerprints).
EXTRACTION_PROMPT_VERSION = "v1"

_CANONICAL_SPARK_KEYS = (
    "content",
    "lane",
    "why_keep",
    "worth_reason",
    "confidence",
    "sensitivity",
    "spark_type",
    "certainty",
    "secondary_lanes_json",
    "exposure_class",
)

_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "tests" / "fixtures" / "spark_extraction_valid.json"
)

_extraction_cache: dict[str, list[dict[str, object]]] = {}


@dataclass(frozen=True)
class SparkExtractionResult:
    ok: bool
    sparks: list[dict[str, object]]
    errors: list[str]
    attempts: int = 0
    cache_hit: bool = False


def clear_extraction_cache() -> None:
    """Clear the in-process receipt-hash extraction cache."""
    _extraction_cache.clear()


def receipt_fingerprint(source_text: str) -> str:
    """Stable fingerprint for identical receipt text + prompt version."""
    normalized = " ".join(source_text.split())
    payload = f"{EXTRACTION_PROMPT_VERSION}\n{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonicalize_spark_batch(
    sparks_batch: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Normalize key order and batch sort for comparable validated output."""
    canonical: list[dict[str, object]] = []
    for spark in sparks_batch:
        item: dict[str, object] = {}
        for key in _CANONICAL_SPARK_KEYS:
            if key not in spark:
                continue
            value = spark[key]
            if key == "secondary_lanes_json":
                lanes, lane_errors = sparks._decode_secondary_lanes(value)
                if not lane_errors and lanes is not None:
                    value = json.dumps(sorted(lanes), ensure_ascii=False)
                else:
                    value = str(value)
            item[key] = value
        canonical.append(item)

    canonical.sort(
        key=lambda s: (
            str(s.get("lane") or ""),
            str(s.get("content") or ""),
            str(s.get("why_keep") or ""),
            str(s.get("worth_reason") or ""),
        )
    )
    return canonical


def parse_spark_extraction_response(text: str) -> tuple[list[object] | None, list[str]]:
    """Parse a top-level JSON array from model output. Reject prose wrappers."""
    errors: list[str] = []
    stripped = text.strip()
    if not stripped:
        return None, ["response is empty"]

    candidate = stripped
    if not candidate.startswith("["):
        if candidate.startswith("```"):
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
            else:
                return None, ["response was not a JSON array"]
        else:
            return None, ["response was not a JSON array"]

    if not candidate.startswith("["):
        return None, ["response was not a JSON array"]

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON: {exc}"]

    if not isinstance(data, list):
        return None, ["response must be a JSON array"]
    return data, errors


def _load_test_fixture() -> list[object]:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("spark extraction fixture must be a JSON array")
    return payload


def _lanes_for_prompt() -> str:
    return ", ".join(sorted(sparks.SPARK_LANES))


def _build_attempt_1_messages(source_text: str) -> list[dict[str, str]]:
    system = (
        "You extract durable cognitive sparks from source text. "
        "Return ONLY a JSON array. No markdown, no commentary, no wrapper object. "
        f"Each item must include: content (max {sparks.SPARK_CONTENT_MAX_LEN} chars), "
        "lane, why_keep, worth_reason, confidence (0-1). "
        "Optional: spark_type (fact|decision|intent|observation), "
        "certainty (tentative|exploratory|confirmed), secondary_lanes (lane array). "
        f"Allowed lanes: {_lanes_for_prompt()}. "
        f"Return at most {MAX_SPARKS_PER_EXTRACTION} items."
    )
    user = f"Extract sparks from this source text:\n\n{source_text}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _format_retry_errors(
    parse_errors: list[str],
    validation_errors: list[str],
) -> str:
    sections: list[str] = []
    if parse_errors:
        sections.append(
            "Parse errors:\n" + "\n".join(f"- {err}" for err in parse_errors)
        )
    if validation_errors:
        sections.append(
            "Validation errors:\n" + "\n".join(f"- {err}" for err in validation_errors)
        )
    text = "\n\n".join(sections) if sections else "Previous response was invalid."
    if len(text) > MAX_RETRY_ERROR_CHARS:
        return text[: MAX_RETRY_ERROR_CHARS - 3] + "..."
    return text


def _build_attempt_2_messages(
    parse_errors: list[str],
    validation_errors: list[str],
) -> list[dict[str, str]]:
    error_block = _format_retry_errors(parse_errors, validation_errors)
    system = (
        "You previously failed to follow spark extraction instructions. "
        "Return ONLY a valid JSON array with no surrounding text. "
        f"Each item must include content, lane, why_keep, worth_reason, confidence. "
        "Optional: spark_type, certainty, secondary_lanes. "
        f"Allowed lanes: {_lanes_for_prompt()}. "
        f"Return at most {MAX_SPARKS_PER_EXTRACTION} items."
    )
    user = (
        f"{error_block}\n\n"
        "Regenerate the sparks correctly. Return ONLY a JSON array."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _validate_batch(
    parsed: list[object],
) -> tuple[list[dict[str, object]] | None, list[str], list[str]]:
    parse_errors: list[str] = []
    validation_errors: list[str] = []

    if len(parsed) > MAX_SPARKS_PER_EXTRACTION:
        validation_errors.append(
            f"too many sparks: {len(parsed)} > {MAX_SPARKS_PER_EXTRACTION}"
        )
        return None, parse_errors, validation_errors

    validated: list[dict[str, object]] = []
    for index, raw_item in enumerate(parsed):
        if not isinstance(raw_item, dict):
            parse_errors.append(f"sparks[{index}] must be an object")
            continue
        result = sparks.validate_spark(raw_item)
        if not result.ok:
            for err in result.errors:
                validation_errors.append(f"sparks[{index}]: {err}")
            continue
        assert result.spark is not None
        validated.append(result.spark)

    if parse_errors or validation_errors:
        return None, parse_errors, validation_errors

    total_chars = sum(len(str(item["content"])) for item in validated)
    if validated and total_chars < MIN_TOTAL_CONTENT_LENGTH:
        validation_errors.append(
            f"batch content too short: {total_chars} < {MIN_TOTAL_CONTENT_LENGTH}"
        )
        return None, parse_errors, validation_errors

    return validated, parse_errors, validation_errors


def _finalize_errors(
    parse_errors: list[str],
    validation_errors: list[str],
) -> list[str]:
    errors: list[str] = []
    if parse_errors:
        errors.append("parse failed")
        errors.extend(f"parse: {err}" for err in parse_errors)
    if validation_errors:
        errors.append("validation failed")
        errors.extend(f"validation: {err}" for err in validation_errors)
    return errors or ["spark extraction failed"]


def _process_parsed_batch(
    parsed: list[object],
) -> tuple[list[dict[str, object]] | None, list[str], list[str]]:
    if len(parsed) == 0:
        return [], [], []
    return _validate_batch(parsed)


def _success_result(
    sparks_batch: list[dict[str, object]],
    *,
    attempts: int,
    cache_key: str | None = None,
    cache_hit: bool = False,
) -> SparkExtractionResult:
    canonical = canonicalize_spark_batch(sparks_batch)
    if cache_key is not None and not cache_hit:
        _extraction_cache[cache_key] = [dict(item) for item in canonical]
    return SparkExtractionResult(
        ok=True,
        sparks=canonical,
        errors=[],
        attempts=attempts,
        cache_hit=cache_hit,
    )


def extract_sparks_from_text(source_text: str) -> SparkExtractionResult:
    """Extract validated spark candidates from raw text via OpenAI (T4/T5)."""
    if crowley.is_test_mode():
        try:
            parsed = _load_test_fixture()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return SparkExtractionResult(
                ok=False,
                sparks=[],
                errors=[f"fixture load failed: {exc}"],
                attempts=0,
            )
        validated, parse_errors, validation_errors = _process_parsed_batch(parsed)
        if validated is not None:
            return _success_result(validated, attempts=1)
        return SparkExtractionResult(
            ok=False,
            sparks=[],
            errors=_finalize_errors(parse_errors, validation_errors),
            attempts=1,
        )

    if not crowley._has_openai_key():
        return SparkExtractionResult(
            ok=False,
            sparks=[],
            errors=["OPENAI_API_KEY not set"],
            attempts=0,
        )

    cache_key = receipt_fingerprint(source_text)
    cached = _extraction_cache.get(cache_key)
    if cached is not None:
        return SparkExtractionResult(
            ok=True,
            sparks=[dict(item) for item in cached],
            errors=[],
            attempts=0,
            cache_hit=True,
        )

    parse_errors: list[str] = []
    validation_errors: list[str] = []

    for attempt in (1, 2):
        if attempt == 1:
            messages = _build_attempt_1_messages(source_text)
        else:
            messages = _build_attempt_2_messages(parse_errors, validation_errors)

        raw = crowley._call_openai(messages, stream=False, temperature=0.0)
        parsed, parse_errors = parse_spark_extraction_response(raw)
        if parsed is None:
            validation_errors = []
            if attempt == 2:
                return SparkExtractionResult(
                    ok=False,
                    sparks=[],
                    errors=_finalize_errors(parse_errors, validation_errors),
                    attempts=attempt,
                )
            continue

        if len(parsed) == 0:
            return _success_result([], attempts=attempt, cache_key=cache_key)

        validated, batch_parse_errors, batch_validation_errors = _validate_batch(parsed)
        parse_errors = batch_parse_errors
        validation_errors = batch_validation_errors
        if validated is not None:
            return _success_result(
                validated,
                attempts=attempt,
                cache_key=cache_key,
            )
        if attempt == 2:
            return SparkExtractionResult(
                ok=False,
                sparks=[],
                errors=_finalize_errors(parse_errors, validation_errors),
                attempts=attempt,
            )

    return SparkExtractionResult(
        ok=False,
        sparks=[],
        errors=_finalize_errors(parse_errors, validation_errors),
        attempts=2,
    )
