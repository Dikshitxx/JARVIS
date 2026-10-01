import time

import pyautogui
import pyperclip
from pywinauto import Desktop

from app.tools.registry import Tool, ToolResult, register

pyautogui.FAILSAFE = True  # moving mouse to a screen corner aborts immediately
pyautogui.PAUSE = 0.1

MAX_TEXT_LENGTH = 500

ALLOWED_KEYS = {
    "enter", "tab", "escape", "esc", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+a", "ctrl+s", "ctrl+f",
    "ctrl+l", "ctrl+p", "ctrl+shift+s", "ctrl+shift+v", "alt+f4", "alt+tab",
}


def _focus_window(title_substring: str) -> bool:
    deadline = time.monotonic() + 5
    while True:
        window, _error = _resolve_and_focus_window(title_substring)
        if window is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def copy_from_window(target_window: str) -> str:
    if not _focus_window(target_window):
        return f"I couldn't focus an open window matching '{target_window}'. Nothing was copied."
    pyautogui.hotkey("ctrl", "a")
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.2)
    return pyperclip.paste()


def _resolve_and_focus_window(target_window: str):
    """Resolve a fresh UIA window and verify foreground focus before input."""
    from app.tools.apps import APP_ALIASES, _process_names, get_active_window_info, resolve_application_name

    target = (target_window or "").strip()
    if not target:
        return None, "Tell me which application window should receive the input."
    try:
        candidates = []
        canonical = resolve_application_name(target)
        process_names = _process_names(canonical) if canonical else set()
        aliases = APP_ALIASES.get(canonical or "", {target.lower()})
        for window in Desktop(backend="uia").windows():
            try:
                title = window.window_text().strip()
                if not title or (hasattr(window, "is_visible") and not window.is_visible()):
                    continue
                if canonical:
                    import psutil

                    process_name = psutil.Process(window.process_id()).name().lower()
                    match = process_name in process_names or any(alias in title.lower() for alias in aliases)
                else:
                    match = target.casefold() in title.casefold()
                if match:
                    candidates.append(window)
            except Exception:
                continue
        if not candidates:
            return None, f"I couldn't find an open window matching '{target}'. Nothing was sent."

        active = get_active_window_info()
        active_handle = active.get("hwnd")
        exact = [window for window in candidates if window.window_text().strip().casefold() == target.casefold()]
        if len(exact) == 1:
            window = exact[0]
        elif len(candidates) == 1:
            window = candidates[0]
        elif active_handle is not None and any(getattr(item, "handle", None) == active_handle for item in candidates):
            window = next(item for item in candidates if getattr(item, "handle", None) == active_handle)
        else:
            return None, f"More than one open window matches '{target}'. Please specify the window title."

        window.set_focus()
        time.sleep(0.15)
        active = get_active_window_info()
        same_handle = active.get("hwnd") is not None and active.get("hwnd") == getattr(window, "handle", None)
        same_process = active.get("pid") is not None and active.get("pid") == window.process_id()
        same_title = bool(active.get("title")) and active["title"].casefold() == window.window_text().strip().casefold()
        if not (same_handle or same_process or same_title):
            return None, f"I couldn't verify focus on '{target}'. Nothing was sent."
        return window, ""
    except Exception as exc:
        return None, f"I couldn't resolve or focus '{target}': {exc}"


def _read_text_value(window):
    """Read text-capable UIA controls when their Value pattern is available."""
    values = []
    try:
        controls = window.descendants()
    except Exception:
        controls = [window]
    for control in controls:
        try:
            if getattr(control.element_info, "control_type", "") not in {"Edit", "Document"}:
                continue
            value = None
            try:
                value = control.iface_value.CurrentValue
            except Exception:
                try:
                    value = control.get_value()
                except Exception:
                    pass
            if value is not None:
                values.append(str(value))
        except Exception:
            continue
    return "\n".join(values) if values else None


def _screen_size():
    return pyautogui.size()


def move_mouse(x: int, y: int) -> str:
    width, height = _screen_size()
    if not (0 <= x < width and 0 <= y < height):
        return f"Refused: coordinates ({x}, {y}) are outside the screen bounds ({width}x{height})."
    pyautogui.moveTo(x, y, duration=0.3)
    return f"Moved mouse to ({x}, {y})."


def click_mouse(x: int, y: int, button: str = "left") -> str:
    width, height = _screen_size()
    if not (0 <= x < width and 0 <= y < height):
        return f"Refused: coordinates ({x}, {y}) are outside the screen bounds ({width}x{height})."
    if button not in {"left", "right", "middle"}:
        return f"Refused: '{button}' is not a valid button. Use left, right, or middle."
    pyautogui.click(x, y, button=button, duration=0.3)
    return f"{button.capitalize()} clicked at ({x}, {y})."


