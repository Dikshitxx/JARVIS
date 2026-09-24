from pathlib import Path

from app.core import config
from app.tools.registry import Tool, register

MAX_READ_CHARS = 4000


def _resolve_safe(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        p = config.DATA_DIR / p
    p = p.resolve()
    for allowed in config.ALLOWED_DIRS:
        if p == allowed.resolve() or allowed.resolve() in p.parents:
            return p
    raise PermissionError(f"Access outside allowed folders is not permitted: {p}")


def list_files(path: str = ".") -> str:
    p = _resolve_safe(path)
    if not p.is_dir():
        return f"'{p}' is not a folder."
    items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    if not items:
        return "The folder is empty."
    return "\n".join(f"{'[folder]' if i.is_dir() else '[file]'} {i.name}" for i in items[:100])


def read_text_file(path: str) -> str:
    p = _resolve_safe(path)
    if not p.is_file():
        return f"'{p}' is not a file."
    if p.suffix.lower() not in {".txt", ".md", ".json", ".csv", ".log", ".py"}:
        return "Only text-like files can be read."
    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + "\n...[truncated]"
    return text


register(Tool(
    name="list_files",
    description="List files and folders inside the user's data folder. Paths are relative to the data folder, e.g. 'documents'. Use '.' for the top level.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Folder path relative to the data folder"}},
    },
    func=list_files,
))

register(Tool(
    name="read_text_file",
    description="Read the contents of a text file inside the user's data folder, e.g. 'documents/notes.txt'.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path relative to the data folder"}},
        "required": ["path"],
    },
    func=read_text_file,
))
