import logging
import re
import threading
from datetime import datetime
from dataclasses import dataclass, field
from typing import Callable
from typing import Literal

from app.memory import store as _memory_store
from app.recovery import attempt_recovery, MAX_RECOVERY_ATTEMPTS, is_infrastructure_failure, recover_resource

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
    keywords: tuple[str, ...] = ()
    parallel_safe: bool = False
    resource: str = ""
    capabilities: frozenset[str] = frozenset()
    side_effect: bool = False
    timeout_seconds: float | None = None
    retry_safe: bool = False
    metadata: dict = field(default_factory=dict)

    def capability_metadata(self) -> dict:
        tool_metadata = dict(self.metadata or {})
        properties = self.parameters.get("properties", {}) if isinstance(self.parameters, dict) else {}
        inputs = tool_metadata.get("inputs") or sorted(properties.keys())
        if not inputs and isinstance(self.parameters, dict):
            inputs = sorted((self.parameters.get("properties") or {}).keys())
        effective = {
            "name": self.name,
            "description": self.description,
            "purpose": tool_metadata.get("purpose") or self.description,
            "capabilities": sorted(self.capabilities),
            "inputs": list(inputs),
            "outputs": tool_metadata.get("outputs") or ["tool result message", "verification status"],
            "environment": tool_metadata.get("environment") or (self.resource or "local"),
            "requirements": list(tool_metadata.get("requirements") or []),
            "risk": tool_metadata.get("risk") or self.risk,
            "side_effect": bool(tool_metadata.get("side_effect", self.side_effect)),
            "parallel_safe": bool(tool_metadata.get("parallel_safe", self.parallel_safe)),
            "supports_background": bool(tool_metadata.get("supports_background", self.parallel_safe)),
            "verification": tool_metadata.get("verification") or ("tool.verify" if self.verify is not None else "runtime result"),
            "failure_conditions": list(tool_metadata.get("failure_conditions") or ["invalid input", "verification failure", "environment unavailable"]),
        }
        if self.needs_confirm is not None:
            effective["requires_confirmation"] = True
        return effective


@dataclass
class ToolResult:
    status: ToolStatus
    message: str
    data: object | None = None
    action: str = ""
    target: str = ""
    verification_status: Literal["verified", "failed", "unknown"] = "unknown"
    error: str = ""

    def __post_init__(self) -> None:
        if self.status in {"failure", "invalid_action"} and not self.error:
            self.error = self.message

    @property
    def execution_state(self) -> str:
        if self.status in {"confirmation_required", "clarification_required"}:
            return "requested"
        if self.status in {"failure", "invalid_action"}:
            return "failed"
        if self.status == "authentication_required":
            return "blocked"
        if self.status == "success":
            return "executed" if self.verification_status != "verified" else "verified"
        return "attempted"

    @property
    def verification_state(self) -> str:
        if self.verification_status == "verified":
            return "verified"
        if self.verification_status == "failed":
            return "failed"
        if self.status == "success":
            return "unverified"
        return "unknown"

    @property
    def is_verified(self) -> bool:
        return self.verification_status == "verified"

    @property
    def final_outcome(self) -> str:
        if self.status in {"failure", "invalid_action"}:
            return "FAILED"
        if self.status == "success" and self.verification_status == "verified":
            return "SUCCEEDED"
        if self.status == "success":
            return "UNVERIFIED"
        return str(self.status).upper()


REGISTRY: dict[str, Tool] = {}
_RESOURCE_LOCKS: dict[str, threading.RLock] = {}
_RESOURCE_LOCKS_GUARD = threading.Lock()

_MODULE_CAPABILITIES = {
    "basic": frozenset({"information"}),
    "apps": frozenset({"windows"}),
    "desktop_input": frozenset({"windows"}),
    "screen": frozenset({"windows"}),
    "clipboard": frozenset({"clipboard"}),
    "whatsapp": frozenset({"messaging"}),
    "whatsapp_adapter": frozenset({"messaging"}),
    "memory_tools": frozenset({"memory"}),
    "people_tools": frozenset({"memory"}),
    "files": frozenset({"files"}),
    "projects": frozenset({"projects"}),
    "terminal": frozenset({"system"}),
}
_MODULE_RESOURCES = {
    "apps": "desktop",
    "desktop_input": "desktop",
    "clipboard": "desktop",
    "browser": "browser",
    "whatsapp": "browser",
    "whatsapp_adapter": "browser",
    "projects": "projects",
    "files": "filesystem",
}


