import os
import shlex
import shutil
import subprocess
from pathlib import Path

from app.core import config
from app.tools.registry import Tool, register

TIMEOUT_SECONDS = 15
MAX_OUTPUT_CHARS = 3000

FALLBACK_PATHS = {
    "ollama": Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
}


def _find_exe(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    fallback = FALLBACK_PATHS.get(name)
    return str(fallback) if fallback and fallback.exists() else None


def run_command(command: str) -> str:
    normalized = " ".join(command.split())
    if normalized not in config.ALLOWED_COMMANDS:
        allowed = ", ".join(config.ALLOWED_COMMANDS)
        return f"Refused: '{normalized}' is not an allowed command. Allowed commands: {allowed}"

    args = shlex.split(normalized)
    exe = _find_exe(args[0])
    if exe is None:
        return f"Error: '{args[0]}' was not found on this computer."
    args[0] = exe

    try:
        result = subprocess.run(
            args,
            cwd=config.PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {TIMEOUT_SECONDS} seconds."

    output = (result.stdout or "") + (result.stderr or "")
    output = output.strip() or "(no output)"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return f"exit code {result.returncode}\n{output}"


register(Tool(
    name="run_command",
    description="Run a read-only terminal command (tool versions, git status, installed packages, Ollama models) and return its output.",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": config.ALLOWED_COMMANDS,
                "description": "The command to run",
            }
        },
        "required": ["command"],
    },
    func=run_command,
))
