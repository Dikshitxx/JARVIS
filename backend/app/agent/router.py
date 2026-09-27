"""
Fast deterministic intent router.
Matches simple, unambiguous commands to a tool call WITHOUT calling the LLM.
Falls through to the normal agent loop (LLM + tools) for anything not matched here.
Only add patterns here for commands that are genuinely unambiguous — if a
phrasing could mean several things, let the LLM handle it instead.
"""

import re
import logging

from app.tools.registry import run_tool, NeedsConfirmation
from app.tools.browser_targets import resolve_target
from app.core import config

log = logging.getLogger("jarvis.router")

# Each pattern: (compiled regex, function(match) -> (tool_name, args))
_PATTERNS = [
    (re.compile(r"^open\s+(.+)$", re.I), lambda m: _open_target_or_app(m.group(1))),
    (re.compile(r"^(?:play|put on)\s+(.+?)\s+(?:on\s+)?youtube$", re.I),
     lambda m: ("play_youtube_song", {"query": m.group(1)})),
    (re.compile(r"^(?:pause|stop|resume)\s+(?:the\s+)?(?:song|video|music)$", re.I),
     lambda m: ("toggle_youtube_playback", {})),
    (re.compile(r"^search\s+(?:the\s+web\s+for|google\s+for|for)\s+(.+)$", re.I),
     lambda m: ("search_web", {"query": m.group(1)})),
    (re.compile(r"^take\s+a?\s*screenshot$", re.I), lambda m: ("take_screenshot", {})),
    (re.compile(r"^what\s+time\s+is\s+it\??$", re.I), lambda m: ("get_time", {})),
    (re.compile(r"^close\s+(\w+)$", re.I), lambda m: ("close_app", {"name": m.group(1)})),
]


def _open_target_or_app(value: str) -> tuple[str, dict]:
    if resolve_target(value) is not None:
        return "browser_open", {"target": value}
    if value.strip().lower() in config.ALLOWED_APPS:
        return "open_app", {"name": value}
    return "browser_open", {"target": value}


def try_fast_route(user_text: str) -> tuple[str, str, dict] | None:
    """
    Returns (tool_name, result_or_confirm_message, args) if a deterministic
    match ran, else None (meaning: fall through to the normal LLM agent loop).
    """
    text = user_text.strip()
    for pattern, extract in _PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        tool_name, args = extract(match)
        log.info("FAST ROUTE matched %r -> %s %s", text, tool_name, args)
        try:
            result = run_tool(tool_name, args)
            return tool_name, result, args
        except NeedsConfirmation as need:
            return tool_name, f"Confirm: {need.tool_name} {need.tool_args}? Reply 'yes' or 'no'.", args
    return None