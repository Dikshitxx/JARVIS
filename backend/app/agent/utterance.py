"""Lightweight, context-aware message classification and tool selection."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from app.tools.registry import REGISTRY, names_for_capabilities


_ACTION_VERBS = {
    "open", "launch", "start", "stop", "close", "focus", "search", "find",
    "look", "play", "pause", "resume", "toggle", "send", "type", "write",
    "copy", "paste", "press", "click", "move", "inspect", "check", "read", "text", "message",
    "list", "remember", "save", "forget", "delete", "remove", "ask", "navigate", "greet",
    "tell", "let", "inform", "notify", "use", "switch", "show", "bring", "update",
    "compare", "summarize", "explain", "cite",
}
_VISION_REQUEST_RE = re.compile(r"\b(?:screen|screenshot|see|look\s+at|what\s+does|is\s+this|showing)\b", re.I)
_REFERENCE_WORDS = {
    "it", "that", "this", "one", "another", "again", "also", "then", "instead",
    "actually", "previous", "first", "second", "continue", "same", "more",
}
_CANCEL_RE = re.compile(
    r"\b(?:cancel|abort|never\s+mind|scratch\s+that|forget\s+that|"
    r"(?:cancel|abort|stop)\s+(?:the\s+)?(?:current\s+)?(?:task|request|action|that|it)|"
    r"don't\s+(?:do|continue|send|open|play)|do\s+not\s+(?:do|continue|send|open|play))\b",
    re.IGNORECASE,
)
_AFFIRM_RE = re.compile(r"^\s*(?:yes|yeah|yep|confirm|confirmed|go\s+ahead|do\s+it)\s*[.!]?\s*$", re.I)
_NEGATIVE_RE = re.compile(r"^\s*(?:no|nope|cancel|don't|do\s+not)\s*[.!]?\s*$", re.I)
_SOCIAL_RE = re.compile(
    r"(?:^\s*(?:hi\b|hello\b|hey\b)|good\s+(?:morning|afternoon|evening)\b|"
    r"how\s+(?:are|is|was|were|do)\s+you\b|what\s+do\s+you\s+(?:think|like)\b|"
    r"what\s+can\s+you\s+do\b|tell\s+me\s+a\s+joke\b|(?:haha|hehe|lol)\b|"
    r"i(?:'m| am)\s+(?:tired|bored)\b|(?:let'?s|can\s+we)\s+chat\b|talk\s+with\s+me\b)",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(r"^\s*(?:what|who|why|how|when|where|which|is|are|can|could|would)\b", re.I)
_REQUEST_LEAD_RE = re.compile(r"^\s*(?:please\b|can\s+you\b|could\s+you\b|would\s+you\b|i\s+(?:want|need)\s+you\s+to\b)", re.I)
_TEMPORAL_REFERENCE_RE = re.compile(
    r"\b(?:current(?:ly)?|latest|recent|today|right\s+now|this\s+(?:week|month|year)|"
    r"live|as\s+of\s+now)\b",
    re.I,
)
_SEARCH_ACTIONS = {"search", "find", "look", "check", "inspect"}
_CONTENT_TASKS = {"compare", "summarize", "explain", "cite"}
_CURRENT_REQUEST_LEAD_RE = re.compile(
    r"^\s*(?:current(?:ly)?|latest|recent|today'?s?|live)\b",
    re.I,
)
_HISTORICAL_CONTEXT_RE = re.compile(r"\b(?:history|historical|origins?)\b", re.I)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NON_ENGLISH_ACTION_RE = re.compile(
    r"\b(?:abre|abrir|lanza|inicia|busca|escribe|ouvre|ouvrir|öffne|öffnen|打开|搜索)\b",
    re.I,
)
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "for", "from",
    "get", "give", "how", "i", "in", "is", "it", "me", "my", "of", "on",
    "or", "please", "the", "that", "this", "to", "up", "us", "with", "you",
}


@dataclass(frozen=True)
class UtteranceAnalysis:
    kind: str
    has_action: bool = False
    refers_to_context: bool = False
    cancellation: bool = False
    confirmation: bool = False
    conversational_clause: bool = False
    temporal_reference: bool = False
    information_seeking: bool = False
    tool_action: bool = False
    historical_reference: bool = False
    contextual_information_followup: bool = False


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(text.lower()) if token not in _STOP_WORDS}


def _matching_information_tools(text: str) -> set[str]:
    tokens = _tokens(text)
    matches: set[str] = set()
    for tool in REGISTRY.values():
        if tool.capabilities & {"information", "live_state"}:
            terms = set(_TOKEN_RE.findall(tool.name.replace("_", " ")))
            terms.update(token for phrase in tool.keywords for token in _tokens(phrase))
            if tokens & terms:
                matches.add(tool.name)
    return matches


def information_tool_names(text: str) -> set[str]:
    """Return matching information tools declared in registry metadata."""
    return {
        name for name in _matching_information_tools(text)
        if (
            REGISTRY[name].metadata.get("direct_information")
            or REGISTRY[name].metadata.get("task_capabilities")
        )
    }


def _has_recent_context(context: dict | None) -> bool:
    if not context:
        return False
    pending = context.get("pending_operation") or {}
    if pending.get("status") == "confirmation_required":
        return True
    last_action = context.get("last_action") or {}
    try:
        acted_at = datetime.fromisoformat(last_action.get("at", ""))
        return datetime.now() - acted_at <= timedelta(minutes=30)
    except (TypeError, ValueError):
        return False


def analyze_utterance(text: str, context: dict | None = None, has_pending: bool = False) -> UtteranceAnalysis:
    """Classify the turn without binding it to the previous task by default."""
    cleaned = text.strip()
    lowered = cleaned.lower().replace("’", "'")
    if _CANCEL_RE.search(lowered) or (has_pending and _NEGATIVE_RE.fullmatch(lowered)):
        return UtteranceAnalysis("cancellation", cancellation=True, refers_to_context=True)
    if has_pending and _AFFIRM_RE.fullmatch(lowered):
        return UtteranceAnalysis("confirmation", confirmation=True, refers_to_context=True)

    tokens = _tokens(lowered)
    lexical_reference = bool(tokens & (_REFERENCE_WORDS - {"it", "that", "this"}))
    pronoun_reference = bool(re.search(r"\b(?:it|that|this)\b", lowered))
    has_context = _has_recent_context(context)
    historical_reference = bool(_HISTORICAL_CONTEXT_RE.search(lowered))
    information_tools = (
        set() if historical_reference else information_tool_names(lowered)
    )
    temporal_reference = bool(_TEMPORAL_REFERENCE_RE.search(lowered))
    refers = lexical_reference or (pronoun_reference and not (information_tools and not lexical_reference))
    refers_to_context = refers and has_context
    request_lead = bool(_REQUEST_LEAD_RE.search(lowered))
    has_vision_request = bool(_VISION_REQUEST_RE.search(lowered))
    action_tokens = set(tokens & _ACTION_VERBS)
    if re.match(r"^(?:tell\s+me\s+)?(?:what|who|why|how|when|where|which|is|are|can|could|would)\b", lowered):
        action_tokens.discard("tell")
    if information_tools and re.match(r"^(?:(?:can|could)\s+you\s+)?tell\s+me\s+about\b", lowered):
        action_tokens.discard("tell")
        request_lead = False
    has_action = bool(action_tokens) or request_lead or has_vision_request
    action_count = len(action_tokens)

    social_clause = bool(_SOCIAL_RE.search(lowered))
    contextual_information_followup = (
        _has_recent_information_context(lowered, context) and not social_clause
    )
    if social_clause:
        action_tokens.difference_update({"tell", "let"})
        action_count = len(action_tokens)
        has_action = bool(action_tokens) or has_vision_request
    is_question = bool(_QUESTION_RE.search(lowered))
    information_seeking = (
        is_question
        or bool(action_tokens & _SEARCH_ACTIONS)
        or bool(_CURRENT_REQUEST_LEAD_RE.search(lowered))
        or contextual_information_followup
    )
    fresh_information_signal = temporal_reference and information_seeking and not social_clause
    conversational_question = is_question and not information_tools and not fresh_information_signal
    is_conversation = (social_clause and not has_action) or (
        conversational_question and not has_action and not refers_to_context
    )

    if is_conversation:
        kind = "conversation"
    elif has_action and (social_clause or (is_question and not request_lead) or action_count > 1):
        kind = "mixed"
    elif refers_to_context:
        kind = "follow_up"
    elif has_action:
        kind = "action"
    elif information_tools or fresh_information_signal or contextual_information_followup:
        kind = "information"
    elif _CANCEL_RE.search(lowered):
        kind = "cancellation"
    else:
        kind = "conversation"

    return UtteranceAnalysis(
        kind=kind,
        has_action=has_action,
        refers_to_context=refers_to_context,
        cancellation=kind == "cancellation",
        conversational_clause=social_clause,
        temporal_reference=temporal_reference,
        information_seeking=information_seeking,
        tool_action=(
            bool(action_tokens - _CONTENT_TASKS)
            or (request_lead and not action_tokens)
            or has_vision_request
        ),
        historical_reference=historical_reference,
        contextual_information_followup=contextual_information_followup,
    )


def relevant_tool_names(
    text: str,
    analysis: UtteranceAnalysis,
    context: dict | None = None,
    capabilities: set[str] | frozenset[str] | None = None,
) -> set[str] | None:
    """Use tool metadata to narrow schemas; return None when reasoning is needed."""
    if analysis.kind in {"conversation", "cancellation", "confirmation"}:
        # Preserve model fallback for clear commands in languages the lightweight
        # English intent parser does not understand.
        if analysis.kind == "conversation" and _NON_ENGLISH_ACTION_RE.search(text):
            return None
        return set()
    eligible = names_for_capabilities(capabilities) if capabilities is not None else None
    if analysis.kind == "follow_up":
        return eligible if eligible is not None else None
    if analysis.kind == "mixed":
        return None

    tokens = _tokens(text)
    if "files" in tokens and tokens & {"browser", "webpage", "website"}:
        return names_for_capabilities({"files", "browser"}) | (eligible or set())
    if tokens & {"explain", "summarize", "compare"} and not tokens & _SEARCH_ACTIONS:
        return eligible if eligible is not None else None
    if (
        analysis.temporal_reference and analysis.information_seeking
    ) or analysis.contextual_information_followup:
        direct = information_tool_names(text)
        names = direct
        if not names:
            names = {
                tool.name for tool in REGISTRY.values()
                if "external_research" in tool.metadata.get("task_capabilities", ())
                and tool.risk != "blocked"
            }
        if names:
            from app.tools.registry import expand_tool_dependencies

            return expand_tool_dependencies(names)
        return None
    if analysis.kind == "information":
        names = information_tool_names(text)
        if eligible is not None:
            names &= eligible
        if names:
            from app.tools.registry import expand_tool_dependencies

            return expand_tool_dependencies(names)
        # Unmatched information requests remain model-led. Schema narrowing is
        # an optimization, not a decision that the task needs a particular tool.
        return None

    scores: list[tuple[int, str]] = []
    for tool in REGISTRY.values():
        if eligible is not None and tool.name not in eligible:
            continue
        if tool.risk == "blocked":
            continue
        searchable = set(_TOKEN_RE.findall(tool.name.replace("_", " ").lower()))
        searchable.update(_tokens(tool.description))
        for keyword in tool.keywords:
            searchable.update(_tokens(keyword))
        score = len(tokens & searchable)
        if score:
            scores.append((score, tool.name))

    if not scores:
        names = set(eligible or ())
    else:
        scores.sort(reverse=True)
        best = scores[0][0]
        # Keep ties and close matches; the model resolves which operation fits.
        names = {name for score, name in scores if score >= max(1, best - 1)}
    return names


def _has_recent_information_context(text: str, context: dict | None) -> bool:
    if not context:
        return False
    last_query = str(context.get("last_search_query") or context.get("last_query") or "")
    recent_turns = context.get("recent_turns") or []
    has_prior_search = bool(last_query) or any(
        isinstance(turn, dict) and turn.get("intent") == "information"
        for turn in recent_turns[-3:]
    )
    tokens = _tokens(text)
    return has_prior_search and 0 < len(tokens) <= 3
