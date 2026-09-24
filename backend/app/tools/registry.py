import logging
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("jarvis.tools")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    risk: str = "safe"  # "safe" | "confirm" | "blocked"


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


def run_tool(name: str, args: dict) -> str:
    tool = REGISTRY.get(name)
    if tool is None:
        log.warning("Model asked for unknown tool: %s", name)
        return f"Error: tool '{name}' does not exist."
    if tool.risk != "safe":
        log.warning("Tool %s needs confirmation (not implemented yet)", name)
        return f"Error: tool '{name}' requires user confirmation, which is not available yet."
    try:
        log.info("Running tool %s with %s", name, args)
        return str(tool.func(**(args or {})))
    except Exception as e:
        log.exception("Tool %s failed", name)
        return f"Error: tool '{name}' failed: {e}"
