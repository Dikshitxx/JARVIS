from typing import Literal
from app.tools.registry import REGISTRY

Decision = Literal["ALLOW", "CONFIRM", "BLOCK"]


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

    # Special case: open_app has argument-dependent confirmation logic.
    if tool_name == "open_app":
        from app.tools.apps import _needs_confirm
        if _needs_confirm(args):
            return "CONFIRM", "app not in configured allowlist"
        return "ALLOW", "app is in configured allowlist"

    # Default: static risk level from the tool's registration.
    if tool.risk == "blocked":
        return "BLOCK", "tool is statically blocked"
    if tool.risk == "confirm":
        return "CONFIRM", "tool requires confirmation by default"
    return "ALLOW", "tool is safe by default"