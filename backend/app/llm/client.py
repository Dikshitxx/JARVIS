import time
import threading
import logging
from datetime import datetime, timezone

import ollama
from app.core import config

_client = ollama.Client(host=config.OLLAMA_HOST)
VISION_TIMEOUT_SECONDS = 60
_vision_client = ollama.Client(host=config.OLLAMA_HOST, timeout=VISION_TIMEOUT_SECONDS)
MODEL_LOCK = threading.RLock()
log = logging.getLogger("jarvis.llm")
_LLM_METRICS: list[dict] = []


def clear_llm_metrics() -> None:
    _LLM_METRICS.clear()


def get_llm_metrics() -> list[dict]:
    return [dict(item) for item in _LLM_METRICS]


def chat(messages: list, tools: list | None = None):
    """Returns the assistant message object (has .content and .tool_calls)."""
    started = time.perf_counter()
    with MODEL_LOCK:
        response = _client.chat(
            model=config.MODEL_NAME,
            messages=messages,
            tools=tools,
            options={"num_ctx": config.NUM_CTX},
            keep_alive=config.OLLAMA_KEEP_ALIVE,
        )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    _LLM_METRICS.append({
        "model": config.MODEL_NAME,
        "tool_count": len(tools or []),
        "message_count": len(messages),
        "latency_ms": latency_ms,
    })
    if len(_LLM_METRICS) > 200:
        del _LLM_METRICS[:-200]
    return response["message"]


def vision_chat(image_path: str, question: str) -> str:
    """Ask the configured Ollama vision model about a local image.

    The caller must load the vision model through app.agent.model_swap first.
    """
    started = time.perf_counter()
    try:
        with MODEL_LOCK:
            response = _vision_client.chat(
                model=config.VISION_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        "Inspect this screenshot and answer using only details you can see. "
                        "Start with the foreground window or app and its clearly readable text. "
                        "Do not invent other windows, objects, or text; say when a detail is unclear.\n\n"
                        f"Question: {question.strip()}"
                    ),
                    "images": [image_path],
                }],
                keep_alive="5m",
            )
        answer = str(response["message"]["content"] or "").strip()
        return answer or "Error: vision model returned an empty response."
    except Exception as exc:
        timed_out = isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()
        if timed_out:
            message = f"Error: vision request timed out after {VISION_TIMEOUT_SECONDS} seconds."
        else:
            message = f"Error: vision request failed: {exc}"
        log.warning("Vision inference failed at=%s duration_ms=%.2f: %s",
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    (time.perf_counter() - started) * 1000, message)
        return message
