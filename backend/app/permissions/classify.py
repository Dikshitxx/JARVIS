from typing import Literal
from app.tools.registry import REGISTRY

Decision = Literal["ALLOW", "CONFIRM", "BLOCK"]
CONFIRM_TOOLS = {
    "send_whatsapp_message",
    "remember_fact",
    "remember_person",
    "forget_memory",
    "clear_text",
    "browser_interaction",
    "close_browser_tab",
    "close_app",
    "click_mouse",
    "take_screenshot",
    "find_project_deep",
    "start_project",
    "stop_project",
}
def classify(tool_name: str, args: dict) -> tuple[Decision, str]:
    """
    Single source of truth for whether a tool call is allowed to run immediately,
    needs user confirmation, or is refused outright.
    Returns (decision, reason) — reason is for logging, not shown raw to the user.
    """
    tool = REGISTRY.get(tool_name)
    if tool is None:
        return "BLOCK", f"unknown tool '{tool_name}'"

    # Special case: remember_fact with credential-like content is always blocked,
    # never just confirm-gated (moved here from memory_tools._SECRET_PATTERN check
    # so it shows up in permission logs; memory_tools still does its own defensive
    # check too as a second layer).
    if tool_name == "remember_fact":
        from app.tools.memory_tools import _SECRET_PATTERN
        fact_text = str(args.get("content", ""))
        if _SECRET_PATTERN.search(fact_text):
            return "BLOCK", "credential-like content detected"

    if tool.risk == "blocked":
        return "BLOCK", "tool is statically blocked"
    if tool.risk == "confirm" or tool_name in CONFIRM_TOOLS:
        return "CONFIRM", "tool requires confirmation"
    if tool_name == "press_key" and str(args.get("key", "")).strip().lower() in {"enter", "alt+f4"}:
        return "CONFIRM", "key press may submit content or close a window"
    return "ALLOW", "tool is safe by default"