def type_text(text: str, target_window: str = "") -> ToolResult:
    if len(text) > MAX_TEXT_LENGTH:
        return ToolResult("invalid_action", f"Refused: text is {len(text)} characters, longer than the {MAX_TEXT_LENGTH} limit.")
    if not text:
        return ToolResult("invalid_action", "No text was provided.")
    window, error = _resolve_and_focus_window(target_window)
    if error:
        return ToolResult("clarification_required" if not target_window else "failure", error, target=target_window, verification_status="failed")
    previous_clipboard = pyperclip.paste()
    try:
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.25)
        value = _read_text_value(window)
    finally:
        if previous_clipboard != text:
            pyperclip.copy(previous_clipboard)
    if value is not None and text in value:
        return ToolResult("success", f"Typed and verified {len(text)} characters in {target_window}.", target=target_window, verification_status="verified")
    if value is not None:
        return ToolResult("failure", f"The text didn't appear in {target_window} after input.", target=target_window, verification_status="failed")
    return ToolResult("success", f"Sent {len(text)} characters to {target_window}.", target=target_window, verification_status="unknown")


def clear_text(target_window: str = "") -> ToolResult:
    """Clear all editable text in one explicitly named application window."""
    window, error = _resolve_and_focus_window(target_window)
    if error:
        status = "clarification_required" if not target_window else "failure"
        return ToolResult(status, error, target=target_window, verification_status="failed")

    try:
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        time.sleep(0.2)
        value = _read_text_value(window)
        if value is not None:
            if value.strip():
                return ToolResult("failure", f"Text remains in {target_window}; I did not verify that it was cleared.", target=target_window, verification_status="failed")
            return ToolResult("success", f"Cleared and verified the text in {target_window}.", target=target_window, verification_status="verified")

        # Some modern Windows editors expose no UIA Value pattern. Read the
        # selected text through the clipboard as a fallback, restoring the
        # user's clipboard immediately afterward.
        previous_clipboard = pyperclip.paste()
        try:
            pyperclip.copy("")
            pyautogui.hotkey("ctrl", "a")
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.2)
            remaining = pyperclip.paste()
        finally:
            pyperclip.copy(previous_clipboard)
        if remaining:
            return ToolResult("failure", f"Text remains in {target_window}; I did not verify that it was cleared.", target=target_window, verification_status="failed")
        return ToolResult("success", f"Cleared and verified the text in {target_window}.", target=target_window, verification_status="verified")
    except Exception as exc:
        return ToolResult("failure", f"Could not clear text in {target_window}: {exc}", target=target_window, verification_status="failed")


def press_key(key: str) -> ToolResult:
    key = key.strip().lower()
    if key not in ALLOWED_KEYS:
        return ToolResult("invalid_action", f"Refused: '{key}' is not an allowed key/combo. Allowed: {', '.join(sorted(ALLOWED_KEYS))}")
    if "+" in key:
        pyautogui.hotkey(*key.split("+"))
    else:
        pyautogui.press(key)
    return ToolResult("success", f"Pressed {key}.")


register(Tool(
    name="move_mouse",
    description="Move the mouse cursor to specific screen coordinates.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate"},
            "y": {"type": "integer", "description": "Y coordinate"},
        },
        "required": ["x", "y"],
    },
    func=move_mouse,
    side_effect=True,
))

register(Tool(
    name="click_mouse",
    description="Click the mouse at specific screen coordinates.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate"},
            "y": {"type": "integer", "description": "Y coordinate"},
            "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Which mouse button"},
        },
        "required": ["x", "y"],
    },
    func=click_mouse,
    side_effect=True,
))

register(Tool(
    name="type_text",
    description=f"Focus a specific open Windows application window and type text into it, up to {MAX_TEXT_LENGTH} characters. Requires a target window title.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to type"},
            "target_window": {"type": "string", "description": "Part of the target window's title, e.g. 'Notepad'. Always provide this so the text goes to the right window."},
        },
        "required": ["text", "target_window"],
    },
    func=type_text,
    side_effect=True,
))

register(Tool(
    name="press_key",
    description="Press a single key or safe key combination (e.g. 'enter', 'ctrl+c').",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "enum": sorted(ALLOWED_KEYS), "description": "The key or combo to press"}
        },
        "required": ["key"],
    },
    func=press_key,
    side_effect=True,
))

register(Tool(
    name="clear_text",
    description="Select all editable text and clear it in one explicitly named open application window. Use only when the user asks to clear that window's text.",
    parameters={
        "type": "object",
        "properties": {
            "target_window": {"type": "string", "description": "Part of the target window's title, e.g. 'Notepad'. Always provide this so only the intended window is cleared."},
        },
        "required": ["target_window"],
    },
    func=clear_text,
    keywords=("clear text", "clear it", "empty the editor", "delete all text"),
    side_effect=True,
))

register(Tool(
    name="copy_from_window",
    description="Focus a specified open Windows window, select all its text, copy it, and return the clipboard text.",
    parameters={
        "type": "object",
        "properties": {"target_window": {"type": "string"}},
        "required": ["target_window"],
    },
    func=copy_from_window,
    risk="safe",
    keywords=("copy all text", "copy from window", "read window text"),
    side_effect=True,
))
