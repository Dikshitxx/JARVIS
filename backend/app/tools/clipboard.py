import pyperclip
from app.tools.registry import Tool, register

def copy_text(text: str) -> str:
    pyperclip.copy(text)
    return f"Copied {len(text)} characters to clipboard."

def paste_text() -> str:
    return pyperclip.paste()

register(Tool(
    name="copy_text",
    description="Copy text to the system clipboard.",
    parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    func=copy_text,
))
register(Tool(
    name="paste_text",
    description="Read the current clipboard contents.",
    parameters={"type": "object", "properties": {}},
    func=paste_text,
))