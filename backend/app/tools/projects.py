import os
from pathlib import Path

from app.tools.registry import Tool, register

PROJECT_MARKERS = {"package.json", "requirements.txt", "pyproject.toml", ".git"}

FAST_SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home(),
    Path("C:/"),
]

MAX_DEPTH = 2


def _is_project_dir(path: Path) -> bool:
    try:
        entries = {p.name for p in path.iterdir()}
    except (PermissionError, OSError):
        return False
    return bool(entries & PROJECT_MARKERS)


def _search(root: Path, name_lower: str, max_depth: int) -> Path | None:
    if not root.exists():
        return None
    try:
        for dirpath, dirnames, _ in os.walk(root):
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth >= max_depth:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in {"node_modules", "__pycache__", ".venv", "venv"}]
            for d in dirnames:
                if name_lower in d.lower():
                    candidate = Path(dirpath) / d
                    if _is_project_dir(candidate):
                        return candidate
    except (PermissionError, OSError):
        pass
    return None


def find_project(name: str) -> str:
    name_lower = name.strip().lower()
    if not name_lower:
        return "Error: no project name given."

    for root in FAST_SEARCH_ROOTS:
        found = _search(root, name_lower, MAX_DEPTH)
        if found:
            return f"Found: {found}"

    return (
        f"Not found in common folders (Desktop, Documents, home). "
        f"Tell me the exact path, or ask me to search all of C:\\ (slower)."
    )


def find_project_deep(name: str) -> str:
    name_lower = name.strip().lower()
    if not name_lower:
        return "Error: no project name given."
    found = _search(Path("C:/"), name_lower, max_depth=6)
    if found:
        return f"Found: {found}"
    return f"Could not find a project matching '{name}' on C:\\ drive."


register(Tool(
    name="find_project",
    description="Search common folders (Desktop, Documents, home) for a project folder by name. Fast. Use this first when the user asks to find/open a project.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The project name to search for, e.g. 'FlowAPI'"}},
        "required": ["name"],
    },
    func=find_project,
))

register(Tool(
    name="find_project_deep",
    description="Search the entire C: drive for a project folder by name. Slow (can take a minute). Only use this if find_project already failed and the user wants a deeper search. This needs the user's confirmation.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The project name to search for"}},
        "required": ["name"],
    },
    func=find_project_deep,
    risk="confirm",
))