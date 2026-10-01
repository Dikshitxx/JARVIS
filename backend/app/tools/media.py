from typing import Literal

import pyautogui

from app.tools.registry import Tool, ToolResult, register


_MEDIA_KEYS = {
    "play_pause": "playpause",
    "next": "nexttrack",
    "previous": "prevtrack",
    "volume_up": "volumeup",
    "volume_down": "volumedown",
    "mute": "volumemute",
}
MediaAction = Literal["play_pause", "next", "previous", "volume_up", "volume_down", "mute"]


def media_control(action: MediaAction) -> ToolResult:
    action = action.strip().lower()
    key = _MEDIA_KEYS.get(action)
    if key is None:
        return ToolResult("invalid_action", f"Unsupported media action '{action}'.")
    try:
        pyautogui.press(key)
    except Exception as exc:
        return ToolResult("failure", f"Could not send the system media key: {exc}", action="media_control", verification_status="failed")
    return ToolResult(
        "success", f"Sent the system media {action.replace('_', ' ')} command.",
        action="media_control", verification_status="unknown",
    )


register(Tool(
    name="media_control",
    description="Send a system-wide media key for play/pause, next, previous, volume, or mute. Windows delivers the key to whichever media session is active; this tool cannot target a named app and cannot verify the resulting playback state. Use control_media for a tracked JARVIS YouTube video, and never claim that a particular browser or player changed unless separately verified.",
    parameters={
        "type": "object",
        "properties": {"action": {"type": "string", "enum": list(_MEDIA_KEYS)}},
        "required": ["action"],
    },
    func=media_control,
    risk="safe",
    keywords=("pause", "play", "stop", "skip", "next track", "previous track", "volume", "mute"),
    capabilities=frozenset({"media"}),
    side_effect=True,
))
