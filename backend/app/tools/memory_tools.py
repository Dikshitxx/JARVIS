import re

from app.memory import store
from app.tools.registry import Tool, register


_SECRET_PATTERN = re.compile(r"(password|passwd|api[_ -]?key|secret|token|pin\b|card number)", re.IGNORECASE)


def _is_valid_fact(text: str) -> bool:
    words = text.split()
    return len(words) >= 4 and len(text) >= 15


def remember_fact(content: str) -> str:
    parts = [p.strip(" .") for p in re.split(r"[\n;]|(?<=[a-z0-9])\.\s+", content) if p.strip(" .")]
    saved, refused = [], []
    invalid = []
    for part in parts[:5]:
        if _SECRET_PATTERN.search(part):
            refused.append(part)
            continue
        if not _is_valid_fact(part):
            invalid.append(part)
            continue
        store.add_fact(part)
        saved.append(part)
    if not saved and refused:
        return "Refused: I do not store passwords, keys, or other credentials in memory."
    if not saved and invalid:
        return (
            "Error: that fact was too short or incomplete: "
            + repr(invalid[0])
            + ". Call remember_fact again with a complete sentence, e.g. 'User's favorite framework is Next.js'."
        )
    result = "Saved:\n" + "\n".join(f"- {s}" for s in saved)
    if refused:
        result += "\n(Skipped one item that looked like a credential.)"
    if invalid:
        result = (
            "PARTIAL SAVE. Only these were saved:\n" + "\n".join(f"- {s}" for s in saved)
            + "\nNOT SAVED (incomplete): " + ", ".join(repr(i) for i in invalid)
            + "\nTell the user what was NOT saved, and call remember_fact again with the full sentence for each missing fact."
        )
    return result


def list_memories() -> str:
    facts = store.list_facts()
    if not facts:
        return "I have no saved memories yet."
    return "\n".join(f"- {content}" for _, content in reversed(facts))


def forget_memory(keyword: str) -> str:
    removed = store.delete_matching(keyword)
    if not removed:
        return f"No saved memories matched '{keyword}'."
    return "Deleted:\n" + "\n".join(f"- {c}" for c in removed)


register(Tool(
    name="remember_fact",
    description="Save ONE fact the user wants remembered, as a short sentence that starts with 'User', e.g. 'User is a frontend developer'. If the user gives several facts, call this tool once per fact. Never save passwords, API keys, or financial numbers.",
    parameters={
        "type": "object",
        "properties": {"content": {"type": "string", "description": "The fact to remember"}},
        "required": ["content"],
    },
    func=remember_fact,
))

register(Tool(
    name="list_memories",
    description="List everything saved in long-term memory. Use when the user asks what you remember about them.",
    parameters={"type": "object", "properties": {}},
    func=list_memories,
))

register(Tool(
    name="forget_memory",
    description="Delete saved memories that contain a keyword. Use when the user asks to forget something.",
    parameters={
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "A word or short phrase, e.g. 'Next.js'"}},
        "required": ["keyword"],
    },
    func=forget_memory,
))
