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
ACTION_TOOLS = {"type_text", "click_mouse", "move_mouse", "press_key"}

REMEMBER_TRIGGERS = {"remember", "save", "note", "don't forget", "dont forget"}
ACTION_TRIGGERS = {
    "type", "write", "insert", "click", "move mouse", "move the mouse",
    "press", "press key", "search", "open", "play", "pause", "stop",
    "resume", "message", "send", "close",
}

# Capabilities with NO real tool behind them. Checked BEFORE the LLM is even
# called, so the model never gets a chance to fabricate a fake result for
# something JARVIS genuinely cannot do yet. Add to this list as new gaps
# are discovered, rather than hoping prompt wording stops fabrication.
KNOWN_GAPS = {
    "email": "checking or sending email",
    "gmail": "checking or sending email",
    "inbox": "checking email",
    "calendar": "checking your calendar",
    "sms": "sending text messages",
    "text message": "sending text messages",
    "phone call": "making phone calls",
    "call someone": "making phone calls",
}

BROWSER_FILES_CLARIFICATION = (
    "Do you mean downloaded files, files visible on a webpage, bookmarks, "
    "or files on your computer?"
)


def check_known_gap(user_text: str) -> str | None:
    """Returns a plain 'not implemented' message if the request matches a
    known capability gap, else None. Called BEFORE the LLM, so no tool call
    or fabrication is ever possible for these."""
    lowered = user_text.lower()
    for keyword, description in KNOWN_GAPS.items():
        if keyword in lowered:
            return f"That's not something I can do yet, boss — {description} isn't implemented in me right now."
    return None


def _looks_like_fabricated_placeholder(value: str) -> bool:
    """Catches cases like the model inventing an 'error message' as the
    actual content to send/type, instead of real user-intended content."""
    if not value or not value.strip():
        return True
    lowered = value.lower()
    if len(value) > 40 and ("error" in lowered or "unable to" in lowered or "failed to" in lowered):
        return True
    return False


def validate_call(tool_name: str, args: dict, user_text: str) -> str | None:
    """
    Returns a Skipped/Refused reason string if this call should NOT execute,
    or None if it's cleared to run. This is the single gate every tool call
    goes through — add new rules here, not as scattered inline checks.
    """
    lowered_text = user_text.lower()

    if tool_name in REMEMBER_TOOLS:
        if not any(t in lowered_text for t in REMEMBER_TRIGGERS):
            return f"Skipped: {tool_name} was not called because the user did not ask to remember, save, or note anything."

    if tool_name in ACTION_TOOLS:
        if not any(t in lowered_text for t in ACTION_TRIGGERS):
            return f"Skipped: {tool_name} was not called because the user's message didn't ask for an on-screen action."

    if tool_name == "send_whatsapp_message":
        contact = str(args.get("contact", "")).strip()
        message = str(args.get("message", "")).strip()
        if not contact or not message:
            return "Refused: contact name and message text are both required — nothing was sent."
        if _looks_like_fabricated_placeholder(message):
            return "Refused: the message content looks like a fabricated placeholder, not real content — nothing was sent."

    return None


def check_ambiguous_request(user_text: str) -> str | None:
    """Stop ambiguous browser/files requests before the model can guess."""
    lowered = user_text.lower()
    browser_terms = ("browser", "webpage", "web page", "website")
    file_terms = ("file", "files", "folder", "folders", "download", "downloads")
    if any(term in lowered for term in browser_terms) and any(term in lowered for term in file_terms):
        return BROWSER_FILES_CLARIFICATION
    return None


def prepare_call(tool_name: str, args: dict) -> dict:
    """Make narrow, deterministic repairs to arguments before validation."""
    prepared = dict(args or {})
    if tool_name == "send_whatsapp_message":
        contact = str(prepared.get("contact", "")).strip()
        message = str(prepared.get("message", "")).strip().lower()
        if contact and message in {"greet him", "greet her", "greet them", "greet", "say hello"}:
            prepared["message"] = f"Hello {contact}, how are you?"
    return prepared