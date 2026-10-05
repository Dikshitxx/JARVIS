import json
import os
import re
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

import psutil

from app.core import config
from app.tools.browser_targets import resolve_target
from app.tools.registry import Tool, ToolResult, register


APP_ALIASES = {
    "notepad": {"notepad", "note pad", "windows notepad", "windows editor"},
    "brave": {"brave", "brave browser"},
    "calculator": {"calculator", "calc", "windows calculator"},
    "explorer": {"explorer", "file explorer", "windows explorer"},
    "vscode": {"vscode", "vs code", "visual studio code", "code"},
    "edge": {"edge", "microsoft edge", "edge browser"},
    "chrome": {"chrome", "google chrome", "chrome browser"},
    "whatsapp": {"whatsapp", "whatsapp messenger"},
}

_ENV_SNAPSHOT_TTL_SECONDS = 5.0
_ENV_SNAPSHOT_CACHE = {"payload": None, "fetched_at": 0.0}


def _invalidate_environment_snapshot() -> None:
    _ENV_SNAPSHOT_CACHE["payload"] = None
    _ENV_SNAPSHOT_CACHE["fetched_at"] = 0.0


def _normalize_app_name(value: str) -> str:
    name = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", value.lower())).strip()
    name = re.sub(r"^(?:open|launch|start|focus|switch to)\s+", "", name)
    name = re.sub(r"\s+(?:application|app)$", "", name)
    return name


def resolve_application_name(value: str) -> str | None:
    """Resolve common spoken names to configured or discoverable app names."""
    query = _normalize_app_name(value)
    for canonical, aliases in APP_ALIASES.items():
        if query in aliases:
            return canonical
    if query in config.ALLOWED_APPS:
        return query
    for app in _list_start_apps():
        app_name = _normalize_app_name(str(app.get("Name", "")))
        if query and app_name == query:
            return str(app.get("Name", ""))
    return None


def resolve_application_reference(value: str) -> str | None:
    resolved = resolve_application_name(value)
    if resolved:
        return resolved
    reference = _normalize_app_name(value)
    if reference not in {"browser", "the browser", "that browser", "this browser", "current browser"}:
        return None
    try:
        from app.agent.runtime_context import get_context

        context = get_context()
        current = context.get("current_browser") or context.get("current_application") or ""
        return resolve_application_name(str(current))
    except Exception:
        return None


def _process_names(app_name: str) -> set[str]:
    canonical = resolve_application_name(app_name) or _normalize_app_name(app_name)
    configured = config.ALLOWED_APPS.get(canonical, [])
    names = {Path(os.path.expandvars(item)).name.lower() for item in configured if item.lower().endswith(".exe")}
    names.update(name.lower() for name in CLOSE_PROCESS_NAMES.get(canonical, []))
    return names


def get_active_window_info() -> dict:
    """Read the foreground window using Win32, without changing focus."""
    if os.name != "nt":
        return {"title": "", "application": "", "pid": None}
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            process_name = psutil.Process(pid.value).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            process_name = ""
        return {"title": title.value, "application": process_name, "pid": pid.value, "hwnd": hwnd}
    except Exception:
        return {"title": "", "application": "", "pid": None, "hwnd": None}


def _is_explorer_shell_window(title: str) -> bool:
    return (title or "").strip().lower() in {"taskbar", "program manager", "desktop"}


def _matching_windows(app_name: str) -> list:
    try:
        from pywinauto import Desktop

        process_names = _process_names(app_name)
        aliases = APP_ALIASES.get(resolve_application_name(app_name) or "", {app_name.lower()})
        windows = []
        for window in Desktop(backend="uia").windows():
            try:
                title = window.window_text().strip()
                if not title:
                    continue
                if app_name == "explorer" and _is_explorer_shell_window(title):
                    continue
                process_name = psutil.Process(window.process_id()).name().lower()
                title_match = any(alias in title.lower() for alias in aliases)
                if process_name in process_names or title_match:
                    windows.append(window)
            except Exception:
                continue
        return windows
    except Exception:
        return []


def _is_running(app_name: str) -> bool:
    process_names = _process_names(app_name)
    if process_names:
        for process in psutil.process_iter(["name"]):
            try:
                if (process.info["name"] or "").lower() in process_names:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return bool(_matching_windows(app_name))


