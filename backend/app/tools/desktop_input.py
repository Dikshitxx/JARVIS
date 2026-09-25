import pyautogui
from pywinauto import Desktop

from app.tools.registry import Tool, register

pyautogui.FAILSAFE = True  # moving mouse to a screen corner aborts immediately
pyautogui.PAUSE = 0.1

MAX_TEXT_LENGTH = 500

ALLOWED_KEYS = {
    "enter", "tab", "escape", "esc", "space", "backspace", "delete",
    "up", "down", "left", "right", "home", "end", "pageup", "pagedown",
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+a", "ctrl+s",
}


def _focus_window(title_substring: str) -> bool:
    try:
        windows = Desktop(backend="uia").windows()
        for w in windows:
            if title_substring.lower() in w.window_text().lower():
                w.set_focus()
                return True
    except Exception:
        pass
    return False


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


def type_text(text: str, target_window: str = "") -> str:
    if len(text) > MAX_TEXT_LENGTH:
        return f"Refused: text is {len(text)} characters, longer than the {MAX_TEXT_LENGTH} limit."
    if target_window:
        focused = _focus_window(target_window)
        if not focused:
            return f"Error: could not find a window matching '{target_window}'. Nothing was typed."
        import time
        time.sleep(0.3)
    pyautogui.write(text, interval=0.02)
    return f"Typed {len(text)} characters into {target_window or 'the currently focused window'}."


def press_key(key: str) -> str:
    key = key.strip().lower()
    if key not in ALLOWED_KEYS:
        return f"Refused: '{key}' is not an allowed key/combo. Allowed: {', '.join(sorted(ALLOWED_KEYS))}"
    if "+" in key:
        pyautogui.hotkey(*key.split("+"))
    else:
        pyautogui.press(key)
    return f"Pressed {key}."


register(Tool(
    name="move_mouse",
    description="Move the mouse cursor to specific screen coordinates. This needs the user's confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate"},
            "y": {"type": "integer", "description": "Y coordinate"},
        },
        "required": ["x", "y"],
    },
    func=move_mouse,
    risk="confirm",
))

register(Tool(
    name="click_mouse",
    description="Click the mouse at specific screen coordinates. This needs the user's confirmation.",
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
    risk="confirm",
))

register(Tool(
    name="type_text",
    description=f"Type text at the current cursor/focus location, up to {MAX_TEXT_LENGTH} characters. This needs the user's confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to type"},
            "target_window": {"type": "string", "description": "Part of the target window's title, e.g. 'Notepad'. Always provide this so the text goes to the right window."},
        },
        "required": ["text", "target_window"],
    },
    func=type_text,
    risk="confirm",
))

register(Tool(
    name="press_key",
    description="Press a single key or safe key combination (e.g. 'enter', 'ctrl+c'). This needs the user's confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "enum": sorted(ALLOWED_KEYS), "description": "The key or combo to press"}
        },
        "required": ["key"],
    },
    func=press_key,
    risk="confirm",
))