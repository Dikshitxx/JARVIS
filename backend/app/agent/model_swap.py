"""Serialize and measure explicit Ollama model swaps for vision requests."""

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import time
from typing import Iterator

import ollama

from app.core import config
from app.llm.client import MODEL_LOCK

log = logging.getLogger("jarvis.agent.model_swap")
_swap_client = ollama.Client(host=config.OLLAMA_HOST)
VISION_KEEP_ALIVE = "5m"


def _log_swap(name: str, started: float, timestamp: str, status: str) -> None:
    duration_ms = (time.perf_counter() - started) * 1000
    log.info("Ollama model swap %s at=%s duration_ms=%.2f status=%s",
             name, timestamp, duration_ms, status)


def ensure_vision_model_loaded() -> None:
    """Unload the main model, then explicitly preload the vision model."""
    started = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    status = "failed"
    try:
        with MODEL_LOCK:
            _swap_client.generate(model=config.MODEL_NAME, prompt="", keep_alive=0)
            _swap_client.generate(model=config.VISION_MODEL, prompt="", keep_alive=VISION_KEEP_ALIVE)
        status = "success"
    finally:
        _log_swap("main_to_vision", started, timestamp, status)


def ensure_main_model_reloaded() -> None:
    """Unload the vision model, then explicitly preload the main model."""
    started = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    status = "failed"
    try:
        with MODEL_LOCK:
            unload_error = None
            try:
                _swap_client.generate(model=config.VISION_MODEL, prompt="", keep_alive=0)
            except Exception as exc:
                # This commonly happens when the vision model was not present
                # or failed to load. Always try to restore the main model.
                unload_error = exc
                log.warning("Could not explicitly unload vision model %s: %s", config.VISION_MODEL, exc)

            load_error = None
            for attempt in range(2):
                try:
                    _swap_client.generate(
                        model=config.MODEL_NAME,
                        prompt="",
                        keep_alive=config.OLLAMA_KEEP_ALIVE,
                    )
                    load_error = None
                    break
                except Exception as exc:
                    load_error = exc
                    if attempt == 0:
                        log.warning("Main model reload attempt failed; retrying: %s", exc)
            if load_error is not None:
                raise RuntimeError(f"Could not reload main model {config.MODEL_NAME}: {load_error}") from load_error
            status = "success" if unload_error is None else "main_reloaded_vision_unload_failed"
    finally:
        _log_swap("vision_to_main", started, timestamp, status)


@contextmanager
def vision_model_session() -> Iterator[None]:
    """Hold the shared model lock and always attempt to restore the main model."""
    with MODEL_LOCK:
        try:
            ensure_vision_model_loaded()
            yield
        finally:
            ensure_main_model_reloaded()
