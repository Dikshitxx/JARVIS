"""Async OpenAI-compatible chat providers with a local Ollama fallback."""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from contextvars import ContextVar
import inspect
import json
import logging
import mimetypes
from pathlib import Path
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.core import config

if TYPE_CHECKING:
    from app.agent.task_profile import TaskProfile

log = logging.getLogger("jarvis.llm.providers")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_TIMEOUT_SECONDS = 15
GROQ_TIMEOUT_SECONDS = 15
OLLAMA_TIMEOUT_SECONDS = 120
_CLIENTS: dict[tuple[str, str, int], AsyncOpenAI] = {}
_PRIVATE_REQUEST: ContextVar[bool] = ContextVar("jarvis_private_request", default=False)
_TASK_SELECTION: ContextVar["TaskSelection | None"] = ContextVar("jarvis_task_selection", default=None)
_BACKGROUND_LOOP: asyncio.AbstractEventLoop | None = None
_BACKGROUND_LOOP_LOCK = threading.Lock()
_PROVIDER_METRICS: dict[str, dict[str, float]] = {}
_PROVIDER_METRICS_LOCK = threading.Lock()

_PROVIDER_CAPABILITIES = {
    "Gemini": frozenset({
        "chat", "tool_calling", "remote", "reasoning", "long_context",
        "fresh_information_workflow",
    }),
    "Groq": frozenset({
        "chat", "tool_calling", "remote", "reasoning",
        "fresh_information_workflow",
    }),
    "Ollama": frozenset({"chat", "tool_calling", "local_execution"}),
}
_PROVIDER_ORDER = ("Gemini", "Groq", "Ollama")


@dataclass
class TaskSelection:
    profile: TaskProfile
    excluded_providers: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


@contextmanager
def task_profile_scope(profile: TaskProfile):
    selection = TaskSelection(profile)
    token = _TASK_SELECTION.set(selection)
    try:
        yield selection
    finally:
        _TASK_SELECTION.reset(token)


def current_task_profile() -> TaskProfile | None:
    selection = _TASK_SELECTION.get()
    return selection.profile if selection is not None else None


def refine_current_task_profile(selected_tools: set[str]) -> None:
    """Refine the active descriptive profile after tool selection."""
    selection = _TASK_SELECTION.get()
    if selection is None:
        return
    from app.agent.task_profile import refine_task_profile

    with selection.lock:
        selection.profile = refine_task_profile(selection.profile, selected_tools)


def exclude_provider(provider: str) -> bool:
    """Exclude an inadequate model from subsequent calls in the active task."""
    selection = _TASK_SELECTION.get()
    if selection is None or provider not in _PROVIDER_CAPABILITIES:
        return False
    with selection.lock:
        selection.excluded_providers.add(provider)
        excluded = set(selection.excluded_providers)
    return bool(_select_capable_providers(selection.profile, "smart", False, excluded))


def _configured_scores(setting_name: str) -> dict[str, float]:
    raw = getattr(config, setting_name, "{}")
    try:
        value = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        log.warning("Ignoring invalid %s provider score configuration", setting_name)
        return {}
    if not isinstance(value, dict):
        log.warning("Ignoring non-object %s provider score configuration", setting_name)
        return {}
    scores = {}
    for provider, score in value.items():
        if provider in _PROVIDER_CAPABILITIES and isinstance(score, (int, float)) and 0 <= score <= 1:
            scores[provider] = float(score)
        else:
            log.warning("Ignoring invalid %s score for provider %s", setting_name, provider)
    return scores


def _provider_score(
    provider: str,
    profile: TaskProfile,
    quality_scores: dict[str, float],
    cost_scores: dict[str, float],
) -> float:
    quality = quality_scores.get(provider, 0.5)
    cost = cost_scores.get(provider, 0.5)
    with _PROVIDER_METRICS_LOCK:
        metrics = dict(_PROVIDER_METRICS.get(provider, {}))
    samples = metrics.get("samples", 0.0)
    health = (metrics.get("successes", 0.0) / samples) if samples else 0.5
    latency = metrics.get("latency_ms")
    latency_score = 0.5 if latency is None else 1 / (1 + max(0.0, latency) / 1000)
    local_score = 1.0 if "local_execution" in _PROVIDER_CAPABILITIES[provider] else 0.0

    reasoning_weight = {"low": 0.2, "medium": 0.7, "high": 1.5}.get(
        getattr(profile, "reasoning_level", "low"), 0.5,
    )
    privacy_weight = 1.0 if getattr(profile, "privacy_level", "standard") == "private" else 0.0
    latency_weight = 0.25
    health_weight = 0.5
    cost_weight = 0.25
    return (
        quality * reasoning_weight
        + local_score * privacy_weight
        + latency_score * latency_weight
        + health * health_weight
        + (1 - cost) * cost_weight
    )


