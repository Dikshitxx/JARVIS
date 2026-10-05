"""Resolve only high-confidence request intents declared by registered tools."""

import re

from app.agent.request import UserRequest, build_user_request
from app.agent.utterance import relevant_tool_names
from app.tools.registry import REGISTRY
from app.tools.apps import resolve_application_name
from app.tools.browser_targets import resolve_target


def _route_value(value, request: UserRequest, context: dict):
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    source, _, field = value[1:].partition(".")
    if source == "request":
        return getattr(request, field, "")
    if source == "context":
        return context.get(field, "")
    if source == "entity":
        return next((item.value for item in request.entities if item.kind == field), "")
    if source == "modifier":
        prefix = f"{field}="
        return next((item[len(prefix):] for item in request.modifiers if item.startswith(prefix)), "")
    return ""


def _tool_args(bindings: dict, request: UserRequest, context: dict) -> dict:
    arguments = {}
    for name, value in bindings.items():
        resolved = _route_value(value, request, context)
        if resolved not in (None, ""):
            arguments[name] = resolved
    return arguments


def _private_safe(tool) -> bool:
    if (tool.metadata or {}).get("private_safe"):
        return True
    return not (tool.resource in {"browser", "internet"} or tool.capabilities & {"browser", "messaging"})


def try_fast_route(
    user_text: str,
    context: dict | None = None,
    request: UserRequest | None = None,
    *,
    private: bool = False,
) -> tuple[str, dict] | None:
    """Return a registered direct route only for a confident typed intent."""
    context = context or {}
    request = request or build_user_request(user_text, context)
    if request.confidence < 0.8:
        return None
    for tool in REGISTRY.values():
        if private and not _private_safe(tool):
            continue
        routes = (tool.metadata or {}).get("direct_routes", {})
        bindings = routes.get(request.intent)
        if bindings is not None:
            arguments = _tool_args(bindings, request, context)
            references = request.context_references or (
                () if not request.analysis or not request.analysis.refers_to_context else ("context",)
            )
            unresolved = any(
                re.search(r"\b(?:same|another|again|previous|it|that|this|there)\b", str(value), re.I)
                for key, value in arguments.items() if key != "target"
            )
            if references and (unresolved or not any(arguments.values())):
                continue
            return tool.name, arguments

    if request.intent == "information_request" and request.analysis is not None:
        names = relevant_tool_names(
            user_text, request.analysis, context, capabilities=request.capabilities,
        )
        tools = [
            REGISTRY[name] for name in (names or set())
            if name in REGISTRY and REGISTRY[name].metadata.get("direct_information")
            and not (private and not _private_safe(REGISTRY[name]))
            and not (REGISTRY[name].parameters or {}).get("required")
        ]
        if len(tools) == 1:
            return tools[0].name, {}
    return None


def capabilities_response(*, private: bool = False) -> str:
    available = sorted({
        str(tool.metadata["offline_summary"]).strip()
        for tool in REGISTRY.values()
        if tool.metadata.get("offline_summary")
        and (tool.metadata.get("direct_routes") or tool.metadata.get("direct_information"))
        and (not private or _private_safe(tool))
    })
    if not available:
        return "I can handle clear requests that match my registered tools. Broader requests need an available language model."
    return (
        "Without a language model, I can still " + "; ".join(available)
        + ". Broader or ambiguous requests need an available language model. "
        "Protected actions may ask for confirmation, and external services must be available."
    )


def is_fast_route_candidate(user_text: str) -> bool:
    return try_fast_route(user_text) is not None


def _open_target_or_app(value: str) -> tuple[str, dict]:
    """Resolve a target for legacy callers without executing a tool."""
    target = resolve_target(value)
    if target is not None:
        return "browser_open", {"target": target.name}
    application = resolve_application_name(value)
    if application is not None:
        return "open_app", {"name": application}
    return "browser_open", {"target": ""}
