"""
Fast deterministic intent router.
Matches simple, unambiguous commands to a tool call WITHOUT calling the LLM.
Falls through to the normal agent loop (LLM + tools) for anything not matched here.
Only add patterns here for commands that are genuinely unambiguous — if a
phrasing could mean several things, let the LLM handle it instead.
"""

import re
import logging

from app.tools.registry import run_tool_result, NeedsConfirmation, ToolResult
from app.tools.browser_targets import parse_browser_intent, resolve_target
from app.tools.apps import resolve_application_name
from app.agent.runtime_context import contextual_browser_intent
from app.agent.request import UserRequest, build_user_request

log = logging.getLogger("jarvis.router")

_OPEN_FAST_RE = re.compile(r"^open\s+(.+)$", re.I)
_PLAY_YOUTUBE_FAST_RE = re.compile(r"^play\s+([\w'-]+)\s+on\s+youtube$", re.I)
_TIME_FAST_RE = re.compile(r"^(?:what time is it|what(?:'s| is) the time|tell me the time|current time)$", re.I)


def is_fast_route_candidate(user_text: str) -> bool:
    """Only exact, short open and YouTube play phrases use the deterministic path."""
    text = re.sub(r"[.!?]+$", "", (user_text or "").strip())
    if _TIME_FAST_RE.fullmatch(text):
        return True
    words = text.split()
    if not 2 <= len(words) <= 4:
        return False
    opened = _OPEN_FAST_RE.fullmatch(text)
    if opened:
        target = opened.group(1).strip()
        return resolve_target(target) is not None or resolve_application_name(target) is not None
    return bool(_PLAY_YOUTUBE_FAST_RE.fullmatch(text))


def _open_target_or_app(value: str) -> tuple[str, dict]:
    target = resolve_target(value)
    if target is not None:
        return "browser_open", {"target": target.name}
    application = resolve_application_name(value)
    if application is not None:
        return "open_app", {"name": application}
    return "browser_open", {"target": ""}


def _run_browser_intent(intent: dict):
    tool_name = intent["intent"]
    args = {key: intent[key] for key in ("target", "query") if intent.get(key)}
    return tool_name, run_tool_result(tool_name, args), args


def _route_request(request: UserRequest) -> tuple[str, ToolResult, dict] | None:
    intent = request.intent
    target = request.target
    args: dict
    tool_name: str
    if intent == "open_target":
        return "browser_open", ToolResult(
            "clarification_required",
            f"I couldn't resolve '{next((entity.value for entity in request.entities if entity.kind == 'unresolved_target'), '')}' to an installed application or website. Please give me its full name or URL.",
        ), {}
    if intent == "open_application":
        tool_name, args = "open_app", {"name": target}
    elif intent == "open_website":
        tool_name, args = "browser_open", {"target": target}
        browser = next((modifier.split("=", 1)[1] for modifier in request.modifiers if modifier.startswith("browser=")), "")
        if browser:
            args["browser"] = browser
    elif intent == "search_web":
        tool_name, args = "search_web", {"query": request.query, "target": target or ""}
    elif intent in {"browser_search", "browser_interaction"}:
        tool_name = intent
        args = {"target": target, "query": request.query}
    elif intent == "search_in_application":
        tool_name, args = "search_in_application", {"name": target, "query": request.query}
    elif intent == "play_media_content":
        tool_name = "play_youtube_song"
        args = {"query": request.query or "music", "avoid_current": "avoid_current" in request.modifiers}
        for modifier in request.modifiers:
            if modifier.startswith("result_index="):
                requested_index = int(modifier.split("=", 1)[1])
                args["result_index"] = 11 if requested_index < 0 else min(11, requested_index)
    elif intent == "pause_current_media":
        tool_name, args = "control_media", {"action": "pause"}
    elif intent == "resume_current_media":
        tool_name, args = "control_media", {"action": "resume"}
    elif intent == "inspect_current_media":
        tool_name, args = "inspect_current_media", {}
    elif intent == "inspect_current_page":
        tool_name, args = "inspect_current_page", {}
    elif intent == "inspect_application":
        tool_name, args = "inspect_application", {"name": target}
    elif intent == "open_project":
        tool_name, args = "open_project_in_vscode", {"name": target}
    elif intent == "send_whatsapp_message":
        tool_name, args = "send_whatsapp_message", {"contact": target, "message": request.query}
    elif intent == "copy_application_text":
        tool_name, args = "copy_application_text", {"target_window": target}
    elif intent in {"type_text", "copy_selection", "paste_text"}:
        if not request.target:
            noun = "type into" if intent == "type_text" else "paste into" if intent == "paste_text" else "copy from"
            return intent, ToolResult("clarification_required", f"Which open window should I {noun}?"), {}
        tool_name = intent
        args = {"target_window": request.target}
        if intent == "type_text":
            args["text"] = request.query
    else:
        return None
    try:
        return tool_name, run_tool_result(tool_name, args), args
    except NeedsConfirmation as need:
        return need.tool_name, ToolResult("confirmation_required", f"Confirm: {need.tool_name}"), need.tool_args


def try_fast_route(
    user_text: str,
    context: dict | None = None,
    request: UserRequest | None = None,
) -> tuple[str, ToolResult | str, dict] | None:
    """
    Returns (tool_name, result_or_confirm_message, args) if a deterministic
    match ran, else None (meaning: fall through to the normal LLM agent loop).
    """
    text = re.sub(r"[.!?]+$", "", (user_text or "").strip())
    if not is_fast_route_candidate(text):
        return None

    match = _TIME_FAST_RE.fullmatch(text)
    if match:
        tool_name, args = "get_time", {}
    else:
        match = _OPEN_FAST_RE.fullmatch(text)
        if match:
            target_text = match.group(1).strip()
            tool_name, args = _open_target_or_app(target_text)
            if tool_name == "browser_open" and not args.get("target"):
                return None
            if tool_name == "browser_open":
                target = resolve_target(target_text)
                if target and target.name in {"wikipedia", "youtube", "google", "github", "reddit"}:
                    tool_name, args = "open_and_remember_site", {"site_name": target.name}
        else:
            match = _PLAY_YOUTUBE_FAST_RE.fullmatch(text)
            if not match:
                return None
            tool_name, args = "play_youtube_song", {"query": match.group(1)}
    log.info("FAST ROUTE matched %r -> %s %s", text, tool_name, args)

    try:
        result = run_tool_result(tool_name, args)
        return tool_name, result, args
    except NeedsConfirmation as need:
        return tool_name, f"Confirm: {need.tool_name} {need.tool_args}? Reply 'yes' or 'no'.", args
