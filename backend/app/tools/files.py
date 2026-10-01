import fnmatch
import os
from pathlib import Path
import time

from app.core import config
from app.tools.registry import Tool, ToolResult, register

MAX_READ_CHARS = 4000


def _safe_roots() -> dict[str, Path]:
    home = Path.home()
    one_drive = Path(os.environ.get("OneDrive", str(home / "OneDrive")))
    roots = {"data": Path(config.DATA_DIR).resolve()}
    for name in ("Desktop", "Documents", "Downloads"):
        candidates = [one_drive / name, home / name]
        root = next((candidate for candidate in candidates if candidate.is_dir()), candidates[-1])
        roots[name.lower()] = root.resolve()
    return roots


def _allowed_roots() -> list[Path]:
    roots = [Path(root).resolve() for root in config.ALLOWED_DIRS]
    roots.extend(_safe_roots().values())
    return list(dict.fromkeys(roots))


def _resolve_safe(path_str: str) -> Path:
    raw = Path(path_str or ".")
    if not raw.is_absolute():
        parts = raw.parts
        roots = _safe_roots()
        alias = parts[0].strip().lower() if parts else ""
        if alias in roots and alias != "data":
            raw = roots[alias].joinpath(*parts[1:])
        elif alias == "data":
            raw = roots["data"].joinpath(*parts[1:])
        else:
            raw = roots["data"] / raw
    path = raw.resolve()
    for allowed in _allowed_roots():
        if path == allowed or allowed in path.parents:
            return path
    raise PermissionError(f"Access outside allowed folders is not permitted: {path}")


def list_files(path: str = ".") -> ToolResult:
    try:
        p = _resolve_safe(path)
    except (OSError, PermissionError) as exc:
        return ToolResult("invalid_action", str(exc), verification_status="failed")
    if not p.is_dir():
        return ToolResult("failure", f"'{p}' is not a folder.", verification_status="failed")
    try:
        items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except OSError as exc:
        return ToolResult("failure", f"Could not list '{p}': {exc}", verification_status="failed")
    if not items:
        return ToolResult("success", f"The folder is empty: {p}.", data={"path": str(p), "items": []}, verification_status="verified")
    names = [f"{'[folder]' if i.is_dir() else '[file]'} {i.name}" for i in items[:100]]
    return ToolResult("success", "\n".join(names), data={"path": str(p), "items": names}, verification_status="verified")


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


def find_file(query: str, path: str = "") -> ToolResult:
    """Search files and folders only in a named safe root or common user folders."""
    query = (query or "").strip().strip('"\'')
    if not query:
        return ToolResult("clarification_required", "Tell me a file name or extension to search for.", verification_status="failed")
    if path:
        try:
            search_roots = [_resolve_safe(path)]
        except (OSError, PermissionError) as exc:
            return ToolResult("invalid_action", str(exc), verification_status="failed")
    else:
        roots = _safe_roots()
        search_roots = [roots[name] for name in ("desktop", "documents", "downloads", "data")]

    pattern = query.casefold()
    extension = pattern if pattern.startswith(".") and not any(char in pattern for char in "*?[") else ""
    wildcard = any(char in pattern for char in "*?[")
    skip_dirs = {".git", ".venv", "venv", "node_modules", "appdata", "$recycle.bin", "system volume information"}
    deadline = time.monotonic() + 8.0
    file_matches: list[str] = []
    folder_matches: list[str] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            kept_dirs = []
            for dirname in sorted(dirs, key=str.casefold):
                directory = Path(current) / dirname
                if dirname.casefold() in skip_dirs or directory.is_symlink():
                    continue
                kept_dirs.append(dirname)
                folded = dirname.casefold()
                if not extension and (fnmatch.fnmatchcase(folded, pattern) if wildcard else pattern in folded):
                    folder_matches.append(str(directory))
                    if len(file_matches) + len(folder_matches) >= 10:
                        break
            dirs[:] = kept_dirs
            if len(file_matches) + len(folder_matches) < 10:
                for filename in sorted(files, key=str.casefold):
                    folded = filename.casefold()
                    file_path = str(Path(current) / filename)
                    if extension and Path(filename).suffix.casefold() == extension:
                        file_matches.append(file_path)
                    elif wildcard and fnmatch.fnmatchcase(folded, pattern):
                        file_matches.append(file_path)
                    elif not extension and not wildcard and pattern in folded:
                        file_matches.append(file_path)
                    if len(file_matches) + len(folder_matches) >= 10:
                        break
            if len(file_matches) + len(folder_matches) >= 10 or time.monotonic() >= deadline:
                break
        if len(file_matches) + len(folder_matches) >= 10 or time.monotonic() >= deadline:
            break
    matches = folder_matches + file_matches
    if not matches:
        return ToolResult("success", f"No file or folder matching '{query}' was found in the searched safe folders.", data={"matches": [], "files": [], "folders": []}, verification_status="verified")
    lines = [f"[folder] {match}" for match in folder_matches] + file_matches
    return ToolResult(
        "success", "\n".join(lines),
        data={"matches": matches, "files": file_matches, "folders": folder_matches},
        verification_status="verified",
    )


register(Tool(
    name="list_files",
    description="List actual file and folder names under the user's safe Desktop, Documents, Downloads, or JARVIS data roots. Use when asked what is on the device, what a folder contains, or to list files. Choose path from a named safe root; do not guess or access arbitrary system paths. Returns verified names and the resolved path.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Folder path relative to the data folder"}},
    },
    func=list_files,
    keywords=("list desktop files", "list documents", "what is on my device", "files on my desktop"),
    capabilities=frozenset({"files"}),
))

register(Tool(
    name="find_file",
    description="Search real file and folder names by substring, wildcard, or extension in safe Desktop, Documents, Downloads, or JARVIS data roots. Use for requests to find something on the user's device. Returns real matching paths or a verified no-match result; it does not search the whole drive. Never invent a path or search outside these roots.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "File name, substring, wildcard, or extension such as .csv"},
            "path": {"type": "string", "description": "Optional safe root name: Desktop, Documents, Downloads, or data"},
        },
        "required": ["query"],
    },
    func=find_file,
    keywords=("find file", "search files", "search in my files", "file extension"),
    capabilities=frozenset({"files"}),
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