def _wait_for_window(app_name: str, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _matching_windows(app_name):
            return True
        time.sleep(0.2)
    return bool(_matching_windows(app_name))


def focus_app(name: str) -> str:
    app_name = resolve_application_name(name)
    if not app_name:
        return f"Error: I could not resolve an application named '{name}'."
    windows = _matching_windows(app_name)
    if not windows:
        return f"Error: no window for {app_name} is currently open."
    try:
        windows[0].set_focus()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            active = get_active_window_info()
            active_title = str(active.get("title", "") or "").lower()
            active_application = str(active.get("application", "") or "").lower()
            window_text = str(windows[0].window_text()).lower()
            if app_name == "explorer" and active_application.endswith("explorer.exe"):
                _invalidate_environment_snapshot()
                return f"Focused {app_name}: {active.get('title') or 'File Explorer'}"
            if active_title and (active_application in _process_names(app_name) or active_title in window_text):
                _invalidate_environment_snapshot()
                return f"Focused {app_name}: {active['title']}"
            time.sleep(0.1)
        return f"Error: focus could not be verified for {app_name}."
    except Exception as exc:
        return f"Error: could not focus {app_name}: {exc}"


def get_active_application() -> str:
    info = get_active_window_info()
    return info["application"] or "No active application could be identified."


def get_active_window() -> str:
    info = get_active_window_info()
    return info["title"] or "No active window could be identified."


def inspect_environment(force_refresh: bool = False) -> ToolResult:
    """Collect a demand-driven snapshot of the live desktop and active window."""
    from datetime import datetime, timezone

    now = time.monotonic()
    if not force_refresh:
        cached = _ENV_SNAPSHOT_CACHE.get("payload")
        cached_at = float(_ENV_SNAPSHOT_CACHE.get("fetched_at", 0.0))
        if cached is not None and (now - cached_at) < _ENV_SNAPSHOT_TTL_SECONDS:
            payload = cached
        else:
            payload = None
    else:
        payload = None

    if payload is None:
        active = get_active_window_info()
        from app.tools.browser_session import get_browser_session

        pages = get_browser_session().snapshot()
        browser = {
            "count": len(pages),
            "pages": pages,
            "visible_page": next((page for page in pages if page.get("visible")), pages[0] if pages else None),
        }

        payload = {
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "active_window": {
                "title": active.get("title", ""),
                "application": active.get("application", ""),
                "pid": active.get("pid"),
            },
            "browser": browser,
        }
        _ENV_SNAPSHOT_CACHE["payload"] = payload
        _ENV_SNAPSHOT_CACHE["fetched_at"] = now

    details = [
        f"Active window: {payload['active_window']['title'] or 'unknown'}",
        f"Application: {payload['active_window']['application'] or 'unknown'}",
    ]
    browser = payload.get("browser") or {}
    if browser.get("visible_page"):
        details.append(f"Visible browser page: {browser['visible_page']['url']}")
    elif browser.get("pages"):
        details.append(f"Tracked browser pages: {len(browser['pages'])}")
    else:
        details.append("Browser session: no visible managed page detected")

    return ToolResult(
        "success",
        "; ".join(details),
        data=payload,
        action="inspect_environment",
        verification_status="verified",
    )


def observe_environment() -> ToolResult:
    return inspect_environment()


def get_environment_snapshot() -> ToolResult:
    return inspect_environment()


def inspect_windows() -> str:
    try:
        from pywinauto import Desktop

        result = []
        for window in Desktop(backend="uia").windows():
            try:
                title = window.window_text().strip()
                if title:
                    name = psutil.Process(window.process_id()).name()
                    result.append(f"{title} ({name})")
            except Exception:
                continue
        return "Open windows:\n" + "\n".join(result[:30]) if result else "No titled windows were found."
    except Exception as exc:
        return f"Error: could not inspect windows: {exc}"


def inspect_application(name: str) -> ToolResult:
    """Check live Windows windows for a named application without focusing it."""
    if os.name != "nt":
        return ToolResult(
            "failure", "I can't inspect Windows applications on this platform.",
            action="inspect_application", target=name, verification_status="unknown",
        )
    key = resolve_application_reference(name) or _normalize_app_name(name)
    try:
        from pywinauto import Desktop

        canonical = resolve_application_name(key)
        process_names = _process_names(canonical or key)
        aliases = APP_ALIASES.get(canonical or "", {key.lower()})
        windows = []
        for window in Desktop(backend="uia").windows():
            try:
                title = window.window_text().strip()
                if not title:
                    continue
                process_name = psutil.Process(window.process_id()).name().lower()
                if process_name in process_names or any(alias in title.lower() for alias in aliases):
                    windows.append(window)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                try:
                    if any(alias in window.window_text().strip().lower() for alias in aliases):
                        windows.append(window)
                except Exception:
                    continue
            except Exception:
                continue
    except Exception as exc:
        return ToolResult(
            "failure", f"I couldn't inspect whether {key} is open: {exc}",
            action="inspect_application", target=key, verification_status="unknown",
        )
    titles = []
    for window in windows:
        try:
            title = window.window_text().strip()
            if title:
                titles.append(title)
        except Exception:
            continue
    running = _matching_processes(process_names)
    is_open = bool(titles)
    is_running = bool(running)
    if is_open:
        detail = f"{key} has an open window: {', '.join(titles[:3])}."
    elif is_running:
        detail = f"{key} has no open window detected, but {len(running)} matching process(es) are still running."
    else:
        detail = f"{key} is closed; no matching window or process was found."
    return ToolResult(
        "success", detail,
        data={"application": key, "is_open": is_open, "is_running": is_running,
              "process_count": len(running), "windows": titles[:10]},
        action="inspect_application", target=key, verification_status="verified",
    )


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
    q = _normalize_app_name(query)
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
    return False  # opening any app is treated as safe, per explicit user decision


@lru_cache(maxsize=1)
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
    q = _normalize_app_name(query)
    if not q:
        return None
    exact, partial = [], []
    for app in _list_start_apps():
        name = _normalize_app_name(str(app.get("Name", "")))
        if name == q:
            exact.append(app)
        elif q in name:
            partial.append(app)
    if exact:
        return exact[0]
    if partial:
        return min(partial, key=lambda a: len(a["Name"]))
    return None


def open_app(name: str) -> ToolResult:
    key = resolve_application_name(name) or _normalize_app_name(name)
    if _matching_windows(key):
        focused = focus_app(key)
        if focused.lower().startswith("error:"):
            return ToolResult("failure", focused)
        return ToolResult("success", f"{key} is already open. {focused}", verification_status="verified")

    browser_target = resolve_target(key) or resolve_target(name)
    if browser_target is not None and browser_target.canonical_url.startswith("http"):
        try:
            from app.tools.browser import open_url

            result = open_url(url=browser_target.canonical_url)
            return result
        except Exception as exc:
            return ToolResult("failure", f"Error: failed to open {browser_target.name}: {exc}")

    if key in config.ALLOWED_APPS:
        exe = _find_executable(config.ALLOWED_APPS[key])
        if exe is not None:
            try:
                subprocess.Popen(
                    [exe],
                    shell=False,
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            except Exception as e:
                return ToolResult("failure", f"Error: failed to launch {key}: {e}")
            if not _wait_for_window(key):
                return ToolResult("failure", f"Started {key}, but could not verify that its window opened.")
            _invalidate_environment_snapshot()
            return ToolResult("success", f"Opened {key}. Verified its window is open.", verification_status="verified")

    if _is_blocked(key):
        return ToolResult("invalid_action", f"Refused: '{name}' is blocked and cannot be opened.")
    shortcut = _find_shortcut(key)
    if shortcut is not None:
        if _is_blocked(shortcut.stem):
            return ToolResult("invalid_action", f"Refused: '{shortcut.stem}' is blocked and cannot be opened.")
        try:
            os.startfile(str(shortcut))
        except Exception as e:
            return ToolResult("failure", f"Error: failed to launch {shortcut.stem}: {e}")
        if not _wait_for_window(shortcut.stem):
            return ToolResult("failure", f"Started {shortcut.stem}, but could not verify that its window opened.")
        _invalidate_environment_snapshot()
        return ToolResult("success", f"Opened {shortcut.stem}. Verified its window is open.", verification_status="verified")

    store_app = _find_store_app(key)
    if store_app is None:
        return ToolResult("clarification_required", f"I could not find an installed app named '{name}'.")
    if _is_blocked(store_app["Name"]):
        return ToolResult("invalid_action", f"Refused: '{store_app['Name']}' is blocked and cannot be opened.")
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{store_app['AppID']}"], shell=False)
    except Exception as e:
        return ToolResult("failure", f"Error: failed to launch {store_app['Name']}: {e}")
    if not _wait_for_window(store_app["Name"]):
        return ToolResult("failure", f"Started {store_app['Name']}, but could not verify that its window opened.")
    _invalidate_environment_snapshot()
    return ToolResult("success", f"Opened {store_app['Name']}. Verified its window is open.", verification_status="verified")


register(Tool(
    name="open_app",
    description="Launch or focus a local Windows application. Use open_app for browser applications themselves (for example, name='edge' means launch Microsoft Edge). Do not use browser_open or open_website_in_application unless the user named a website to navigate to. Verify the app process or window. Retrying is safe because an existing window is checked first.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The app name"}},
        "required": ["name"],
    },
    func=open_app,
    keywords=("open", "launch", "application", "desktop app", "focus window"),
    parallel_safe=True,
    resource="desktop",
    side_effect=True,
    retry_safe=True,
    metadata={"direct_routes": {"open_application": {"name": "$request.target"}}, "offline_summary": "open a named local application"},
))


