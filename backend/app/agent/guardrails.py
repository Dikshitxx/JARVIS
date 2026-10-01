"""
Single source of truth for whether a proposed tool call is allowed to
actually execute. This consolidates checks that were previously scattered
inline in agent.py (remember-trigger, action-trigger, placeholder detection)
into one place, so future tools/rules get added here once instead of as
one-off patches in the agent loop.

Philosophy: the model proposes, this code decides. A 3B local model will
sometimes call tools it shouldn't, invent plausible-looking arguments when
information is missing, or fabricate results for capabilities that don't
exist. None of that is trusted — every call is checked here first.
"""

import re

REMEMBER_TOOLS = {"remember_fact", "remember_person"}

REMEMBER_TRIGGERS = {"remember", "save", "note", "don't forget", "dont forget"}
VISION_TOOLS = {"look_at_screen"}
VISION_TRIGGERS = {"screen", "see", "look at", "what does", "is this", "showing"}

def _looks_like_fabricated_placeholder(value: str) -> bool:
    """Catches cases like the model inventing an 'error message' as the
    actual content to send/type, instead of real user-intended content."""
    if not value or not value.strip():
        return True
    lowered = value.lower()
    if len(value) > 40 and ("error" in lowered or "unable to" in lowered or "failed to" in lowered):
        return True
    return False


def _has_remember_trigger(user_text: str) -> bool:
    return any(re.search(rf"\b{re.escape(trigger)}\b", user_text, re.I) for trigger in REMEMBER_TRIGGERS)


def _has_vision_trigger(user_text: str) -> bool:
    return any(re.search(rf"\b{re.escape(trigger)}\b", user_text, re.I) for trigger in VISION_TRIGGERS)


def validate_call(tool_name: str, args: dict, user_text: str) -> str | None:
    """
    Returns a Skipped/Refused reason string if this call should NOT execute,
    or None if it's cleared to run. This is the single gate every tool call
    goes through — add new rules here, not as scattered inline checks.
    """
    lowered_text = user_text.lower()

    if tool_name in REMEMBER_TOOLS:
        if not _has_remember_trigger(lowered_text):
            return f"Skipped: {tool_name} was not called because the user did not ask to remember, save, or note anything."

    if tool_name in VISION_TOOLS:
        if not _has_vision_trigger(lowered_text):
            return f"Skipped: {tool_name} was not called because the user did not ask about visible content."

    if tool_name == "clear_text" and not re.search(r"\b(?:clear|erase|empty|delete|remove)\b", lowered_text):
        return "Skipped: clear_text was not called because the user did not ask to clear or delete text."

    if tool_name == "send_whatsapp_message":
        contact = str(args.get("contact", "")).strip()
        message = str(args.get("message", "")).strip()
        if not contact or not message:
            return "Refused: contact name and message text are both required — nothing was sent."
        if _looks_like_fabricated_placeholder(message):
            return "Refused: the message content looks like a fabricated placeholder, not real content — nothing was sent."

    return None


def prepare_call(tool_name: str, args: dict) -> dict:
    """Make narrow, deterministic repairs to arguments before validation."""
    prepared = dict(args or {})
    if tool_name == "look_at_screen":
        question = str(prepared.get("question", "")).strip()
        if len(question.split()) < 3:
            prepared["question"] = "Describe the visible foreground window and read any clearly visible text."
    if tool_name == "send_whatsapp_message":
        contact = str(prepared.get("contact", "")).strip()
        message = str(prepared.get("message", "")).strip().lower()
        if contact and message in {"greet him", "greet her", "greet them", "greet", "say hello"}:
            prepared["message"] = f"Hello {contact}, how are you?"
    return prepared