def register(tool: Tool) -> None:
    if not tool.capabilities:
        module_name = getattr(tool.func, "__module__", "").rsplit(".", 1)[-1]
        tool.capabilities = _MODULE_CAPABILITIES.get(module_name, frozenset())
    if not tool.resource:
        module_name = getattr(tool.func, "__module__", "").rsplit(".", 1)[-1]
        tool.resource = _MODULE_RESOURCES.get(module_name, "")
    REGISTRY[tool.name] = tool


CORE_TOOL_NAMES = {"remember_fact", "list_memories", "forget_memory", "get_time"}


def get_schemas(
    relevant_names: set[str] | None = None,
    include_core: bool = False,
    capabilities: set[str] | frozenset[str] | None = None,
) -> list[dict]:
    tools = REGISTRY.values()
    if relevant_names is not None:
        tools = [t for t in tools if t.name in relevant_names or (include_core and t.name in CORE_TOOL_NAMES)]
    if capabilities is not None:
        allowed = set(capabilities)
        tools = [t for t in tools if t.capabilities & allowed]
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in tools
        if t.risk != "blocked"
    ]


def names_for_capabilities(capabilities: set[str] | frozenset[str]) -> set[str]:
    allowed = set(capabilities)
    return {tool.name for tool in REGISTRY.values() if tool.capabilities & allowed and tool.risk != "blocked"}


def get_capability_catalog(
    relevant_names: set[str] | None = None,
    capabilities: set[str] | frozenset[str] | None = None,
    include_core: bool = False,
) -> list[dict]:
    tools = list(REGISTRY.values())
    if relevant_names is not None:
        tools = [tool for tool in tools if tool.name in relevant_names or (include_core and tool.name in CORE_TOOL_NAMES)]
    if capabilities is not None:
        allowed = set(capabilities)
        tools = [tool for tool in tools if tool.capabilities & allowed]
    return [tool.capability_metadata() for tool in tools if tool.risk != "blocked"]


class NeedsConfirmation(Exception):
    def __init__(self, tool_name: str, tool_args: dict):
        super().__init__(f"{tool_name} needs confirmation")
        self.tool_name = tool_name
        self.tool_args = tool_args


def run_tool(name: str, args: dict, confirmed: bool = False) -> str:
    return run_tool_result(name, args, confirmed).message


def run_tool_result(name: str, args: dict, confirmed: bool = False) -> ToolResult:
    tool = REGISTRY.get(name)
    if tool is not None and tool.resource:
        with _RESOURCE_LOCKS_GUARD:
            lock = _RESOURCE_LOCKS.setdefault(tool.resource, threading.RLock())
        with lock:
            result = _run_tool_result_locked(name, args, confirmed)
    else:
        result = _run_tool_result_locked(name, args, confirmed)

    try:
        from app.tasks import append_step, current_task_id, update_task

        task_id = current_task_id()
        if task_id:
            capability = ",".join(sorted(tool.capabilities)) if tool else ""
            append_step(
                task_id, tool_name=name, capability=capability, arguments=args or {},
                status=result.status, result=_safe_result(name, result.message),
                verification=result.verification_status, started_at=getattr(result, "started_at", None),
                side_effect=bool(tool and tool.side_effect),
            )
            update_task(task_id, current_step=f"{name}: {result.status}")
    except Exception:
        log.exception("Could not persist task step for %s", name)
    return result


def _safe_arguments(args: dict) -> dict:
    safe = {}
    for key, value in (args or {}).items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("password", "secret", "token", "cookie", "authorization")):
            safe[key] = "[redacted]"
        elif lowered in {"message", "text", "content"}:
            safe[key] = f"[redacted; {len(str(value))} characters]"
        else:
            safe[key] = str(value)[:300]
    return safe


_CONTENT_TOOLS = {
    "read_clipboard", "copy_selection", "copy_application_text", "copy_from_window", "read_text_file",
    "send_whatsapp_message", "type_text", "browser_type_text", "copy_text",
}


def _safe_result(name: str, message: str) -> str:
    return "[content omitted]" if name in _CONTENT_TOOLS else message


