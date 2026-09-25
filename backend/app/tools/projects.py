import json
import os
import shlex
import socket
import subprocess
import time
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


def inspect_project(path: str) -> str:
    p = Path(path)
    if not p.is_dir():
        return f"Error: '{path}' is not a folder."

    lines = [f"Project: {p}"]
    entries = {e.name for e in p.iterdir()} if p.exists() else set()

    if "package.json" in entries:
        try:
            data = json.loads((p / "package.json").read_text(encoding="utf-8"))
            lines.append("Type: Node.js")
            if "scripts" in data:
                lines.append("Scripts: " + ", ".join(f"{k}" for k in data["scripts"].keys()))
            deps = list(data.get("dependencies", {}).keys())
            if deps:
                lines.append(f"Key dependencies: {', '.join(deps[:8])}")
        except (json.JSONDecodeError, OSError) as e:
            lines.append(f"Type: Node.js (could not fully parse package.json: {e})")

    if "requirements.txt" in entries:
        lines.append("Type: Python (requirements.txt)")
        try:
            reqs = (p / "requirements.txt").read_text(encoding="utf-8").splitlines()
            reqs = [r.strip() for r in reqs if r.strip() and not r.startswith("#")]
            lines.append(f"Dependencies: {', '.join(reqs[:8])}")
        except OSError:
            pass

    if "pyproject.toml" in entries:
        lines.append("Type: Python (pyproject.toml)")

    if ".env" in entries:
        try:
            env_keys = []
            for line in (p / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    env_keys.append(line.split("=", 1)[0])
            lines.append(f".env present with keys: {', '.join(env_keys)} (values not read)")
        except OSError:
            lines.append(".env present (could not read key names)")

    if "docker-compose.yml" in entries or "docker-compose.yaml" in entries:
        lines.append("Has its own docker-compose.yml")

    if ".git" in entries:
        lines.append("Git repository: yes")

    if len(lines) == 1:
        return f"'{path}' does not look like a recognized project (no package.json, requirements.txt, pyproject.toml, or .git found)."

    return "\n".join(lines)


register(Tool(
    name="inspect_project",
    description="Inspect a project folder: detect its type (Node/Python), list its scripts/dependencies, and check for a .env file (key names only, never values) and Docker setup.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Full path to the project folder"}},
        "required": ["path"],
    },
    func=inspect_project,
))


_running_projects: dict[str, subprocess.Popen] = {}
_running_ports: dict[str, int] = {}


def _port_is_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def _try_launch(p: Path, args: list[str], port: int) -> tuple[subprocess.Popen | None, str | None]:
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(p),
            shell=False,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except Exception as e:
        return None, f"failed to start '{' '.join(args)}' in {p}: {e}"
    return proc, None


def _wait_for_port_or_death(proc: subprocess.Popen, port: int, timeout_s: int = 10) -> str:
    """Returns 'up', 'died', or 'timeout'."""
    for _ in range(timeout_s):
        if proc.poll() is not None:
            return "died"
        if _port_is_open(port):
            return "up"
        time.sleep(1)
    return "timeout"


def start_project(path: str, command: str, port: int) -> str:
    p = Path(path)
    if not p.is_dir():
        return f"Error: '{path}' is not a folder."
    key = str(p.resolve())

    if key in _running_projects and _running_projects[key].poll() is None:
        return f"'{path}' already has a tracked process running (PID {_running_projects[key].pid})."

    if _port_is_open(port):
        return f"Refused: port {port} is already in use by something else. Choose a different port or stop that process first."

    try:
        args = shlex.split(command)
    except ValueError as e:
        return f"Error: could not parse command '{command}': {e}"

    attempt = 1
    max_attempts = 2
    last_reason = None

    while attempt <= max_attempts:
        proc, launch_err = _try_launch(p, args, port)
        if proc is None:
            last_reason = launch_err
            attempt += 1
            continue

        outcome = _wait_for_port_or_death(proc, port)

        if outcome == "up":
            _running_projects[key] = proc
            _running_ports[key] = port
            suffix = f" (recovered after {attempt} attempts)" if attempt > 1 else ""
            return f"Started '{command}' in {path} (PID {proc.pid}), port {port} confirmed open{suffix}."

        if outcome == "died":
            exit_code = proc.poll()
            last_reason = f"process exited immediately (exit code {exit_code}) on attempt {attempt}"
            attempt += 1
            continue

        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return (
            f"Failed: '{command}' in {path} started (PID was {proc.pid}) but port {port} "
            f"never opened within 10s. Not retrying (process was alive, so retrying the same "
            f"command won't help) — check the command/port are correct."
        )

    return f"Failed: '{command}' in {path} could not be started after {max_attempts} attempts. Last reason: {last_reason}"


def _verify_start_project(args: dict, result: str) -> bool:
    # start_project() now verifies internally before returning. This just re-confirms
    # the final state matches what was reported, for consistency with the registry's
    # verify() hook contract.
    if not result.startswith("Started"):
        return False
    port = args.get("port")
    return port is not None and _port_is_open(int(port))


def stop_project(path: str) -> str:
    key = str(Path(path).resolve())
    proc = _running_projects.get(key)
    if proc is None or proc.poll() is not None:
        return f"No tracked running process for '{path}'."
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    del _running_projects[key]
    _running_ports.pop(key, None)
    return f"Stopped process for '{path}'."


def _verify_stop_project(args: dict, result: str) -> bool:
    return result.startswith("Stopped")


def project_status(path: str) -> str:
    key = str(Path(path).resolve())
    proc = _running_projects.get(key)
    if proc is None:
        return f"'{path}' is not tracked as running."
    alive = proc.poll() is None
    port = _running_ports.get(key)
    port_status = f", port {port} {'open' if port and _port_is_open(port) else 'not responding'}" if port else ""
    return f"'{path}': process {'running' if alive else 'exited'} (PID {proc.pid}){port_status}."


register(Tool(
    name="start_project",
    description="Start a project's dev server as a background process and verify it's actually listening on the given port. This needs the user's confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Full path to the project folder"},
            "command": {"type": "string", "description": "The command to run, e.g. 'npm run dev' or 'uvicorn app.main:app'"},
            "port": {"type": "integer", "description": "The port the server is expected to listen on"},
        },
        "required": ["path", "command", "port"],
    },
    func=start_project,
    risk="confirm",
    verify=_verify_start_project,
))

register(Tool(
    name="stop_project",
    description="Stop a previously started project's background process.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Full path to the project folder"}},
        "required": ["path"],
    },
    func=stop_project,
    risk="confirm",
    verify=_verify_stop_project,
))

register(Tool(
    name="project_status",
    description="Check whether a project's dev server is currently tracked as running, and whether its port is responding.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Full path to the project folder"}},
        "required": ["path"],
    },
    func=project_status,
))