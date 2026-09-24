import os
import shutil
import subprocess

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


def open_app(name: str) -> str:
    key = name.strip().lower()
    if key not in config.ALLOWED_APPS:
        return f"Refused: '{name}' is not an allowed app. Allowed apps: {', '.join(config.ALLOWED_APPS)}"
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
    return f"Launched {key}."


register(Tool(
    name="open_app",
    description="Open an application on this computer.",
    parameters={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "enum": list(config.ALLOWED_APPS.keys()),
                "description": "The app to open",
            }
        },
        "required": ["name"],
    },
    func=open_app,
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
