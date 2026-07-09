"""Model provider, brain routing, and runtime diagnostics helpers."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import ollama

import crowley_core

MODEL_PROVIDER = "auto"
MODEL_PROVIDER_OPTIONS = frozenset({"auto", "openai", "ollama", "anthropic"})
OPENAI_MODEL = "gpt-4.1-mini"
OLLAMA_MODEL = "llama3.1:8b"
ANTHROPIC_MODEL_OPTIONS = (
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-latest",
    "claude-3-5-haiku-latest",
)
TEST_MODE_STUB_REPLY = "[Crowley test mode]"

_brain_setting_lock = threading.Lock()
_brain_setting_loaded = False
_brain_config_cache: dict[str, str | None] | None = None
_brain_settings_path_override: Path | None = None


def _has_openai_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def _has_anthropic_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _default_anthropic_model() -> str:
    raw = os.environ.get("ANTHROPIC_MODEL", "").strip()
    if raw:
        return raw
    return ANTHROPIC_MODEL_OPTIONS[0]


def get_brain_settings_path() -> Path:
    """Path to persisted runtime brain preference (provider routing)."""
    if _brain_settings_path_override is not None:
        return _brain_settings_path_override
    return crowley_core.PROJECT_ROOT / ".crowley" / "brain.json"


def set_brain_settings_path(path: Path | str | None) -> Path | None:
    """Point brain settings at a specific file (tests) or back to default."""
    global _brain_settings_path_override, _brain_setting_loaded, _brain_config_cache
    _brain_settings_path_override = Path(path) if path is not None else None
    _brain_setting_loaded = False
    _brain_config_cache = None
    return _brain_settings_path_override


def _normalize_brain_config(raw: dict[str, object] | None) -> dict[str, str | None]:
    provider = MODEL_PROVIDER
    model: str | None = None
    if isinstance(raw, dict):
        candidate = str(raw.get("provider", "")).strip().lower()
        if candidate in MODEL_PROVIDER_OPTIONS:
            provider = candidate
        raw_model = raw.get("model")
        if raw_model is not None:
            cleaned = str(raw_model).strip()
            model = cleaned or None
    if provider == "auto":
        model = None
    return {"provider": provider, "model": model}


def _load_brain_config_from_disk() -> dict[str, str | None] | None:
    path = get_brain_settings_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return _normalize_brain_config(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def get_brain_config() -> dict[str, str | None]:
    """Active brain routing config: provider + optional model override."""
    global _brain_setting_loaded, _brain_config_cache
    with _brain_setting_lock:
        if not _brain_setting_loaded:
            _brain_config_cache = _load_brain_config_from_disk()
            _brain_setting_loaded = True
        if _brain_config_cache is not None:
            return dict(_brain_config_cache)
        return {"provider": MODEL_PROVIDER, "model": None}


def get_model_provider_setting() -> str:
    """Configured provider mode (persisted when switched in UI)."""
    return str(get_brain_config()["provider"])


def set_brain_config(provider: str, model: str | None = None) -> dict[str, str | None]:
    """Persist runtime brain preference and apply immediately."""
    global _brain_setting_loaded, _brain_config_cache
    normalized = provider.strip().lower()
    if normalized not in MODEL_PROVIDER_OPTIONS:
        allowed = ", ".join(sorted(MODEL_PROVIDER_OPTIONS))
        raise ValueError(f"provider must be one of: {allowed}")
    config = _normalize_brain_config({"provider": normalized, "model": model})
    with _brain_setting_lock:
        path = get_brain_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        _brain_config_cache = dict(config)
        _brain_setting_loaded = True
    return dict(config)


def set_model_provider_setting(provider: str) -> str:
    """Persist provider only (legacy API)."""
    return set_brain_config(provider)["provider"] or MODEL_PROVIDER


def reset_model_provider_setting() -> None:
    """Clear in-memory and on-disk brain preference (tests)."""
    global _brain_setting_loaded, _brain_config_cache
    with _brain_setting_lock:
        _brain_config_cache = None
        _brain_setting_loaded = False
        path = get_brain_settings_path()
        if path.is_file():
            path.unlink()


def list_ollama_models(timeout: float = 3.0) -> list[str]:
    """Return installed Ollama model names from the local daemon."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=timeout
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return []
    names: list[str] = []
    for entry in payload.get("models", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if name:
            names.append(name)
    return sorted(set(names))


def _probe_ollama_reachable(timeout: float = 2.0) -> bool:
    """Lightweight Ollama reachability check (no model load)."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=timeout
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _available_providers(
    *,
    has_openai_key: Callable[[], bool] = _has_openai_key,
    has_anthropic_key: Callable[[], bool] = _has_anthropic_key,
    probe_ollama_reachable: Callable[[], bool] = _probe_ollama_reachable,
) -> list[str]:
    available: list[str] = []
    if has_openai_key():
        available.append("openai")
    if has_anthropic_key():
        available.append("anthropic")
    if probe_ollama_reachable():
        available.append("ollama")
    return available


def get_model_provider(
    *,
    get_provider_setting: Callable[[], str] = get_model_provider_setting,
    available_providers: Callable[[], list[str]] | None = None,
) -> str:
    """Return resolved provider for inference."""
    setting = get_provider_setting()
    if setting != "auto":
        return setting
    available = available_providers() if available_providers else _available_providers()
    return available[0] if available else "ollama"


def get_active_model_name(
    *,
    get_brain_config_func: Callable[[], dict[str, str | None]] = get_brain_config,
    get_model_provider_func: Callable[[], str] = get_model_provider,
    list_ollama_models_func: Callable[[], list[str]] = list_ollama_models,
) -> str:
    """Return the model id used for the current brain selection."""
    config = get_brain_config_func()
    provider = config["provider"]
    model_override = config.get("model")
    if provider == "auto":
        provider = get_model_provider_func()
        model_override = None
    if model_override:
        return str(model_override)
    if provider == "openai":
        return OPENAI_MODEL
    if provider == "anthropic":
        return _default_anthropic_model()
    if provider == "ollama":
        models = list_ollama_models_func()
        if OLLAMA_MODEL in models:
            return OLLAMA_MODEL
        return models[0] if models else OLLAMA_MODEL
    return OPENAI_MODEL


def probe_model_availability(
    *,
    is_test_mode: Callable[[], bool] = crowley_core.is_test_mode,
    has_openai_key: Callable[[], bool] = _has_openai_key,
    has_anthropic_key: Callable[[], bool] = _has_anthropic_key,
    probe_ollama_reachable: Callable[[], bool] = _probe_ollama_reachable,
    get_provider_setting: Callable[[], str] = get_model_provider_setting,
    get_model_provider_func: Callable[[], str] = get_model_provider,
) -> dict[str, object]:
    """
    Structured model availability for health/runtime diagnostics.
    Separate from provider routing: reports reachability truth.
    """
    if is_test_mode():
        return {
            "status": "available",
            "provider": "test",
            "detail": "CROWLEY_TEST_MODE stub",
        }

    openai_ok = has_openai_key()
    ollama_ok = probe_ollama_reachable()
    anthropic_ok = has_anthropic_key()

    setting = get_provider_setting()
    if setting == "openai":
        return {
            "status": "available" if openai_ok else "unavailable",
            "provider": "openai",
            "detail": "OPENAI_API_KEY set"
            if openai_ok
            else "OPENAI_API_KEY not set",
        }
    if setting == "anthropic":
        return {
            "status": "available" if anthropic_ok else "unavailable",
            "provider": "anthropic",
            "detail": "ANTHROPIC_API_KEY set"
            if anthropic_ok
            else "ANTHROPIC_API_KEY not set",
        }
    if setting == "ollama":
        return {
            "status": "available" if ollama_ok else "unavailable",
            "provider": "ollama",
            "detail": "Ollama reachable"
            if ollama_ok
            else "Ollama not reachable at 127.0.0.1:11434",
        }

    if openai_ok:
        return {
            "status": "available",
            "provider": "openai",
            "detail": "OPENAI_API_KEY set",
        }
    if anthropic_ok:
        return {
            "status": "available",
            "provider": "anthropic",
            "detail": "ANTHROPIC_API_KEY set",
        }
    if ollama_ok:
        return {
            "status": "available",
            "provider": "ollama",
            "detail": "Ollama reachable (OpenAI unavailable)",
        }
    return {
        "status": "unavailable",
        "provider": get_model_provider_func(),
        "detail": "No model provider reachable",
    }


def _runtime_retrieval_label(mode: str) -> str:
    lower = mode.lower()
    if "vector" in lower and "keyword" in lower:
        return "vector"
    if "keyword" in lower:
        return "keyword"
    return mode


def build_runtime_diagnostics(
    *,
    memory_embed_provider: Callable[[], str],
    connect_db: Callable[[], Any],
    try_load_sqlite_vec: Callable[[Any], bool],
    get_sqlite_vec_failure_reason: Callable[[], str | None],
    get_last_retrieval_mode: Callable[[], str],
    probe_model_availability_func: Callable[[], dict[str, object]],
    is_test_mode: Callable[[], bool] = crowley_core.is_test_mode,
) -> dict[str, object]:
    """Operator-facing runtime block for /api/health."""
    embed = memory_embed_provider()
    conn = connect_db()
    try:
        vec_ready = try_load_sqlite_vec(conn)
    finally:
        conn.close()
    model_probe = probe_model_availability_func()
    vec_detail = get_sqlite_vec_failure_reason()
    if vec_ready:
        vector_store = "available"
        vector_detail: str | None = None
    elif embed == "off":
        vector_store = "unavailable"
        vector_detail = vec_detail
    else:
        vector_store = "fallback"
        vector_detail = "sqlite-vec unavailable; using Python cosine fallback"
        if vec_detail:
            vector_detail = f"{vector_detail} ({vec_detail})"

    runtime: dict[str, object] = {
        "embeddings": embed,
        "vector_store": vector_store,
        "retrieval": _runtime_retrieval_label(get_last_retrieval_mode()),
        "model": str(model_probe.get("status", "unknown")),
        "test_mode": is_test_mode(),
    }
    if vector_detail:
        runtime["vector_store_detail"] = vector_detail
    if model_probe.get("detail"):
        runtime["model_detail"] = model_probe["detail"]
    return runtime


def _brain_provider_label(
    provider: str,
    *,
    get_model_provider_func: Callable[[], str] = get_model_provider,
) -> str:
    if provider == "auto":
        resolved = get_model_provider_func()
        if resolved == "openai":
            return "Auto · OpenAI"
        if resolved == "anthropic":
            return "Auto · Claude"
        return "Auto · Ollama"
    if provider == "openai":
        return "OpenAI"
    if provider == "anthropic":
        return "Claude"
    return "Ollama"


def _brain_banner_label(
    *,
    get_brain_config_func: Callable[[], dict[str, str | None]] = get_brain_config,
    get_model_provider_func: Callable[[], str] = get_model_provider,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
    brain_provider_label_func: Callable[[str], str] | None = None,
) -> str:
    config = get_brain_config_func()
    provider = config["provider"]
    model = get_active_model_name_func()
    if provider == "auto":
        resolved = get_model_provider_func()
        resolved_name = {
            "openai": "OpenAI",
            "anthropic": "Claude",
            "ollama": "Ollama",
        }.get(resolved, resolved)
        return f"Auto ({resolved_name}) / {model}"
    label_func = brain_provider_label_func or _brain_provider_label
    return f"{label_func(provider)} / {model}"


def _brain_provider_models(
    provider: str,
    *,
    list_ollama_models_func: Callable[[], list[str]] = list_ollama_models,
) -> list[str]:
    if provider == "openai":
        return [OPENAI_MODEL]
    if provider == "anthropic":
        return list(ANTHROPIC_MODEL_OPTIONS)
    if provider == "ollama":
        return list_ollama_models_func()
    return []


def _brain_provider_available(
    provider: str,
    *,
    available_providers: Callable[[], list[str]] | None = None,
    has_openai_key: Callable[[], bool] = _has_openai_key,
    has_anthropic_key: Callable[[], bool] = _has_anthropic_key,
    probe_ollama_reachable: Callable[[], bool] = _probe_ollama_reachable,
) -> bool:
    if provider == "auto":
        if available_providers is not None:
            return bool(available_providers())
        return bool(
            _available_providers(
                has_openai_key=has_openai_key,
                has_anthropic_key=has_anthropic_key,
                probe_ollama_reachable=probe_ollama_reachable,
            )
        )
    if provider == "openai":
        return has_openai_key()
    if provider == "anthropic":
        return has_anthropic_key()
    return probe_ollama_reachable()


def get_brain_snapshot(
    *,
    is_test_mode: Callable[[], bool] = crowley_core.is_test_mode,
    get_brain_config_func: Callable[[], dict[str, str | None]] = get_brain_config,
    get_model_provider_func: Callable[[], str] = get_model_provider,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
    brain_provider_label_func: Callable[[str], str] | None = None,
    brain_banner_label_func: Callable[[], str] | None = None,
    brain_provider_models_func: Callable[[str], list[str]] | None = None,
    brain_provider_available_func: Callable[[str], bool] | None = None,
) -> dict[str, object]:
    """Runtime brain routing for UI switcher and health."""
    config = get_brain_config_func()
    provider = str(config["provider"])
    resolved = get_model_provider_func()
    active_model = get_active_model_name_func()
    label_func = brain_provider_label_func or _brain_provider_label
    banner_func = brain_banner_label_func or _brain_banner_label
    models_func = brain_provider_models_func or _brain_provider_models
    available_func = brain_provider_available_func or _brain_provider_available

    if is_test_mode():
        test_models = ["test-stub"]
        providers = [
            {
                "id": "auto",
                "label": "Auto",
                "hint": "Best available",
                "available": True,
                "active": provider == "auto",
                "models": [],
            },
            {
                "id": "openai",
                "label": "OpenAI",
                "hint": OPENAI_MODEL,
                "available": True,
                "active": provider == "openai",
                "models": [
                    {
                        "id": OPENAI_MODEL,
                        "label": OPENAI_MODEL,
                        "active": provider == "openai",
                    }
                ],
            },
            {
                "id": "anthropic",
                "label": "Claude",
                "hint": "ANTHROPIC_API_KEY",
                "available": True,
                "active": provider == "anthropic",
                "models": [
                    {
                        "id": "test-claude",
                        "label": "test-claude",
                        "active": provider == "anthropic",
                    }
                ],
            },
            {
                "id": "ollama",
                "label": "Ollama",
                "hint": "Local models",
                "available": True,
                "active": provider == "ollama",
                "models": [
                    {"id": model, "label": model, "active": provider == "ollama"}
                    for model in test_models
                ],
            },
        ]
        return {
            "provider": provider,
            "model": active_model,
            "resolved": "test",
            "label": label_func(provider),
            "banner": banner_func(),
            "providers": providers,
        }

    providers: list[dict[str, object]] = [
        {
            "id": "auto",
            "label": "Auto",
            "hint": "OpenAI → Claude → Ollama",
            "available": available_func("auto"),
            "active": provider == "auto",
            "models": [],
        }
    ]

    for pid, label, hint in (
        ("openai", "OpenAI", OPENAI_MODEL),
        ("anthropic", "Claude", "ANTHROPIC_API_KEY in .env"),
        ("ollama", "Ollama", "Local uncensored models"),
    ):
        model_ids = models_func(pid)
        if pid == "ollama" and provider == "ollama" and active_model not in model_ids:
            model_ids = [active_model, *model_ids]
        providers.append(
            {
                "id": pid,
                "label": label,
                "hint": hint,
                "available": available_func(pid),
                "active": provider == pid,
                "models": [
                    {
                        "id": model_id,
                        "label": model_id,
                        "active": provider == pid and active_model == model_id,
                    }
                    for model_id in model_ids
                ],
            }
        )

    return {
        "provider": provider,
        "model": active_model,
        "resolved": resolved,
        "label": label_func(provider),
        "banner": banner_func(),
        "providers": providers,
    }


def _print_stream_token(token: str, started: bool) -> bool:
    if not started:
        print(f"\rCrowley: {token}", end="", flush=True)
    else:
        print(token, end="", flush=True)
    return True


def _ollama_chunk_text(chunk: object) -> str:
    """Extract streamable text from an Ollama chat chunk (content or thinking)."""
    message = chunk.get("message") if isinstance(chunk, dict) else getattr(chunk, "message", None)
    if message is None:
        return ""
    if isinstance(message, dict):
        content = str(message.get("content") or "")
        thinking = str(message.get("thinking") or "")
    else:
        content = str(getattr(message, "content", None) or "")
        thinking = str(getattr(message, "thinking", None) or "")
    return content or thinking


def _iter_ollama_tokens(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    think: bool = False,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
) -> Iterator[str]:
    model_name = model or get_active_model_name_func()
    stream = ollama.chat(
        model=model_name,
        messages=messages,
        stream=True,
        think=think,
    )
    for chunk in stream:
        token = _ollama_chunk_text(chunk)
        if token:
            yield token


def _iter_openai_tokens(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
) -> Iterator[str]:
    from openai import OpenAI

    model_name = model or get_active_model_name_func()
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=True,
    )
    for chunk in response:
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token


def _anthropic_payload(
    messages: list[dict[str, str]], model: str, *, stream: bool
) -> dict[str, object]:
    system_parts: list[str] = []
    api_messages: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            api_messages.append({"role": role, "content": content})
    body: dict[str, object] = {
        "model": model,
        "max_tokens": 4096,
        "messages": api_messages,
        "stream": stream,
    }
    if system_parts:
        body["system"] = "\n\n".join(system_parts).strip()
    return body


def _iter_anthropic_tokens(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
) -> Iterator[str]:
    import urllib.error
    import urllib.request

    model_name = model or get_active_model_name_func()
    body = _anthropic_payload(messages, model_name, stream=True)
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            payload_raw = line[5:].strip()
            if not payload_raw or payload_raw == "[DONE]":
                continue
            payload = json.loads(payload_raw)
            if payload.get("type") != "content_block_delta":
                continue
            token = payload.get("delta", {}).get("text", "")
            if token:
                yield token


def _call_ollama(
    messages: list[dict[str, str]],
    stream: bool,
    *,
    model: str | None = None,
    think: bool = False,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
    iter_ollama_tokens: Callable[..., Iterator[str]] = _iter_ollama_tokens,
) -> str:
    model_name = model or get_active_model_name_func()
    if stream:
        return "".join(
            iter_ollama_tokens(messages, model=model_name, think=think)
        ).strip()
    response = ollama.chat(model=model_name, messages=messages, think=think)
    message = response.get("message") if isinstance(response, dict) else response.message
    if isinstance(message, dict):
        text = str(message.get("content") or message.get("thinking") or "")
    else:
        text = str(getattr(message, "content", None) or getattr(message, "thinking", None) or "")
    return text.strip()


def _call_openai(
    messages: list[dict[str, str]],
    stream: bool,
    *,
    model: str | None = None,
    temperature: float | None = None,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
    iter_openai_tokens: Callable[..., Iterator[str]] = _iter_openai_tokens,
) -> str:
    model_name = model or get_active_model_name_func()
    if stream:
        return "".join(iter_openai_tokens(messages, model=model_name)).strip()
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    kwargs: dict[str, object] = {"model": model_name, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    response = client.chat.completions.create(**kwargs)
    return (response.choices[0].message.content or "").strip()


def _call_anthropic(
    messages: list[dict[str, str]],
    stream: bool,
    *,
    model: str | None = None,
    get_active_model_name_func: Callable[[], str] = get_active_model_name,
    iter_anthropic_tokens: Callable[..., Iterator[str]] = _iter_anthropic_tokens,
) -> str:
    model_name = model or get_active_model_name_func()
    if stream:
        return "".join(iter_anthropic_tokens(messages, model=model_name)).strip()
    import urllib.request

    body = _anthropic_payload(messages, model_name, stream=False)
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    parts: list[str] = []
    for block in payload.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts).strip()


def _iter_provider_tokens(
    provider: str,
    messages: list[dict[str, str]],
    *,
    iter_openai_tokens: Callable[[list[dict[str, str]]], Iterator[str]] = _iter_openai_tokens,
    iter_anthropic_tokens: Callable[[list[dict[str, str]]], Iterator[str]] = _iter_anthropic_tokens,
    iter_ollama_tokens: Callable[[list[dict[str, str]]], Iterator[str]] = _iter_ollama_tokens,
) -> Iterator[str]:
    if provider == "openai":
        yield from iter_openai_tokens(messages)
        return
    if provider == "anthropic":
        yield from iter_anthropic_tokens(messages)
        return
    yield from iter_ollama_tokens(messages)


def _call_provider(
    provider: str,
    messages: list[dict[str, str]],
    stream: bool,
    *,
    call_openai: Callable[[list[dict[str, str]], bool], str] = _call_openai,
    call_anthropic: Callable[[list[dict[str, str]], bool], str] = _call_anthropic,
    call_ollama: Callable[[list[dict[str, str]], bool], str] = _call_ollama,
) -> str:
    if provider == "openai":
        return call_openai(messages, stream)
    if provider == "anthropic":
        return call_anthropic(messages, stream)
    return call_ollama(messages, stream)


def _auto_fallback_providers(primary: str) -> list[str]:
    order = ["openai", "anthropic", "ollama"]
    return [provider for provider in order if provider != primary]


def iter_model_tokens(
    messages: list[dict[str, str]],
    *,
    quiet: bool = True,
    is_test_mode: Callable[[], bool] = crowley_core.is_test_mode,
    get_model_provider_func: Callable[[], str] = get_model_provider,
    get_model_provider_setting_func: Callable[[], str] = get_model_provider_setting,
    has_openai_key: Callable[[], bool] = _has_openai_key,
    has_anthropic_key: Callable[[], bool] = _has_anthropic_key,
    iter_provider_tokens: Callable[[str, list[dict[str, str]]], Iterator[str]] = _iter_provider_tokens,
    available_providers: Callable[[], list[str]] | None = None,
    auto_fallback_providers: Callable[[str], list[str]] = _auto_fallback_providers,
) -> Iterator[str]:
    """
    Yield completion tokens from the resolved provider.
    In auto mode, falls through OpenAI -> Claude -> Ollama on failure.
    """
    if is_test_mode():
        yield TEST_MODE_STUB_REPLY
        return

    provider = get_model_provider_func()
    allow_fallback = get_model_provider_setting_func() == "auto"

    def _err(msg: str) -> None:
        if not quiet:
            print(msg, flush=True)

    if provider == "openai" and not has_openai_key():
        _err("\rCrowley: OpenAI selected but OPENAI_API_KEY is not set.")
        if not allow_fallback:
            return
    elif provider == "anthropic" and not has_anthropic_key():
        _err("\rCrowley: Claude selected but ANTHROPIC_API_KEY is not set.")
        if not allow_fallback:
            return
    else:
        try:
            yield from iter_provider_tokens(provider, messages)
            return
        except Exception as exc:
            if not allow_fallback:
                _err(f"\rCrowley: model error — {exc}")
                return
            _err(f"\rCrowley: {provider} failed ({exc}), trying fallback...")

    if not allow_fallback:
        return

    available = available_providers or _available_providers
    for fallback in auto_fallback_providers(provider):
        if fallback not in available():
            continue
        try:
            yield from iter_provider_tokens(fallback, messages)
            return
        except Exception as exc:
            _err(f"\rCrowley: {fallback} failed ({exc})")
    _err("\rCrowley: no model provider available")


def call_model(
    messages: list[dict[str, str]],
    stream: bool = True,
    quiet: bool = False,
    on_token: Callable[[str], None] | None = None,
    *,
    is_test_mode: Callable[[], bool] = crowley_core.is_test_mode,
    get_model_provider_func: Callable[[], str] = get_model_provider,
    get_model_provider_setting_func: Callable[[], str] = get_model_provider_setting,
    has_openai_key: Callable[[], bool] = _has_openai_key,
    has_anthropic_key: Callable[[], bool] = _has_anthropic_key,
    call_provider: Callable[[str, list[dict[str, str]], bool], str] = _call_provider,
    iter_model_tokens_func: Callable[..., Iterator[str]] = iter_model_tokens,
    available_providers: Callable[[], list[str]] | None = None,
    auto_fallback_providers: Callable[[str], list[str]] = _auto_fallback_providers,
    print_stream_token: Callable[[str, bool], bool] = _print_stream_token,
) -> str | None:
    """
    Call the configured model provider.
    When stream=True, tokens go to on_token if set, else to the terminal.
    Returns the full reply, or None after an error (unless quiet=True).
    """
    if is_test_mode():
        reply = TEST_MODE_STUB_REPLY
        if stream:
            if on_token is not None:
                on_token(reply)
            elif not quiet:
                print(f"\r{reply}", flush=True)
            return reply
        return reply

    if not stream:
        provider = get_model_provider_func()
        allow_fallback = get_model_provider_setting_func() == "auto"

        def _err(msg: str) -> None:
            if not quiet:
                print(msg, flush=True)

        if provider == "openai" and not has_openai_key():
            _err("\rCrowley: OpenAI selected but OPENAI_API_KEY is not set.")
            if not allow_fallback:
                return None
        elif provider == "anthropic" and not has_anthropic_key():
            _err("\rCrowley: Claude selected but ANTHROPIC_API_KEY is not set.")
            if not allow_fallback:
                return None
        else:
            try:
                return call_provider(provider, messages, stream=False)
            except Exception as exc:
                if not allow_fallback:
                    _err(f"\rCrowley: model error — {exc}")
                    return None
                _err(f"\rCrowley: {provider} failed ({exc}), trying fallback...")

        if allow_fallback:
            available = available_providers or _available_providers
            for fallback in auto_fallback_providers(provider):
                if fallback not in available():
                    continue
                try:
                    return call_provider(fallback, messages, stream=False)
                except Exception as exc:
                    _err(f"\rCrowley: {fallback} failed ({exc})")
        return None

    parts: list[str] = []
    started = False
    for token in iter_model_tokens_func(messages, quiet=quiet):
        if on_token is not None:
            on_token(token)
        else:
            started = print_stream_token(token, started)
        parts.append(token)

    reply = "".join(parts).strip()
    if on_token is None:
        if not started:
            print("\rCrowley: (no response)", flush=True)
        elif parts:
            print(flush=True)
    return reply if reply else None
