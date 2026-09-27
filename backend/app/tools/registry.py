import logging
from dataclasses import dataclass
from typing import Callable
from typing import Literal

from app.memory import store as _memory_store
from app.recovery import attempt_recovery, MAX_RECOVERY_ATTEMPTS

log = logging.getLogger("jarvis.tools")

RISK_LEVELS = ("safe", "confirm", "blocked")
ToolStatus = Literal["success", "failure", "authentication_required", "confirmation_required", "clarification_required", "invalid_action"]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    risk: str = "safe"  # "safe" | "confirm" | "blocked"
    needs_confirm: Callable | None = None
    verify: Callable | None = None


@dataclass
class ToolResult:
    status: ToolStatus
    message: str
    data: object | None = None


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    REGISTRY[tool.name] = tool


CORE_TOOL_NAMES = {"remember_fact", "list_memories", "forget_memory", "get_time"}


def get_schemas(relevant_names: set[str] | None = None, include_core: bool = True) -> list[dict]:
    tools = REGISTRY.values()
    if relevant_names is not None:
        tools = [t for t in tools if t.name in relevant_names or (include_core and t.name in CORE_TOOL_NAMES)]
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
        if t.risk != "blocked"
    ]


class NeedsConfirmation(Exception):
    def __init__(self, tool_name: str, tool_args: dict):
        super().__init__(f"{tool_name} needs confirmation")
        self.tool_name = tool_name
        self.tool_args = tool_args


def run_tool(name: str, args: dict, confirmed: bool = False) -> str:
    return run_tool_result(name, args, confirmed).message


def run_tool_result(name: str, args: dict, confirmed: bool = False) -> ToolResult:
    from app.permissions.classify import classify

    tool = REGISTRY.get(name)
    decision, reason = classify(name, args or {})
    log.info("CLASSIFY: %s | TOOL: %s | REASON: %s", decision, name, reason)
    if tool is None:
        log.warning("Model asked for unknown tool: %s", name)
        return ToolResult("invalid_action", f"Error: tool '{name}' does not exist.")
    if decision == "BLOCK":
        return ToolResult("invalid_action", f"Refused: {name} is not permitted ({reason}).")
    if decision == "CONFIRM" and not confirmed:
        raise NeedsConfirmation(name, args or {})
    try:
        log.info("Running tool %s with %s (confirmed=%s)", name, args, confirmed)
        if confirmed:
            log.info("PERMISSION: CONFIRMED | TOOL: %s", name)
        raw_result = tool.func(**(args or {}))
        if isinstance(raw_result, ToolResult):
            result = raw_result
        else:
            result = ToolResult("success", str(raw_result))
        if tool.verify is not None:
            ok = tool.verify(args or {}, result.message)
            log.info("VERIFICATION: %s | TOOL: %s", "PASSED" if ok else "FAILED", name)
            if not ok:
                recovered_result, recovered = attempt_recovery(tool, args or {}, result.message)
                if not recovered:
                    result = ToolResult("failure", f"{recovered_result}\n(Tried {MAX_RECOVERY_ATTEMPTS} times, still not verified. Giving up — please check manually.)")
                else:
                    result = ToolResult("success", recovered_result)
        _memory_store.log_tool_execution(name, args or {}, result.message, confirmed, success=result.status == "success")
        return result
    except Exception as e:
        log.exception("Tool %s failed", name)
        error_result = f"Error: tool '{name}' failed: {e}"
        _memory_store.log_tool_execution(name, args or {}, error_result, confirmed, success=False)
        return ToolResult("failure", error_result)
