from app.memory import store
from app.tools.registry import Tool, register


def remember_person(name: str, relationship: str = "", notes: str = "") -> str:
    store.add_person(name, relationship, notes)
    parts = [name]
    if relationship:
        parts.append(f"({relationship})")
    if notes:
        parts.append(f"— {notes}")
    return f"Saved person: {' '.join(parts)}"


def list_known_people() -> str:
    people = store.list_people()
    if not people:
        return "I don't have anyone saved yet."
    lines = []
    for _, name, relationship, notes in reversed(people):
        line = f"- {name}"
        if relationship:
            line += f" ({relationship})"
        if notes:
            line += f": {notes}"
        lines.append(line)
    return "\n".join(lines)


register(Tool(
    name="remember_person",
    description="Save a person's name and relationship to the user permanently. Only call this when the user explicitly asks to remember, save, or note a person — never just because they mentioned someone in passing.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The person's name"},
            "relationship": {"type": "string", "description": "e.g. 'friend', 'colleague', 'classmate'"},
            "notes": {"type": "string", "description": "Any other detail worth remembering about them"},
        },
        "required": ["name"],
    },
    func=remember_person,
))

register(Tool(
    name="list_known_people",
    description="List everyone saved in long-term memory. Use when the user asks who you remember or know about.",
    parameters={"type": "object", "properties": {}},
    func=list_known_people,
))