def _run_tool_result_locked(name: str, args: dict, confirmed: bool = False) -> ToolResult:
    from app.permissions.classify import classify
    started_at = datetime.now().isoformat(timespec="seconds")

    tool = REGISTRY.get(name)
    if tool is None:
        log.warning("Model asked for unknown tool: %s", name)
        return ToolResult("invalid_action", f"Error: tool '{name}' does not exist.", action=name, verification_status="failed")
    properties = (tool.parameters or {}).get("properties") or {}
    provided_args = args or {}
    unexpected = set(provided_args) - set(properties)
    if unexpected:
        log.warning("Ignoring unsupported arguments for tool %s: %s", name, sorted(unexpected))
        provided_args = {key: value for key, value in provided_args.items() if key in properties}
    decision, reason = classify(name, provided_args)
    log.info("CLASSIFY: %s | TOOL: %s | REASON: %s", decision, name, reason)
    if decision == "BLOCK":
        return ToolResult("invalid_action", f"Refused: {name} is not permitted ({reason}).", action=name, verification_status="failed")
    if decision == "CONFIRM" and not confirmed:
        raise NeedsConfirmation(name, provided_args)
    try:
        from app.tasks import cancellation_requested

        if cancellation_requested():
            return ToolResult("failure", "Cancelled before this operation started.", action=name, verification_status="failed")
        safe_args = _safe_arguments(provided_args)
        log.info("Running tool %s with %s (confirmed=%s)", name, safe_args, confirmed)
        if confirmed:
            log.info("PERMISSION: CONFIRMED | TOOL: %s", name)
        def invoke_tool() -> ToolResult:
            try:
                raw_result = tool.func(**provided_args)
            except Exception as exc:
                return ToolResult(
                    "failure", f"Error: tool '{name}' failed: {exc}", action=name,
                    target=str(provided_args.get("target") or provided_args.get("name") or ""),
                    verification_status="failed",
                )
            if isinstance(raw_result, ToolResult):
                result_value = raw_result
            else:
                message = str(raw_result)
                lowered = message.strip().lower()
                if re.match(r"^(?:error|failed|failure|refused|unsupported)(?:\b|:)", lowered):
                    status = "failure"
                elif lowered.startswith(("i don't recognize", "i could not find", "i couldn't find", "i can't", "that's not something")):
                    status = "clarification_required"
                elif lowered.startswith(("could not", "couldn't", "unable to", "not found", "is not running", "no tracked", "no usable")):
                    status = "failure"
                else:
                    status = "success"
                result_value = ToolResult(status, message)
            if not result_value.action:
                result_value.action = name
            if not result_value.target:
                result_value.target = str(
                    provided_args.get("target_window") or provided_args.get("target")
                    or provided_args.get("name") or provided_args.get("query") or ""
                )
            return result_value

        result = invoke_tool()
        if tool.retry_safe and result.status != "success" and is_infrastructure_failure(result.message):
            recover_resource(tool.resource)
            log.info("TOOL_RETRY tool=%s reason=infrastructure attempt=1", name)
            result = invoke_tool()
            if result.status == "success":
                result.verification_status = "verified"
                log.info("TOOL_RECOVERY_SUCCEEDED tool=%s", name)

        if tool.verify is not None:
            ok = tool.verify(provided_args, result.message)
            log.info("VERIFICATION: %s | TOOL: %s", "PASSED" if ok else "FAILED", name)
            if not ok:
                if not tool.retry_safe:
                    recovered_result, recovered = result.message, False
                    retry_message = "Verification failed; I did not retry because repeating this operation may cause a duplicate effect."
                else:
                    recovered_result, recovered = attempt_recovery(tool, provided_args, result.message)
                    retry_message = f"Tried {MAX_RECOVERY_ATTEMPTS} safe retries without verification."
                if not recovered:
                    result = ToolResult("failure", f"{recovered_result}\n({retry_message} Please check manually.)", action=name, target=result.target, verification_status="failed")
                else:
                    result = ToolResult("success", recovered_result, action=name, target=result.target, verification_status="verified")
            else:
                result.verification_status = "verified"
        if tool.side_effect and result.status == "success" and result.verification_status == "unknown":
            result.message = f"{result.message} I couldn't verify that it took effect."
        _memory_store.log_tool_execution(name, safe_args, _safe_result(name, result.message), confirmed, success=result.status == "success")
        result.started_at = started_at
        return result
    except Exception as e:
        log.exception("Tool %s failed", name)
        error_result = f"Error: tool '{name}' failed: {e}"
        _memory_store.log_tool_execution(name, _safe_arguments(provided_args), error_result, confirmed, success=False)
        target = str(provided_args.get("target_window") or provided_args.get("target") or provided_args.get("name") or "")
        result = ToolResult("failure", error_result, action=name, target=target, verification_status="failed")
        result.started_at = started_at
        return result
