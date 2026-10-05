"""Validate tool arguments without interpreting the user's wording.

Intent belongs to model tool calling. Permission policy belongs to
``permissions.classify``. This module performs narrow argument checks only.
"""

from typing import Any


def validate_call(tool_name: str, args: dict[str, Any], user_text: str) -> str | None:
    """Return a reason when a tool call is structurally missing required data."""
    if tool_name == "send_whatsapp_message":
        contact = str((args or {}).get("contact", "")).strip()
        message = str((args or {}).get("message", "")).strip()
        if not contact or not message:
            return "Refused: contact name and message text are both required; nothing was sent."
    return None


def prepare_call(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Make only non-semantic repairs to tool arguments."""
    prepared = dict(args or {})
    if tool_name == "look_at_screen" and not str(prepared.get("question", "")).strip():
        prepared["question"] = "Describe the visible foreground window and read any clearly visible text."
    return prepared
