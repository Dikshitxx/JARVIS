import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from app.core import config
from app.tools.registry import Tool, register


def _find_executable(candidates: list[str]) -> str | None:
    for candidate in candidates:
        expanded = os.path.expandvars(candidate)
        if os.path.isabs(expanded):
            if os.path.exists(expanded):
                return expanded
        else:
            found = shutil.which(expanded)
            if found:
                return found
    return None


START_MENU_DIRS = [
    os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
]


def _is_blocked(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in config.BLOCKED_APP_TERMS)


def _find_shortcut(query: str) -> Path | None:
    q = query.strip().lower()
    if not q:
        return None
    exact, partial = [], []
    for base in START_MENU_DIRS:
        for lnk in Path(base).rglob("*.lnk"):
            stem = lnk.stem.lower()
            if stem == q:
                exact.append(lnk)
            elif q in stem:
                partial.append(lnk)
    if exact:
        return exact[0]
    if partial:
        return min(partial, key=lambda p: len(p.stem))
    return None


def _needs_confirm(args: dict) -> bool:
    name = str(args.get("name", "")).strip().lower()
    return name not in config.ALLOWED_APPS and not _is_blocked(name)


def _list_start_apps() -> list[dict]:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=15, shell=False,
        )
        data = json.loads(out.stdout or "[]")
    except Exception:
        return []
    return [data] if isinstance(data, dict) else data


def _find_store_app(query: str) -> dict | None:
    q = query.strip().lower()
    if not q:
        return None
    exact, partial = [], []
    for app in _list_start_apps():
        name = str(app.get("Name", "")).lower()
        if name == q:
            exact.append(app)
        elif q in name:
            partial.append(app)
    if exact:
        return exact[0]
    if partial:
        return min(partial, key=lambda a: len(a["Name"]))
    return None


def open_app(name: str) -> str:
    key = name.strip().lower()
    if key in config.ALLOWED_APPS:
        exe = _find_executable(config.ALLOWED_APPS[key])
        if exe is None:
            return f"Error: could not find {key} on this computer."
        try:
            subprocess.Popen(
                [exe],
                shell=False,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except Exception as e:
            return f"Error: failed to launch {key}: {e}"
        time.sleep(1.0)  # give the window time to open and receive focus
        return f"Launched {key}."

    if _is_blocked(key):
        return f"Refused: '{name}' is blocked and cannot be opened."
    shortcut = _find_shortcut(key)
    if shortcut is not None:
        if _is_blocked(shortcut.stem):
            return f"Refused: '{shortcut.stem}' is blocked and cannot be opened."
        try:
            os.startfile(str(shortcut))
        except Exception as e:
            return f"Error: failed to launch {shortcut.stem}: {e}"
        time.sleep(1.0)  # give the window time to open and receive focus
        return f"Launched {shortcut.stem}."

    store_app = _find_store_app(key)
    if store_app is None:
        return f"Error: I could not find an app named '{name}' on this computer."
    if _is_blocked(store_app["Name"]):
        return f"Refused: '{store_app['Name']}' is blocked and cannot be opened."
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{store_app['AppID']}"], shell=False)
    except Exception as e:
        return f"Error: failed to launch {store_app['Name']}: {e}"
    time.sleep(1.0)  # give the window time to open and receive focus
    return f"Launched {store_app['Name']}."


register(Tool(
    name="open_app",
    description="Open an application by name, e.g. 'notepad', 'spotify', 'whatsapp'.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The app name"}},
        "required": ["name"],
    },
    func=open_app,
    needs_confirm=_needs_confirm,
))


CLOSE_PROCESS_NAMES = {
    "notepad": ["notepad.exe"],
    "calculator": ["calculatorapp.exe", "calc.exe"],
    "vscode": ["code.exe"],
    "brave": ["brave.exe"],
}


def close_app(name: str) -> str:
    key = name.strip().lower()
    if key not in CLOSE_PROCESS_NAMES:
        return f"Refused: '{name}' cannot be closed. Closable apps: {', '.join(CLOSE_PROCESS_NAMES)}"
    targets = set(CLOSE_PROCESS_NAMES[key])
    closed = 0
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() in targets:
                proc.terminate()
                closed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if closed == 0:
        return f"{key} is not running."
    return f"Closed {closed} {key} process(es)."


register(Tool(
    name="close_app",
    description="Close a running application. This needs the user's confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": list(CLOSE_PROCESS_NAMES.keys()),
                "description": "The app to close",
            }
        },
        "required": ["name"],
    },
    func=close_app,
    risk="confirm",
))
