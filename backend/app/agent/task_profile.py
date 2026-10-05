"""Provider-independent request capabilities with a deterministic local fallback."""

from dataclasses import dataclass, replace
import logging
from typing import Protocol

from app.agent.privacy import should_keep_local
from app.agent.request import UserRequest
from app.agent.utterance import UtteranceAnalysis, information_tool_names
from app.tools.registry import REGISTRY

log = logging.getLogger("jarvis.agent.task_profile")


@dataclass(frozen=True)
class TaskProfile:
    intent: str
    category: str
    reasoning_level: str
    fresh_information_required: bool
    required_tools: tuple[str, ...]
    available_tools: tuple[str, ...]
    privacy_level: str
    action_risk: str
    multi_step_required: bool
    verification_required: bool
    context_required: bool
    required_capabilities: frozenset[str]
    required_tool_capabilities: frozenset[str] = frozenset()


class SemanticProfileClassifier(Protocol):
    """Optional in-process classifier; no model or preprocessing is bundled."""

    def classify(self, request: UserRequest, signals: TaskProfile) -> TaskProfile | None: ...


def build_task_profile(
    request: UserRequest,
    analysis: UtteranceAnalysis,
    context: dict | None = None,
    *,
    private: bool = False,
    candidate_tool_names: set[str] | None = None,
    classifier: SemanticProfileClassifier | None = None,
) -> TaskProfile:
    """Build a profile from established request and tool metadata, without an LLM call."""
    context = context or {}
    private = bool(private or should_keep_local(request.raw_text))
    candidates = set(candidate_tool_names or ())
    if not candidates and candidate_tool_names is None:
        candidates = set(REGISTRY)
    candidates.intersection_update(REGISTRY)

    explicit_tools = {
        name for name in (request.intent, *(action.intent for action in request.plan))
        if name in REGISTRY
    }
    required_tools = set(explicit_tools)
    if analysis.kind == "information" and not analysis.historical_reference:
        required_tools.update(information_tool_names(request.raw_text) & candidates)
    fresh_signal = (
        (
            analysis.temporal_reference
            and analysis.information_seeking
            and not required_tools
        )
        or (analysis.contextual_information_followup and not required_tools)
        or (
            request.kind == "INFORMATION_REQUEST"
            and analysis.kind == "information"
            and not required_tools
        )
    )
    required_tool_capabilities = {"fresh_information"} if fresh_signal else set()
    required_tool_capabilities.update(
        capability
        for name in required_tools
        for capability in REGISTRY[name].metadata.get("task_capabilities", ())
    )
    fresh = "fresh_information" in required_tool_capabilities
    multi_step = (
        len(request.plan) > 1
        or any(action.depends_on for action in request.plan)
        or request.ordered
        or analysis.kind == "mixed"
    )
    high_risk = any(
        REGISTRY[name].risk in {"confirm", "blocked"}
        for name in required_tools
        if name in REGISTRY
    )
    action_requested = analysis.tool_action
    tools_required = bool(required_tools or required_tool_capabilities or action_requested)
    verification_required = fresh or multi_step or high_risk or bool(required_tools)
    if private:
        category = "local_private"
    elif fresh:
        category = "research_current"
    elif high_risk:
        category = "high_risk_action"
    elif multi_step:
        category = "multi_step_action" if action_requested else "complex_reasoning"
    elif analysis.kind == "conversation":
        category = "conversation"
    else:
        category = "simple"

    reasoning_level = (
        "high" if multi_step else
        "medium" if fresh or high_risk else
        "low" if category in {"conversation", "simple"} else
        "unknown"
    )
    provider_capabilities = {
        capability
        for name in candidates
        if name in REGISTRY
        for capability in REGISTRY[name].metadata.get("provider_capabilities", ())
    } if fresh else {
        capability
        for name in required_tools
        if name in REGISTRY
        for capability in REGISTRY[name].metadata.get("provider_capabilities", ())
    }
    profile = TaskProfile(
        intent=request.intent,
        category=category,
        reasoning_level=reasoning_level,
        fresh_information_required=fresh,
        required_tools=tuple(sorted(required_tools)),
        available_tools=tuple(sorted(candidates)),
        privacy_level="private" if private else "standard",
        action_risk="high" if high_risk else "unknown" if action_requested else "none",
        multi_step_required=multi_step,
        verification_required=verification_required,
        context_required=bool(request.context_references or analysis.refers_to_context),
        required_capabilities=frozenset(
            ({"tool_calling"} if tools_required else set())
            | provider_capabilities
            | ({"reasoning"} if multi_step else set())
            | ({"local_execution"} if private else set())
        ),
        required_tool_capabilities=frozenset(required_tool_capabilities),
    )
    if classifier is None:
        return profile
    try:
        classified = classifier.classify(request, profile)
    except Exception:
        log.exception("Optional task-profile classifier failed; using structured request signals")
        return profile
    if classified is None:
        return profile
    # Optional classification may refine semantic fields, never weaken hard policy
    # or remove a capability established by the deterministic request/tool data.
    return replace(
        classified,
        intent=profile.intent,
        category="local_private" if private else classified.category,
        required_tools=tuple(sorted(set(classified.required_tools) | set(profile.required_tools))),
        available_tools=profile.available_tools,
        privacy_level=profile.privacy_level,
        action_risk=profile.action_risk,
        fresh_information_required=profile.fresh_information_required or classified.fresh_information_required,
        multi_step_required=profile.multi_step_required or classified.multi_step_required,
        verification_required=profile.verification_required or classified.verification_required,
        context_required=profile.context_required or classified.context_required,
        required_capabilities=profile.required_capabilities | classified.required_capabilities,
        required_tool_capabilities=(
            profile.required_tool_capabilities | classified.required_tool_capabilities
        ),
    )


def refine_task_profile(profile: TaskProfile, selected_tools: set[str]) -> TaskProfile:
    """Add requirements revealed by model-selected tools without weakening policy."""
    names = set(profile.required_tools) | (selected_tools & set(REGISTRY))
    task_capabilities = set(profile.required_tool_capabilities)
    provider_capabilities = set(profile.required_capabilities)
    risk = profile.action_risk
    for name in selected_tools & set(REGISTRY):
        tool = REGISTRY[name]
        task_capabilities.update(tool.metadata.get("task_capabilities", ()))
        provider_capabilities.update(tool.metadata.get("provider_capabilities", ()))
        if tool.risk in {"confirm", "blocked"}:
            risk = "high"
    fresh = profile.fresh_information_required or "fresh_information" in task_capabilities
    return replace(
        profile,
        required_tools=tuple(sorted(names)),
        required_tool_capabilities=frozenset(task_capabilities),
        required_capabilities=frozenset(provider_capabilities),
        fresh_information_required=fresh,
        verification_required=profile.verification_required or fresh or risk == "high",
        action_risk=risk,
        category="research_current" if fresh and profile.privacy_level != "private" else profile.category,
    )


def workflow_satisfies_profile(profile: TaskProfile, executed_tools: set[str]) -> bool:
    """Check tool workflow requirements against metadata on successfully run tools."""
    for requirement in profile.required_tool_capabilities:
        if not any(
            requirement in REGISTRY[name].metadata.get("task_capabilities", ())
            for name in executed_tools
            if name in REGISTRY
        ):
            return False
    return True
