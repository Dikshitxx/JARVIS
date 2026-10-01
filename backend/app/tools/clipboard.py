import time
import uuid

import pyautogui
import pyperclip
from app.tools.registry import Tool, ToolResult, register

def copy_text(text: str) -> ToolResult:
    pyperclip.copy(text)
    copied = pyperclip.paste()
    if copied != text:
        return ToolResult("failure", "Clipboard verification failed after copying text.", verification_status="failed")
    return ToolResult("success", f"Copied and verified {len(text)} characters to the clipboard.", data={"clipboard": text}, verification_status="verified")

def paste_text(target_window: str = "") -> ToolResult:
    from app.tools.desktop_input import _read_text_value, _resolve_and_focus_window

    text = pyperclip.paste()
    if not text:
        return ToolResult("failure", "The clipboard is empty; nothing was pasted.", target=target_window, verification_status="failed")
    window, error = _resolve_and_focus_window(target_window)
    if error:
        status = "clarification_required" if not target_window else "failure"
        return ToolResult(status, error, target=target_window, verification_status="failed")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.25)
    value = _read_text_value(window)
    if value is not None and text in value:
        return ToolResult("success", f"Pasted and verified {len(text)} clipboard characters in {target_window}.", target=target_window, verification_status="verified")
    if value is not None:
        return ToolResult("failure", f"The clipboard text didn't appear in {target_window}.", target=target_window, verification_status="failed")
    return ToolResult("success", f"Sent the clipboard text to {target_window}.", target=target_window, verification_status="unknown")


def read_clipboard() -> ToolResult:
    text = pyperclip.paste()
    return ToolResult("success", text or "The clipboard is empty.", data={"clipboard": text})


def copy_selection(target_window: str = "") -> ToolResult:
    from app.tools.desktop_input import _resolve_and_focus_window

    window, error = _resolve_and_focus_window(target_window)
    if error:
        status = "clarification_required" if not target_window else "failure"
        return ToolResult(status, error, target=target_window, verification_status="failed")
    previous = pyperclip.paste()
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.15)
    text = pyperclip.paste()
    if not text or text == previous:
        return ToolResult("failure", "I couldn't verify that selected text was copied.", target=target_window, verification_status="unknown")
    return ToolResult("success", f"Copied and verified the selected text ({len(text)} characters).", data={"clipboard": text}, target=target_window, verification_status="verified")


def copy_application_text(target_window: str = "") -> ToolResult:
    """Copy the full text value of a named open document/editor window."""
    from app.tools.desktop_input import _read_text_value, _resolve_and_focus_window

    window, error = _resolve_and_focus_window(target_window)
    if error:
        status = "clarification_required" if not target_window else "failure"
        return ToolResult(status, error, target=target_window, verification_status="failed")

    text = _read_text_value(window)
    if text:
        pyperclip.copy(text)
        if pyperclip.paste() == text:
            return ToolResult(
                "success", f"Copied the document text from {target_window} ({len(text)} characters).",
                data={"clipboard": text}, target=target_window, verification_status="verified",
            )

    # Some Notepad/UIA versions don't expose the editor's Value pattern.
    # In that case use the application's normal Select All and Copy commands.
    previous_clipboard = pyperclip.paste()
    sentinel = f"\u2063JARVIS-COPY-CHECK-{uuid.uuid4().hex}"
    pyperclip.copy(sentinel)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.2)
    text = pyperclip.paste()
    if not text or text == sentinel:
        pyperclip.copy(previous_clipboard)
        return ToolResult("failure", f"I couldn't copy document text from {target_window}.", target=target_window, verification_status="failed")
    return ToolResult(
        "success", f"Copied the document text from {target_window} ({len(text)} characters).",
        data={"clipboard": text}, target=target_window, verification_status="verified",
    )

register(Tool(
    name="copy_text",
    description="Copy text to the system clipboard.",
    parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    func=copy_text,
    side_effect=True,
))
register(Tool(
    name="paste_text",
    description="Focus a specified open application window and paste the current clipboard contents there.",
    parameters={"type": "object", "properties": {"target_window": {"type": "string"}}, "required": ["target_window"]},
    func=paste_text,
    side_effect=True,
))
register(Tool(
    name="read_clipboard",
    description="Read the current clipboard text when the user asks to inspect or search for it.",
    parameters={"type": "object", "properties": {}},
    func=read_clipboard,
))
register(Tool(
    name="copy_selection",
    description="Focus a specified open application window and copy its currently selected text.",
    parameters={"type": "object", "properties": {"target_window": {"type": "string"}}, "required": ["target_window"]},
    func=copy_selection,
    side_effect=True,
))
register(Tool(
    name="copy_application_text",
    description="Copy all text from the named open application document to the system clipboard. Use for requests such as copying text from Notepad; this reads the document or selects all and copies it.",
    parameters={"type": "object", "properties": {"target_window": {"type": "string"}}, "required": ["target_window"]},
    func=copy_application_text,
    side_effect=True,
    capabilities=frozenset({"clipboard", "windows"}),
))
