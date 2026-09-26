import logging
from dataclasses import dataclass
from typing import Callable

from app.memory import store as _memory_store

log = logging.getLogger("jarvis.tools")

RISK_LEVELS = ("safe", "confirm", "blocked")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    risk: str = "safe"  # "safe" | "confirm" | "blocked"
    needs_confirm: Callable | None = None
    verify: Callable | None = None


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    REGISTRY[tool.name] = tool


def get_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in REGISTRY.values()
        if t.risk != "blocked"
    ]


class NeedsConfirmation(Exception):
    def __init__(self, tool_name: str, tool_args: dict):
        super().__init__(f"{tool_name} needs confirmation")
        self.tool_name = tool_name
        self.tool_args = tool_args


def run_tool(name: str, args: dict, confirmed: bool = False) -> str:
    from app.permissions.classify import classify

    tool = REGISTRY.get(name)
    decision, reason = classify(name, args or {})
    log.info("CLASSIFY: %s | TOOL: %s | REASON: %s", decision, name, reason)
    if tool is None:
        log.warning("Model asked for unknown tool: %s", name)
        return f"Error: tool '{name}' does not exist."
    if decision == "BLOCK":
        return f"Refused: {name} is not permitted ({reason})."
    if decision == "CONFIRM" and not confirmed:
        raise NeedsConfirmation(name, args or {})
    try:
        log.info("Running tool %s with %s (confirmed=%s)", name, args, confirmed)
        if confirmed:
            log.info("PERMISSION: CONFIRMED | TOOL: %s", name)
        result = str(tool.func(**(args or {})))
        if tool.verify is not None:
            ok = tool.verify(args or {}, result)
            log.info("VERIFICATION: %s | TOOL: %s", "PASSED" if ok else "FAILED", name)
        _memory_store.log_tool_execution(name, args or {}, result, confirmed, success=True)
        return result
    except Exception as e:
        log.exception("Tool %s failed", name)
        error_result = f"Error: tool '{name}' failed: {e}"
        _memory_store.log_tool_execution(name, args or {}, error_result, confirmed, success=False)
        return error_result