def _provider_healthy(provider: str) -> bool:
    with _PROVIDER_METRICS_LOCK:
        metrics = dict(_PROVIDER_METRICS.get(provider, {}))
    failures = metrics.get("consecutive_failures", 0.0)
    failed_at = metrics.get("failed_at", 0.0)
    return failures < 2 or time.monotonic() - failed_at >= 30


def _select_capable_providers(
    profile: TaskProfile, tier: str, private: bool, excluded: set[str],
) -> list[str]:
    required = set(getattr(profile, "required_capabilities", ()))
    if private or getattr(profile, "privacy_level", "standard") == "private":
        required.add("local_execution")
    if tier == "local":
        required.add("local_execution")
    if getattr(profile, "reasoning_level", "low") == "high":
        required.add("reasoning")
    settings = _provider_settings()
    candidates = [
        provider for provider in _PROVIDER_ORDER
        if provider not in excluded
        and (provider == "Ollama" or bool(settings[provider][1]))
        and _provider_healthy(provider)
        and required.issubset(_PROVIDER_CAPABILITIES[provider])
    ]
    quality_scores = _configured_scores("LLM_PROVIDER_QUALITY")
    cost_scores = _configured_scores("LLM_PROVIDER_COST")
    return sorted(
        candidates,
        key=lambda provider: (
            -_provider_score(provider, profile, quality_scores, cost_scores),
            _PROVIDER_ORDER.index(provider),
        ),
    )


def _record_provider_result(provider: str, elapsed_ms: float, success: bool) -> None:
    with _PROVIDER_METRICS_LOCK:
        metrics = _PROVIDER_METRICS.setdefault(provider, {
            "samples": 0.0, "successes": 0.0, "latency_ms": elapsed_ms,
            "consecutive_failures": 0.0, "failed_at": 0.0,
        })
        metrics["samples"] += 1
        metrics["successes"] += 1 if success else 0
        if success:
            metrics["consecutive_failures"] = 0.0
            previous = metrics.get("latency_ms", elapsed_ms)
            metrics["latency_ms"] = previous * 0.75 + elapsed_ms * 0.25
        else:
            metrics["consecutive_failures"] = metrics.get("consecutive_failures", 0.0) + 1
            metrics["failed_at"] = time.monotonic()


@contextmanager
def private_request_scope(private: bool):
    token = _PRIVATE_REQUEST.set(bool(private))
    try:
        yield
    finally:
        _PRIVATE_REQUEST.reset(token)


def is_private_request() -> bool:
    return _PRIVATE_REQUEST.get()


def _provider_settings() -> dict[str, tuple[str, str, str, float]]:
    return {
        "Gemini": (
            GEMINI_BASE_URL,
            getattr(config, "GEMINI_API_KEY", ""),
            getattr(config, "GEMINI_MODEL", "gemini-3.8-flash"),
            GEMINI_TIMEOUT_SECONDS,
        ),
        "Groq": (
            GROQ_BASE_URL,
            getattr(config, "GROQ_API_KEY", ""),
            getattr(config, "GROQ_MODEL", "llama-3.3-70b-versatile"),
            GROQ_TIMEOUT_SECONDS,
        ),
        "Ollama": (
            f"{getattr(config, 'OLLAMA_HOST', 'http://localhost:11434').rstrip('/')}/v1",
            "ollama",
            getattr(config, "OLLAMA_MODEL", getattr(config, "MODEL_NAME", "llama3.2:3b")),
            OLLAMA_TIMEOUT_SECONDS,
        ),
    }


def _client(provider: str) -> AsyncOpenAI:
    base_url, api_key, _model, timeout = _provider_settings()[provider]
    cache_key = (provider, api_key, id(asyncio.get_running_loop()))
    if cache_key not in _CLIENTS:
        _CLIENTS[cache_key] = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
        )
    return _CLIENTS[cache_key]


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    global _BACKGROUND_LOOP
    if _BACKGROUND_LOOP is not None and not _BACKGROUND_LOOP.is_closed():
        return _BACKGROUND_LOOP
    with _BACKGROUND_LOOP_LOCK:
        if _BACKGROUND_LOOP is not None and not _BACKGROUND_LOOP.is_closed():
            return _BACKGROUND_LOOP
        loop = asyncio.new_event_loop()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=run_loop, name="jarvis-llm-loop", daemon=True)
        thread.start()
        _BACKGROUND_LOOP = loop
        return loop