CLOSE_PROCESS_NAMES = {
    "notepad": ["notepad.exe"],
    "calculator": ["calculatorapp.exe", "calc.exe"],
    "vscode": ["code.exe"],
    "brave": ["brave.exe"],
    "edge": ["msedge.exe"],
}


def _matching_processes(targets: set[str]) -> list[psutil.Process]:
    matches = []
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() in targets:
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


def close_app(name: str) -> ToolResult:
    key = resolve_application_reference(name) or _normalize_app_name(name)
    if key not in CLOSE_PROCESS_NAMES:
        return ToolResult(
            "invalid_action", f"Refused: '{name}' cannot be closed. Closable apps: {', '.join(CLOSE_PROCESS_NAMES)}",
            verification_status="failed",
        )
    targets = set(CLOSE_PROCESS_NAMES[key])
    processes = []
    for proc in _matching_processes(targets):
        try:
            proc.terminate()
            processes.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not processes:
        remaining = _matching_processes(targets)
        if remaining:
            return ToolResult("failure", f"Could not close {key}; matching processes are still running.", verification_status="failed")
        _invalidate_environment_snapshot()
        return ToolResult("success", f"{key.capitalize()} is already closed.", verification_status="verified")

    _gone, alive = psutil.wait_procs(processes, timeout=4)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=3)

    remaining = _matching_processes(targets)
    _invalidate_environment_snapshot()
    if remaining:
        return ToolResult(
            "failure", f"Could not verify {key} closed; {len(remaining)} matching process(es) are still running.",
            verification_status="failed",
        )
    return ToolResult(
        "success", f"Closed {len(processes)} {key} process(es). Verified no matching process remains.",
        verification_status="verified",
    )


