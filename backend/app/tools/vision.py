"""On-demand visual questions about the current desktop screen."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import time

from app.agent.model_swap import vision_model_session
from app.llm.client import vision_chat
from app.tools.registry import Tool, register
from app.tools.screen import take_screenshot

log = logging.getLogger("jarvis.tools.vision")
DEFAULT_QUESTION = "Describe what is on this screen in a few sentences"
_SCREENSHOT_PREFIX = "Screenshot saved: "


def _screenshot_path(result: str) -> str:
    if not result.startswith(_SCREENSHOT_PREFIX):
        raise RuntimeError(result or "Screenshot capture did not return a file path.")
    path_and_size = result[len(_SCREENSHOT_PREFIX):]
    path = path_and_size.rsplit(" (", 1)[0]
    if not path or not Path(path).is_file():
        raise RuntimeError("Screenshot capture did not produce a readable image file.")
    return path


def look_at_screen(question: str = DEFAULT_QUESTION) -> str:
    """Capture the desktop and answer a visual question using Ollama."""
    started = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    log.info("LOOK_AT_SCREEN invoked at=%s question_chars=%d", timestamp, len(question))
    try:
        image_path = _screenshot_path(take_screenshot())
        with vision_model_session():
            answer = vision_chat(image_path, question)
        return answer
    except Exception as exc:
        log.exception("LOOK_AT_SCREEN failed at=%s", timestamp)
        return f"Error: vision request failed: {exc}"
    finally:
        log.info("LOOK_AT_SCREEN completed at=%s duration_ms=%.2f",
                 timestamp, (time.perf_counter() - started) * 1000)


register(Tool(
    name="look_at_screen",
    description=(
        "Inspect the current screen for visual judgment calls, such as describing an image, "
        "reading an error dialog, or checking whether a page looks broken. Use only when the "
        "user asks about something visible; do not use for text or state another tool can read."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "A focused question about what is visibly shown on the screen.",
            },
        },
        "required": [],
    },
    func=look_at_screen,
    risk="safe",
    capabilities=frozenset({"windows"}),
))
