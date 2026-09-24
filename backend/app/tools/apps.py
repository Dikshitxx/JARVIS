import os
import shutil
import subprocess

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