register(Tool(
    name="close_app",
    description="Close the named local Windows application and verify its process has exited. Resolve phrases such as 'close that browser' from the current browser/application context, then use the explicit app name (brave or edge). This needs the user's confirmation.",
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
    side_effect=True,
))


register(Tool(
    name="focus_app",
    description="Focus an already open application window by its name or alias. Use when the user asks to switch to or bring a local app forward; verify focus before reporting success.",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    func=focus_app,
    side_effect=True,
    verify=lambda args, _message: bool(get_active_window_info().get("title")) and (
        not args.get("name") or str(args.get("name", "")).lower() in get_active_window_info().get("title", "").lower()
    ),
    retry_safe=True,
))
register(Tool(
    name="get_active_application",
    description="Identify the currently focused Windows application.",
    parameters={"type": "object", "properties": {}},
    func=get_active_application,
))
register(Tool(
    name="get_active_window",
    description="Read the title of the currently focused Windows window.",
    parameters={"type": "object", "properties": {}},
    func=get_active_window,
))
register(Tool(
    name="inspect_windows",
    description="List a short summary of the currently open titled application windows.",
    parameters={"type": "object", "properties": {}},
    func=inspect_windows,
))
register(Tool(
    name="inspect_environment",
    description="Read a fresh snapshot of the live desktop environment, active window, and running apps without inspecting browser tabs or capturing the screen.",
    parameters={"type": "object", "properties": {}},
    func=inspect_environment,
    keywords=("environment state", "desktop state", "current environment", "what is open"),
    capabilities=frozenset({"windows", "browser", "live_state"}),
    metadata={
        "purpose": "Observe the current desktop and browser context",
        "inputs": ["active_window", "open_windows", "browser_pages"],
        "outputs": ["active window summary", "browser page list", "observed_at timestamp"],
        "environment": "desktop",
        "risk": "safe",
        "side_effect": False,
        "verification": "live foreground window and browser session snapshot",
        "failure_conditions": ["window enumeration unavailable", "browser session unavailable"],
    },
))
register(Tool(
    name="observe_environment",
    description="Alias for inspect_environment: read the current desktop and active window without assuming stale context.",
    parameters={"type": "object", "properties": {}},
    func=observe_environment,
    capabilities=frozenset({"windows", "browser", "live_state"}),
))
register(Tool(
    name="get_environment_snapshot",
    description="Alias for inspect_environment: return the latest observed desktop and active window state.",
    parameters={"type": "object", "properties": {}},
    func=get_environment_snapshot,
    capabilities=frozenset({"windows", "browser", "live_state"}),
))
register(Tool(
    name="inspect_application",
    description="Read live state for a named Windows application. Reports separately whether a visible titled window is open and whether any matching application process is still running. Use this to verify whether Brave, Edge, or another app is open or closed; do not infer application state from browser page history or a screenshot.",
    parameters={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    func=inspect_application,
    keywords=("application open", "is application running", "open windows", "currently open"),
    capabilities=frozenset({"windows", "live_state"}),
))