def _safe_error(error: Exception) -> str:
    message = str(error)
    for key in (getattr(config, "GEMINI_API_KEY", ""), getattr(config, "GROQ_API_KEY", "")):
        if key:
            message = message.replace(key, "[redacted]")
    return f"{type(error).__name__}: {message[:300]}"


def _flatten_tool_history(messages: list[dict]) -> list[dict]:
    flattened: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            flattened.append(message)
            continue
        item = dict(message)
        role = item.get("role")
        if role == "assistant" and item.get("tool_calls"):
            item.pop("tool_calls", None)
            if not item.get("content"):
                item["content"] = "[tool call executed]"
        if role == "tool":
            content = item.get("content")
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False, default=str)
            tool_name = item.get("name") or "tool"
            item["content"] = f"[{tool_name} result] {content}" if content else f"[{tool_name} result]"
            item.pop("tool_call_id", None)
            item.pop("name", None)
        flattened.append(item)
    return flattened


def _looks_like_tool_history_issue(error: Exception) -> bool:
    message = str(error).lower()
    return (
        "tool_calls" in message
        and (
            "tools" in message
            or "history" in message
            or "messages" in message
            or "not provided" in message
            or "not passed" in message
        )
    ) or ("tool calls" in message and "messages" in message)


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text", "")))
            else:
                parts.append(str(getattr(part, "text", "") or ""))
        return "".join(parts)
    return str(content or "")


def _normalize_response(response, provider: str, model: str = "") -> dict:
    choices = getattr(response, "choices", None) or []
    message = getattr(choices[0], "message", None) if choices else None
    tool_calls = []
    for call in getattr(message, "tool_calls", None) or []:
        function = getattr(call, "function", None)
        raw_arguments = getattr(function, "arguments", "{}")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except (json.JSONDecodeError, TypeError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        tool_calls.append({
            "id": str(getattr(call, "id", "") or ""),
            "name": str(getattr(function, "name", "") or ""),
            "arguments": arguments,
        })
    return {
        "provider": provider,
        "model": model,
        "text": _content_text(getattr(message, "content", "")),
        "tool_calls": tool_calls,
    }


def _image_messages(messages: list[dict], image_path: str) -> list[dict]:
    data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    mime_type = mimetypes.guess_type(image_path)[0] or "image/png"
    image_url = f"data:{mime_type};base64,{data}"
    prepared = [dict(message) for message in messages]
    user_index = next(
        (index for index in range(len(prepared) - 1, -1, -1) if prepared[index].get("role") == "user"),
        None,
    )
    if user_index is None:
        raise ValueError("Vision requests require a user message.")
    question = _content_text(prepared[user_index].get("content", ""))
    prepared[user_index]["content"] = [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    return prepared


def _local_vision(image_path: str, question: str) -> dict:
    from app.agent.model_swap import vision_model_session
    from app.llm.client import vision_chat

    with vision_model_session():
        answer = vision_chat(image_path, question)
    return {"provider": "Ollama", "model": config.VISION_MODEL, "text": answer, "tool_calls": []}


async def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    private: bool | None = None,
    vision: bool = False,
    image_path: str | None = None,
    tier: str = "smart",
    tool_choice=None,
    _selection: TaskSelection | None = None,
) -> dict:
    """Call Gemini, Groq, then Ollama and return normalized text/tool calls.

    Vision requests use Gemini when permitted, then the existing local
    moondream path. They intentionally do not pass images to Groq or the main
    local chat model.
    """
    if private is None:
        private = is_private_request()
    tier_name = str(tier or "smart").lower()
    if tier_name not in {"local", "smart"}:
        raise ValueError("tier must be 'local' or 'smart'")
    settings = _provider_settings()
    if vision:
        if not image_path:
            raise ValueError("Vision requests require an image path.")
        question = next(
            (_content_text(message.get("content", "")) for message in reversed(messages) if message.get("role") == "user"),
            "",
        )
        errors = []
        if not private and settings["Gemini"][1]:
            try:
                _base_url, _api_key, model, _timeout = settings["Gemini"]
                response = await _client("Gemini").chat.completions.create(
                    model=model,
                    messages=_image_messages(messages, image_path),
                )
                return _normalize_response(response, "Gemini", model)
            except Exception as exc:
                errors.append(f"Gemini: {_safe_error(exc)}")
                log.warning("LLM provider Gemini failed: %s", errors[-1])
        try:
            return await asyncio.to_thread(_local_vision, image_path, question)
        except Exception as exc:
            errors.append(f"Ollama vision: {_safe_error(exc)}")
            log.warning("LLM provider Ollama vision failed: %s", errors[-1])
        raise RuntimeError("All vision providers failed. " + "; ".join(errors))

    active_selection = _selection or _TASK_SELECTION.get()
    profile = active_selection.profile if active_selection is not None else None
    if profile is None:
        order = ("Ollama",) if private or tier_name == "local" else _PROVIDER_ORDER
    else:
        with active_selection.lock:
            excluded = set(active_selection.excluded_providers)
        order = tuple(_select_capable_providers(profile, tier_name, bool(private), excluded))
        if not order:
            raise RuntimeError("No configured LLM provider satisfies this task's required capabilities.")
    errors = []
    for provider in order:
        _base_url, api_key, model, _timeout = settings[provider]
        if provider != "Ollama" and not api_key:
            continue
        try:
            request_options = {"model": model, "messages": messages}
            if tools:
                request_options["tools"] = tools
            if provider != "Ollama" and tool_choice is not None:
                request_options["tool_choice"] = tool_choice
            if provider == "Ollama":
                request_options["extra_body"] = {
                    "options": {"num_ctx": config.NUM_CTX},
                    "keep_alive": config.OLLAMA_KEEP_ALIVE,
                }
            response = None
            start = time.perf_counter()
            for attempt in range(2):
                if attempt == 1 and (provider != "Ollama") and not request_options.get("tools") and "tool_calls" in json.dumps(messages, default=str):
                    request_options["messages"] = _flatten_tool_history(messages)
                try:
                    if provider == "Ollama":
                        from app.llm.client import MODEL_LOCK

                        with MODEL_LOCK:
                            response = await _client(provider).chat.completions.create(**request_options)
                    else:
                        response = await _client(provider).chat.completions.create(**request_options)
                    break
                except Exception as exc:
                    if attempt == 0 and (provider != "Ollama") and not request_options.get("tools") and _looks_like_tool_history_issue(exc):
                        request_options["messages"] = _flatten_tool_history(messages)
                        continue
                    raise
            if response is None:
                raise RuntimeError(f"No response received from {provider}")
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
            _record_provider_result(provider, elapsed_ms, True)
            normalized = _normalize_response(response, provider, model)
            usage = getattr(response, "usage", None)
            usage_summary = {}
            if usage is not None:
                usage_summary = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                }
            log.info("LLM_CALL provider=%s tier=%s latency_ms=%s tokens=%s", provider, tier_name, elapsed_ms, usage_summary or "n/a")
            return normalized
        except Exception as exc:
            _record_provider_result(provider, 0.0, False)
            errors.append(f"{provider}: {_safe_error(exc)}")
            log.warning("LLM provider %s failed: %s", provider, errors[-1])
    raise RuntimeError("All configured LLM providers failed. " + "; ".join(errors))


def chat_sync(
    messages: list[dict],
    tools: list[dict] | None = None,
    private: bool | None = None,
    vision: bool = False,
    image_path: str | None = None,
    tier: str = "smart",
    tool_choice=None,
) -> dict:
    """Bridge the async provider API for the current synchronous agent worker."""
    if private is None:
        private = is_private_request()
    selection = _TASK_SELECTION.get()
    loop = _ensure_background_loop()
    result = chat(
        messages,
        tools=tools,
        private=private,
        vision=vision,
        image_path=image_path,
        tier=tier,
        tool_choice=tool_choice,
        _selection=selection,
    )
    future = asyncio.run_coroutine_threadsafe(result, loop)
    try:
        return future.result(timeout=180)
    except TimeoutError:
        raise TimeoutError("LLM provider call timed out after 180s.")


async def provider_status() -> dict:
    """Return provider configuration and API reachability without exposing keys."""
    settings = _provider_settings()
    providers = []
    for provider in ("Gemini", "Groq", "Ollama"):
        _base_url, api_key, model, _timeout = settings[provider]
        configured = provider == "Ollama" or bool(api_key)
        reachable = None
        if configured:
            try:
                await _client(provider).models.list()
                reachable = True
            except Exception as exc:
                reachable = False
                log.warning("LLM provider %s status check failed: %s", provider, _safe_error(exc))
        providers.append({
            "name": provider,
            "model": model,
            "configured": configured,
            "reachable": reachable,
        })
    return {"providers": providers}
