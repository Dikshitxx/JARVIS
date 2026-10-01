"""Convert a user utterance into a small, typed request before tool routing."""

from dataclasses import dataclass, replace
import re
import unicodedata

from app.agent.utterance import UtteranceAnalysis, analyze_utterance
from app.tools.apps import resolve_application_name
from app.tools.browser_targets import parse_browser_intent, resolve_target


@dataclass(frozen=True)
class Entity:
    kind: str
    value: str


@dataclass(frozen=True)
class PlannedAction:
    intent: str
    capability: str
    target: str = ""
    target_type: str = ""
    query: str = ""
    modifiers: tuple[str, ...] = ()
    depends_on: tuple[int, ...] = ()


@dataclass(frozen=True)
class Objective:
    desired_outcome: str = ""
    entities: tuple[Entity, ...] = ()
    target: str = ""
    target_type: str = ""
    query: str = ""
    constraints: tuple[str, ...] = ()
    context_references: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    ambiguity: str = ""
    needs_clarification: bool = False
    confidence: float = 0.0

    def prompt_data(self) -> dict:
        return {
            "desired_outcome": self.desired_outcome or None,
            "entities": [{"kind": item.kind, "value": item.value} for item in self.entities],
            "target": self.target or None,
            "target_type": self.target_type or None,
            "query": self.query or None,
            "constraints": list(self.constraints),
            "context_references": list(self.context_references),
            "required_capabilities": list(self.required_capabilities),
            "ambiguity": self.ambiguity or None,
            "needs_clarification": self.needs_clarification,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class UserRequest:
    raw_text: str
    normalized_text: str
    kind: str
    intent: str
    entities: tuple[Entity, ...]
    target: str = ""
    target_type: str = ""
    query: str = ""
    modifiers: tuple[str, ...] = ()
    context_references: tuple[str, ...] = ()
    confidence: float = 0.0
    capabilities: frozenset[str] = frozenset()
    plan: tuple[PlannedAction, ...] = ()
    ordered: bool = False
    analysis: UtteranceAnalysis | None = None
    objective: Objective | None = None

    def prompt_data(self) -> dict:
        """Return a compact, JSON-friendly representation for the local model."""
        data = {
            "kind": self.kind,
            "intent": self.intent,
            "entities": [{"kind": item.kind, "value": item.value} for item in self.entities],
            "target": self.target or None,
            "target_type": self.target_type or None,
            "query": self.query or None,
            "modifiers": list(self.modifiers),
            "context_references": list(self.context_references),
            "capabilities": sorted(self.capabilities),
            "plan": [
                {
                    "intent": item.intent,
                    "capability": item.capability,
                    "target": item.target or None,
                    "target_type": item.target_type or None,
                    "query": item.query or None,
                    "modifiers": list(item.modifiers),
                    "depends_on": list(item.depends_on),
                }
                for item in self.plan
            ],
        }
        if self.objective is not None:
            data["objective"] = self.objective.prompt_data()
        return data


_LEADING_POLITENESS = re.compile(
    r"^(?:(?:hey\s+jarvis)[,\s]+)?(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)+",
    re.I,
)
_TRAILING_POLITENESS = re.compile(r"(?:\s+(?:for\s+me|please|now|thanks|thank\s+you))+$", re.I)
_REFERENCE_RE = re.compile(
    r"\b(it|that|this|another|again|also|then|instead|actually|previous|first|second|continue|same|more)\b",
    re.I,
)
_OPEN_RE = re.compile(
    r"^(?:open|launch|start|go\s+to|navigate\s+to|take\s+me\s+to|bring\s+up|show\s+me|visit|head\s+to|check\s+out)\s+(.+)$",
    re.I,
)
_OPEN_PROJECT_RE = re.compile(
    r"^(?:open|launch|start)\s+(.+?)\s+(?:in|on|with|using)\s+(?:vs\s*code|visual\s+studio\s+code|vscode)$",
    re.I,
)
_PLAY_RE = re.compile(r"^(?:play|put\s+on)\s+(.+)$", re.I)
_CONTROL_RE = re.compile(r"^(pause|resume|stop|continue)\s+(.+)$", re.I)
_TYPE_RE = re.compile(r"^(?:type|write|enter)\s+(.+)$", re.I)
_APP_SEARCH_SUFFIX_RE = re.compile(
    r"^(?:search|find|look\s+up)\s+(?:for\s+)?(.+?)\s+(?:in|on|using)\s+(brave(?:\s+browser)?|chrome|google\s+chrome|edge|microsoft\s+edge)$",
    re.I,
)
_WEB_SEARCH_RE = re.compile(
    r"^(?:search|look\s+up)\s+(?:(?:the\s+web|online|the\s+internet)\s+for\s+)?(?:for\s+)?(.+)$",
    re.I,
)
_LIST_LOCAL_ROOT_RE = re.compile(
    r"^(?:list|show)\s+(?:what(?:'s|\s+is)\s+)?(?:the\s+)?(?:files?\s+)?"
    r"(?:on|in|from)\s+(?:my\s+)?(desktop|documents|downloads)$|"
    r"^what(?:'s|\s+is)\s+on\s+(?:my\s+)?(desktop|documents|downloads)$",
    re.I,
)
_LIST_EXPLICIT_PATH_RE = re.compile(
    r"^(?:list|show)\s+(?:the\s+)?(?:files|contents)\s+"
    r"(?:in|under|inside|at|from)\s+(.+)$",
    re.I,
)
_FIND_LOCAL_FILE_RE = re.compile(
    r"^(?:search|find|look\s+up|check|locate)\s+(?:for\s+)?(.+?)\s+"
    r"(?:in|under|on)\s+(?:my\s+)?(files|device|computer|pc|desktop|documents|downloads)$",
    re.I,
)
_NEWS_REQUEST_RE = re.compile(
    r"^(?:(?:tell|show|give)\s+me\s+|what(?:'s|\s+is)\s+)?"
    r"(?:the\s+)?(?:(?:latest|recent|current|today'?s?)\s+)?news"
    r"(?:\s+(?:about|on)\s+(.+?))?(?:\s+(?:today|now|right\s+now))?$",
    re.I,
)
_COPY_APPLICATION_TEXT_RE = re.compile(
    r"^(?:copy|read)\s+(?:all\s+)?(?:the\s+)?(?:text|contents?)\s+(?:written\s+)?(?:in|from)\s+(.+)$",
    re.I,
)
_MESSAGE_WITH_DELIMITER_RE = re.compile(
    r"^(?:text|message|send\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to)\s+(.+?)\s+(?:saying|that\s+says|to\s+say)\s+(.+)$",
    re.I,
)
_MESSAGE_SIMPLE_RE = re.compile(r"^(?:text|message)\s+(\S+)\s+(.+)$", re.I)
_MEDIA_STATE_REFERENCE_RE = re.compile(r"\b(?:current(?:ly)?|paused|playing)\b", re.I)
_MEDIA_REPLAY_REFERENCE_RE = re.compile(r"\b(?:again|same|previous|last)\b", re.I)
_LIVE_MEDIA_QUESTION_RE = re.compile(
    r"\b(?:what|which|is|tell\s+me)\b.*\b(?:song|track|video|media|music)\b.*\b(?:playing|paused|current)\b|"
    r"\b(?:currently\s+playing|now\s+playing)\b",
    re.I,
)
_LIVE_APP_QUESTION_RE = re.compile(
    r"^(?:is|are)\s+(?:the\s+)?(.+?)\s+(?:currently\s+)?(?:open|running)(?:\s+right\s+now)?$|"
    r"^(?:check\s+)?(?:whether|if)\s+(.+?)\s+is\s+(?:currently\s+)?(?:open|running)$",
    re.I,
)
_LIVE_BROWSER_QUESTION_RE = re.compile(
    r"\b(?:what|which)\s+(?:web\s+)?(?:page|website|site)\b.*\b(?:am\s+i\s+on|active|currently|open|loaded)\b|"
    r"\bwhat\s+is\s+(?:the\s+)?(?:current|active)\s+(?:web\s+)?(?:page|website|site)\b|"
    r"\bcurrent(?:ly)?\s+(?:web\s+)?(?:page|website|site)\b",
    re.I,
)
_VISUAL_REQUEST_RE = re.compile(
    r"\b(?:screen|screenshot)\b|"
    r"\b(?:look\s+at|see)\s+(?:this|that|the)\s+(?:image|picture|photo|screen)\b|"
    r"\bwhat\s+does\s+(?:this|that|the)\s+(?:image|picture|photo|screen)\b|"
    r"\bshowing\b.{0,40}\b(?:screen|image|picture|photo|page)\b",
    re.I,
)
_MEDIA_NOUN = re.compile(r"\s+(?:song|track|video|music)\s*$", re.I)
_TARGET_SUFFIXES = re.compile(r"\s+(?:in|using)\s+(brave(?:\s+browser)?|chrome|google\s+chrome|edge|microsoft\s+edge)$", re.I)
_MIXED_SPLIT_RE = re.compile(r"\s+(and\s+then|then|and)\s+", re.I)
_ACTION_LEAD_RE = re.compile(
    r"^(?:open|launch|start|go\s+to|navigate\s+to|take\s+me\s+to|bring\s+up|show\s+me|visit|head\s+to|"
    r"search|find|look\s+up|play|put\s+on|pause|resume|stop|continue|type|write|enter|copy|paste|send|text|"
    r"message|tell|let|ask|inform|notify|remember|save|delete|remove|close|focus|inspect|check|list|use|switch|show|bring|update)\b",
    re.I,
)
_CONTEXTUAL_SWITCH_RE = re.compile(
    r"^(?:actually\s+)?(?:use|switch\s+to|go\s+to)\s+(.+?)(?:\s+(?:instead|instead\s+of|now))?$",
    re.I,
)
_COMMUNICATION_RE = re.compile(
    r"^(?:let|tell|ask|inform|notify|email|mail)\s+(?P<contact>.+?)(?:\s+(?:know|that|to\s+say|saying|about)\s+|\s+)(?P<message>.+)$",
    re.I,
)
_EMAIL_MESSAGE_RE = re.compile(
    r"^(?:email|mail|send\s+(?:an?\s+)?(?:email|mail))\s+(?P<contact>.+?)(?:\s+(?:saying|that\s+says|to\s+say|about)\s+|\s+)(?P<message>.+)$",
    re.I,
)
_NOTEPAD_TYPE_CLEAR_RE = re.compile(
    r"^(?:open|launch|start)\s+(?:the\s+)?notepad\s*,?\s*(?:and\s+)?(?:then\s+)?"
    r"(?:type|write|enter)\s+(.+?)\s*,?\s+then\s+clear\s+"
    r"(?:it|the\s+text|the\s+contents?)$",
    re.I,
)


def normalize_user_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "").replace("’", "'").replace("‘", "'")
    value = re.sub(r"\s+", " ", value).strip()
    value = _LEADING_POLITENESS.sub("", value)
    value = re.sub(r"[?!]+$", "", value).strip()
    if value.endswith(".") and not re.search(r"\b\d+\.\d+\.$", value):
        value = value[:-1]
    return value.strip()


def _classification_name(analysis: UtteranceAnalysis) -> str:
    if analysis.kind == "conversation":
        return "CHAT"
    if analysis.kind == "information":
        return "INFORMATION_REQUEST"
    if analysis.kind == "action":
        return "ACTION"
    if analysis.kind == "follow_up":
        return "FOLLOW_UP"
    if analysis.kind == "mixed":
        return "MIXED_REQUEST"
    if analysis.kind == "cancellation":
        return "CANCELLATION"
    if analysis.kind == "confirmation":
        return "CONFIRMATION"
    return "CHAT"


def _open_entity(value: str) -> tuple[str, str, str, str]:
    """Resolve the longest known target prefix, leaving polite trailing words out."""
    value = value.strip().strip("'\"`.,!? ")
    browser = ""
    browser_match = _TARGET_SUFFIXES.search(value)
    if browser_match:
        candidate_browser = resolve_application_name(browser_match.group(1))
        if candidate_browser in {"brave", "chrome", "edge"}:
            browser = candidate_browser
            value = value[:browser_match.start()].strip()

    value = _TRAILING_POLITENESS.sub("", value).strip()
    words = value.split()
    app_candidates: list[tuple[str, str]] = []
    website_candidates: list[tuple[str, str]] = []
    for end in range(len(words), 0, -1):
        candidate = " ".join(words[:end]).strip("'\"`.,!? ")
        target = resolve_target(candidate)
        if target is not None:
            website_candidates.append((target.name, value))
        application = resolve_application_name(candidate)
        if application:
            app_candidates.append((application, value))

    if app_candidates:
        return app_candidates[0][0], "application", browser, value
    if website_candidates:
        return website_candidates[0][0], "website", browser, value

    # Unknown site names are not passed through as executable tool targets.
    # A URL is accepted by resolve_target above; other names need clarification.
    return "", "", browser, value


def _media_query(value: str) -> str:
    query = value.strip().strip("'\"`.,!? ")
    query = re.sub(r"^(?:the|a|an|some)\s+", "", query, flags=re.I)
    query = re.sub(r"\s+(?:on|in)\s+(?:the\s+)?(?:youtube|you\s*tube|youtu\s*be)\s*$", "", query, flags=re.I)
    query = _MEDIA_NOUN.sub("", query).strip()
    if re.fullmatch(r"(?:song|track|video|music|one|it|that|this|again|same|previous|last)", query, re.I):
        return ""
    return query.strip()


def _base(
    raw: str,
    normalized: str,
    analysis: UtteranceAnalysis,
    *,
    kind: str | None = None,
    intent: str = "none",
    entities: tuple[Entity, ...] = (),
    target: str = "",
    target_type: str = "",
    query: str = "",
    modifiers: tuple[str, ...] = (),
    capabilities: frozenset[str] = frozenset(),
    plan: tuple[PlannedAction, ...] = (),
    ordered: bool = False,
    analysis_override: UtteranceAnalysis | None = None,
    objective: Objective | None = None,
) -> UserRequest:
    refs = tuple(dict.fromkeys(match.group(1).lower() for match in _REFERENCE_RE.finditer(normalized)))
    confidence = 0.92 if intent not in {"none", "open_target"} and capabilities else 0.45
    if objective is None:
        objective = Objective(
            desired_outcome=intent if intent not in {"none", "open_target"} else "understand request",
            entities=entities,
            target=target,
            target_type=target_type,
            query=query,
            context_references=refs,
            required_capabilities=tuple(sorted(capabilities)),
            confidence=confidence,
        )
    return UserRequest(
        raw_text=raw,
        normalized_text=normalized,
        kind=kind or _classification_name(analysis),
        intent=intent,
        entities=entities,
        target=target,
        target_type=target_type,
        query=query,
        modifiers=modifiers,
        context_references=refs,
        confidence=confidence,
        capabilities=capabilities,
        plan=plan,
        ordered=ordered,
        analysis=analysis_override or analysis,
        objective=objective,
    )


def _parse_one(
    raw: str,
    context: dict,
    allow_mixed: bool,
    analysis_override: UtteranceAnalysis | None = None,
) -> UserRequest:
    normalized = normalize_user_text(raw)
    analysis = analysis_override or analyze_utterance(raw, context)

    text_clear = _NOTEPAD_TYPE_CLEAR_RE.fullmatch(normalized)
    if text_clear:
        text = text_clear.group(1).strip().strip("'\"` ")
        if text:
            plan = (
                PlannedAction("open_application", "windows", target="notepad", target_type="application", modifiers=("workflow=notepad_type_clear",)),
                PlannedAction("type_text", "windows", target="notepad", target_type="application", query=text, modifiers=("workflow=notepad_type_clear",), depends_on=(0,)),
                PlannedAction("clear_text", "windows", target="notepad", target_type="application", modifiers=("workflow=notepad_type_clear",), depends_on=(1,)),
            )
            return _base(
                raw, normalized, analysis, kind="MIXED_REQUEST", intent="execute_plan",
                entities=(Entity("application", "notepad"), Entity("text", text)),
                target="notepad", target_type="application", query=text,
                capabilities=frozenset({"windows"}), plan=plan, ordered=True,
            )

    if _VISUAL_REQUEST_RE.search(normalized):
        return _base(
            raw, normalized, analysis, intent="look_at_screen",
            entities=(Entity("visual_question", normalized),), query=normalized,
            capabilities=frozenset({"windows"}),
        )

    if _LIVE_MEDIA_QUESTION_RE.search(normalized):
        info_analysis = replace(analysis, kind="information", has_action=False, refers_to_context=False)
        return _base(
            raw, normalized, analysis, kind="INFORMATION_REQUEST", intent="inspect_current_media",
            entities=(Entity("media_state", "current"),), capabilities=frozenset({"media"}),
            analysis_override=info_analysis,
        )

    if _LIVE_APP_QUESTION_RE.search(normalized):
        match = _LIVE_APP_QUESTION_RE.search(normalized)
        raw_name = next((value for value in match.groups() if value), "").strip()
        application = resolve_application_name(raw_name) or raw_name
        info_analysis = replace(analysis, kind="information", has_action=False, refers_to_context=False)
        return _base(
            raw, normalized, analysis, kind="INFORMATION_REQUEST", intent="inspect_application",
            entities=(Entity("application", application), Entity("application_state", "open")),
            target=application, target_type="application", capabilities=frozenset({"windows"}),
            analysis_override=info_analysis,
        )

    if _LIVE_BROWSER_QUESTION_RE.search(normalized):
        info_analysis = replace(analysis, kind="information", has_action=False, refers_to_context=False)
        return _base(
            raw, normalized, analysis, kind="INFORMATION_REQUEST", intent="inspect_current_page",
            entities=(Entity("browser_state", "visible_page"),), capabilities=frozenset({"browser"}),
            analysis_override=info_analysis,
        )

    if analysis.cancellation:
        return _base(raw, normalized, analysis, intent="cancel_pending")

    browser_intent = parse_browser_intent(normalized)
    if browser_intent is not None:
        target = resolve_target(browser_intent.get("target", ""))
        canonical_target = target.name if target else ""
        query = browser_intent.get("query", "")
        action = "open_website" if browser_intent["intent"] == "browser_open" else browser_intent["intent"]
        prior_browser = str(context.get("current_browser") or "").lower()
        if action == "open_website" and prior_browser in {"brave", "chrome", "edge"}:
            return _base(
                raw, normalized, analysis, kind="MIXED_REQUEST", intent="execute_plan",
                target=canonical_target, target_type="website",
                entities=(Entity("website", canonical_target), Entity("browser", prior_browser)),
                capabilities=frozenset({"browser", "windows"}), ordered=True,
                plan=(
                    PlannedAction("open_application", "windows", target=prior_browser, target_type="application"),
                    PlannedAction(
                        "open_website", "browser", target=canonical_target, target_type="website",
                        modifiers=("browser=" + prior_browser,), depends_on=(0,),
                    ),
                ),
            )
        return _base(
            raw, normalized, analysis, intent=action, target=canonical_target,
            target_type="website", query=query,
            entities=tuple(item for item in (
                Entity("website", canonical_target) if canonical_target else None,
                Entity("query", query) if query else None,
            ) if item),
            capabilities=frozenset({"browser"}),
        )

    app_search = _APP_SEARCH_SUFFIX_RE.match(normalized)
    if app_search:
        query = app_search.group(1).strip()
        application = resolve_application_name(app_search.group(2))
        if application:
            return _base(
                raw, normalized, analysis, intent="search_in_application", target=application,
                target_type="application", query=query,
                entities=(Entity("application", application), Entity("query", query)),
                capabilities=frozenset({"browser", "windows"}),
            )

    file_listing = _LIST_LOCAL_ROOT_RE.fullmatch(normalized)
    if file_listing:
        root = next((value for value in file_listing.groups() if value), "desktop").capitalize()
        return _base(
            raw, normalized, analysis, intent="list_files",
            entities=(Entity("file_root", root),), target=root, target_type="file_root",
            capabilities=frozenset({"files"}),
        )

    explicit_file_path = _LIST_EXPLICIT_PATH_RE.fullmatch(normalized)
    if explicit_file_path:
        path = explicit_file_path.group(1).strip().strip("'\"` ")
        return _base(
            raw, normalized, analysis, intent="list_files",
            entities=(Entity("file_path", path),), target=path, target_type="file_path",
            capabilities=frozenset({"files"}),
        )

    file_search = _FIND_LOCAL_FILE_RE.fullmatch(normalized)
    if file_search:
        query, scope = file_search.groups()
        root = scope.capitalize() if scope.casefold() in {"desktop", "documents", "downloads"} else ""
        return _base(
            raw, normalized, analysis, intent="find_file",
            entities=(Entity("file_query", query.strip()),), target=root,
            target_type="file_root" if root else "", query=query.strip(),
            capabilities=frozenset({"files"}),
        )

    news_request = _NEWS_REQUEST_RE.fullmatch(normalized)
    if news_request:
        topic = (news_request.group(1) or "").strip()
        query = f"latest news {topic}".strip()
        info_analysis = replace(analysis, kind="information", has_action=False, refers_to_context=False)
        return _base(
            raw, normalized, info_analysis, kind="INFORMATION_REQUEST", intent="search_web", target="google",
            target_type="website", query=query,
            entities=(Entity("news_topic", topic or "general"),),
            capabilities=frozenset({"browser"}),
            analysis_override=info_analysis,
        )

    if analysis.refers_to_context and re.match(r"^(?:search|find|look up)\b", normalized, re.I):
        from app.agent.runtime_context import contextual_browser_intent

        contextual = contextual_browser_intent(normalized, context)
        if contextual is not None:
            target = resolve_target(contextual.get("target", ""))
            canonical_target = target.name if target else str(contextual.get("name", ""))
            query = contextual.get("query", "")
            intent = "search_in_application" if contextual.get("intent") == "search_in_application" else "browser_search"
            return _base(
                raw, normalized, analysis, intent=intent, target=canonical_target,
                target_type="application" if intent == "search_in_application" else "website",
                query=query, entities=(Entity("query", query), Entity("context_reference", normalized)),
                capabilities=frozenset({"browser", "windows"}) if intent == "search_in_application" else frozenset({"browser"}),
            )

    if allow_mixed:
        clauses = _MIXED_SPLIT_RE.split(normalized)
        if len(clauses) >= 3:
            actions = [part for part in clauses[::2] if part and _ACTION_LEAD_RE.match(part)]
            if len(actions) >= 2:
                planning_context = dict(context)
                children = []
                for part in actions:
                    child = _parse_one(part, planning_context, allow_mixed=False)
                    children.append(child)
                    if child.intent == "open_application" and child.target in {"brave", "chrome", "edge"}:
                        planning_context["current_browser"] = child.target
                if all(child.intent != "none" for child in children):
                    dependencies: list[PlannedAction] = []
                    ordered = False
                    connector_words = [part.lower() for part in clauses[1::2]]
                    for index, child in enumerate(children):
                        dependent = index > 0 and (
                            "then" in connector_words[index - 1]
                            or children[index - 1].intent in {"open_application", "open_website", "navigate"}
                            and child.intent in {
                                "browser_search", "browser_interaction", "search_in_application", "search_web",
                                "play_media_content", "send_whatsapp_message",
                            }
                        )
                        ordered = ordered or dependent
                        dependencies.append(PlannedAction(
                            intent=child.intent,
                            capability=sorted(child.capabilities)[0] if child.capabilities else "general",
                            target=child.target,
                            target_type=child.target_type,
                            query=child.query,
                            modifiers=child.modifiers,
                            depends_on=(index - 1,) if dependent else (),
                        ))
                    capabilities = frozenset(cap for child in children for cap in child.capabilities)
                    all_entities = tuple(entity for child in children for entity in child.entities)
                    return _base(
                        raw, normalized, analysis, kind="MIXED_REQUEST", intent="execute_plan",
                        entities=all_entities, capabilities=capabilities, plan=tuple(dependencies), ordered=ordered,
                    )

    contextual_switch = _CONTEXTUAL_SWITCH_RE.match(normalized)
    if contextual_switch and context:
        switch_target = contextual_switch.group(1).strip().strip("'\"`.,!? ")
        if switch_target:
            target, target_type, browser, _ = _open_entity(switch_target)
            if target_type == "website":
                selected_browser = str(context.get("current_browser") or "").lower()
                if selected_browser in {"brave", "chrome", "edge"}:
                    return _base(
                        raw, normalized, analysis, kind="MIXED_REQUEST", intent="execute_plan",
                        target=target, target_type="website",
                        entities=(Entity("website", target), Entity("browser", selected_browser)),
                        capabilities=frozenset({"browser", "windows"}),
                        plan=(
                            PlannedAction("open_application", "windows", target=selected_browser, target_type="application"),
                            PlannedAction("open_website", "browser", target=target, target_type="website", modifiers=(f"browser={selected_browser}",), depends_on=(0,)),
                        ),
                        ordered=True,
                    )
                return _base(
                    raw, normalized, analysis, intent="open_website", target=target, target_type="website",
                    entities=(Entity("website", target),), capabilities=frozenset({"browser", "windows"}),
                )

    web_search = _WEB_SEARCH_RE.match(normalized)
    if web_search:
        query = web_search.group(1).strip()
        selected_browser = str(context.get("current_browser") or "").lower()
        explicitly_general = bool(re.match(
            r"^(?:search|look up)\s+(?:the\s+web|online|the\s+internet)\s+for\b",
            normalized, re.I,
        ))
        if selected_browser in {"brave", "chrome", "edge"} and not explicitly_general:
            return _base(
                raw, normalized, analysis, intent="search_in_application", target=selected_browser,
                target_type="application", query=query,
                entities=(Entity("application", selected_browser), Entity("query", query)),
                capabilities=frozenset({"browser", "windows"}),
            )
        return _base(
            raw, normalized, analysis, intent="search_web", query=query,
            entities=(Entity("query", query),), capabilities=frozenset({"browser"}),
        )

    communication_match = _COMMUNICATION_RE.match(normalized) or _EMAIL_MESSAGE_RE.match(normalized)
    if communication_match:
        contact = communication_match.group("contact").strip().strip("'\"`.,!? ")
        message = communication_match.group("message").strip().strip("'\"`.,!? ")
        if contact and message and contact.lower() not in {"me", "us", "them", "you"}:
            return _base(
                raw, normalized, analysis, kind="ACTION", intent="send_whatsapp_message",
                entities=(Entity("contact", contact), Entity("message", message)),
                target=contact, target_type="contact", query=message,
                capabilities=frozenset({"messaging"}),
            )

    message_match = _MESSAGE_WITH_DELIMITER_RE.match(normalized) or _MESSAGE_SIMPLE_RE.match(normalized)
    if message_match:
        contact, message = (part.strip().strip("'\" ") for part in message_match.groups())
        if contact and message:
            return _base(
                raw, normalized, analysis, kind="ACTION", intent="send_whatsapp_message",
                entities=(Entity("contact", contact), Entity("message", message)),
                target=contact, target_type="contact", query=message,
                capabilities=frozenset({"messaging"}),
            )

    project_match = _OPEN_PROJECT_RE.match(normalized)
    if project_match:
        project_name = re.sub(r"\s+project$", "", project_match.group(1).strip(), flags=re.I).strip()
        if project_name:
            return _base(
                raw, normalized, analysis, intent="open_project",
                entities=(Entity("project", project_name), Entity("application", "vscode")),
                target=project_name, target_type="project",
                capabilities=frozenset({"projects", "windows"}),
            )

    match = _OPEN_RE.match(normalized)
    if match:
        target, target_type, browser, raw_target = _open_entity(match.group(1))
        if target_type == "website" and not browser:
            prior_browser = str(context.get("current_browser") or "").lower()
            if prior_browser in {"brave", "chrome", "edge"}:
                browser = prior_browser
        intent = "open_website" if target_type == "website" else "open_application" if target_type == "application" else "open_target"
        capabilities = frozenset({"browser"}) if target_type == "website" else frozenset({"windows"}) if target_type == "application" else frozenset()
        entities = (Entity(target_type, target),) if target else (Entity("unresolved_target", raw_target),)
        if browser:
            entities += (Entity("browser", browser),)
            capabilities |= frozenset({"windows"})
            plan = (
                PlannedAction("open_application", "windows", target=browser, target_type="application"),
                PlannedAction(
                    "open_website", "browser", target=target, target_type="website",
                    modifiers=("browser=" + browser,), depends_on=(0,),
                ),
            )
            return _base(
                raw, normalized, analysis, kind="MIXED_REQUEST", intent="execute_plan",
                entities=entities, capabilities=capabilities, plan=plan, ordered=True,
            )
        return _base(
            raw, normalized, analysis, intent=intent, entities=entities, target=target,
            target_type=target_type or "unknown", modifiers=(("browser=" + browser,) if browser else ()),
            capabilities=capabilities,
        )

    match = _CONTROL_RE.match(normalized)
    if match and re.search(r"\b(song|track|video|music|media|audio|it|that|this)\b", match.group(2), re.I):
        command, subject = match.group(1).lower(), match.group(2).strip()
        intent = "pause_current_media" if command == "stop" else "resume_current_media" if command in {"resume", "continue"} else "pause_current_media"
        return _base(
            raw, normalized, analysis, intent=intent,
            entities=(Entity("media_reference", subject),), target="current_media", target_type="media",
            capabilities=frozenset({"media"}),
        )

    if re.fullmatch(r"play\s+(?:something|anything)\s+on\s+wikipedia", normalized, re.I):
        # Wikipedia is a readable information site, not a media player. Treat
        # this phrase as an explicit site choice so the following search uses it.
        return _base(
            raw, normalized, analysis, intent="open_and_remember_site",
            entities=(Entity("website", "wikipedia"),), target="wikipedia",
            target_type="website", capabilities=frozenset({"browser"}),
        )

    match = _PLAY_RE.match(normalized)
    if match:
        content = match.group(1).strip()
        requested_browser = ""
        browser_suffix = re.search(
            r"\s+on\s+(brave(?:\s+browser)?|microsoft\s+edge|edge|chrome|google\s+chrome)$",
            content, re.I,
        )
        if browser_suffix:
            candidate = resolve_application_name(browser_suffix.group(1))
            if candidate in {"brave", "chrome", "edge"}:
                requested_browser = candidate
                content = content[:browser_suffix.start()].strip()
        browser_modifiers = (f"browser={requested_browser}",) if requested_browser else ()
        if re.search(r"\b(?:another|different|else|more)\b", content, re.I):
            last_query = str(context.get("last_query") or "").strip()
            alternative = re.sub(r"^(?:another|different|more)\s+", "", content, flags=re.I)
            query = _media_query(alternative) or last_query or "music"
            return _base(
                raw, normalized, analysis, kind="MODIFICATION" if analysis.refers_to_context else "ACTION",
                intent="play_media_content", entities=(Entity("media_query", query),),
                target=str(context.get("active_service") or "youtube"), target_type="media_service",
                query=query, modifiers=("avoid_current",), capabilities=frozenset({"media"}),
            )
        refers_to_current_media = re.search(r"\b(song|track|video|music|media|it|that|this)\b", content, re.I)
        if refers_to_current_media and _MEDIA_STATE_REFERENCE_RE.search(content):
            return _base(
                raw, normalized, analysis, kind="FOLLOW_UP", intent="resume_current_media",
                entities=(Entity("media_reference", content),), target="current_media", target_type="media",
                capabilities=frozenset({"media"}),
            )
        if refers_to_current_media and _MEDIA_REPLAY_REFERENCE_RE.search(content):
            last_query = str(context.get("last_query") or "").strip()
            current_media = str(context.get("current_media") or "").strip()
            media_state = str(context.get("media_state") or "").lower()
            if context.get("active_media") and media_state in {"pause", "paused"}:
                return _base(
                    raw, normalized, analysis, kind="FOLLOW_UP", intent="resume_current_media",
                    entities=(Entity("media_reference", content),), target="current_media", target_type="media",
                    capabilities=frozenset({"media"}),
                )
            # Replay wording may refer to a prior item, but it must not resume
            # unrelated media simply because some media tool was used before.
            replay_subject = re.sub(r"\b(?:again|same|previous|last)\b", "", content, flags=re.I)
            query = last_query or current_media or _media_query(replay_subject) or "music"
            return _base(
                raw, normalized, analysis, kind="FOLLOW_UP", intent="play_media_content",
                entities=(Entity("media_query", query),), target="youtube", target_type="media_service",
                query=query, capabilities=frozenset({"media"}),
            )
        result_reference = re.search(r"\b(first|second|third|last|previous)\b", content, re.I)
        if result_reference:
            query = str(context.get("last_query") or "").strip()
            if query:
                ordinal = result_reference.group(1).lower()
                index = {"first": 0, "second": 1, "third": 2, "last": -1, "previous": -1}[ordinal]
                return _base(
                    raw, normalized, analysis, kind="FOLLOW_UP", intent="play_media_content",
                    entities=(Entity("media_query", query), Entity("result_reference", ordinal)),
                    target=str(context.get("active_service") or "youtube"), target_type="media_service",
                    query=query, modifiers=(f"result_index={index}",), capabilities=frozenset({"media"}),
                )
        if re.fullmatch(r"(?:it|that|this|the\s+(?:song|track|video|music))", content, re.I):
            return _base(
                raw, normalized, analysis, kind="FOLLOW_UP", intent="resume_current_media",
                entities=(Entity("media_reference", content),), target="current_media", target_type="media",
                capabilities=frozenset({"media"}),
            )
        query = _media_query(content) or str(context.get("last_query") or "music")
        return _base(
            raw, normalized, analysis, intent="play_media_content",
            entities=(Entity("media_query", query),), target="youtube", target_type="media_service",
            query=query, modifiers=browser_modifiers, capabilities=frozenset({"media"}),
        )

    if re.fullmatch(r"(?:copy\s+(?:that|this|it|the\s+selection|selected\s+text)|copy)", normalized, re.I):
        return _base(
            raw, normalized, analysis, intent="copy_selection",
            entities=(Entity("context_reference", "selection"),),
            target=str(context.get("current_window") or context.get("current_application") or ""),
            target_type="application", capabilities=frozenset({"clipboard", "windows"}),
        )

    copy_application_text = _COPY_APPLICATION_TEXT_RE.match(normalized)
    if copy_application_text:
        target = copy_application_text.group(1).strip().strip("'\"`.,!? ")
        application = resolve_application_name(target)
        return _base(
            raw, normalized, analysis, intent="copy_application_text",
            entities=(Entity("application", application or target), Entity("text", "document")),
            target=application or target, target_type="application",
            capabilities=frozenset({"clipboard", "windows"}),
        )

    if re.fullmatch(r"paste(?:\s+(?:it|that|this|now|there|here))*", normalized, re.I):
        return _base(
            raw, normalized, analysis, intent="paste_text",
            entities=(Entity("context_reference", "clipboard"),),
            target=str(context.get("current_window") or context.get("current_application") or ""),
            target_type="application", capabilities=frozenset({"clipboard", "windows"}),
        )

    match = _TYPE_RE.match(normalized)
    if match:
        text = match.group(1).strip().strip("'\"` ")
        target_match = re.search(r"\s+(?:in|into)\s+(.+)$", text, re.I)
        target = ""
        if target_match:
            explicit_target = target_match.group(1).strip()
            app = resolve_application_name(explicit_target)
            if app:
                target = app
                text = text[:target_match.start()].strip()
        target = target or str(context.get("current_window") or context.get("current_application") or "")
        return _base(
            raw, normalized, analysis, intent="type_text", entities=(Entity("text", text),),
            target=target, target_type="application", query=text,
            capabilities=frozenset({"windows"}),
        )

    if analysis.kind == "information":
        lowered = normalized.lower()
        capability = "media" if re.search(r"\b(song|track|video|currently playing)\b", lowered) else "information"
        return _base(raw, normalized, analysis, intent="information_request", capabilities=frozenset({capability}))

    if analysis.kind in {"action", "follow_up", "mixed"}:
        lowered = normalized.lower()
        capabilities: set[str] = set()
        if analysis.kind == "follow_up" and context.get("active_media"):
            capabilities.add("media")
        if re.search(r"\b(?:copy|paste|clipboard|selection)\b", lowered):
            capabilities.update({"clipboard", "windows"})
        if re.search(r"\b(?:screen|screenshot|see|look\s+at|what\s+does|is\s+this|showing)\b", lowered):
            capabilities.add("windows")
        if re.search(r"\b(?:type|write|enter|click|press|focus|close|open|launch|use|switch)\b", lowered):
            capabilities.add("windows")
        if re.search(r"\b(?:play|pause|resume|song|track|video|music|media)\b", lowered):
            capabilities.add("media")
        if re.search(r"\b(?:search|find|navigate|website|browser|url|chatgpt|claude)\b", lowered):
            capabilities.add("browser")
        if re.search(r"\b(?:send|message|whatsapp|greet|wish|tell|let|inform|notify|ask)\b", lowered):
            capabilities.add("messaging")
        if re.search(r"\b(?:remember|save|forget|memory)\b", lowered):
            capabilities.add("memory")
        if re.search(r"\b(?:file|folder)\b", lowered):
            capabilities.add("files")
        if re.search(r"\bproject\b", lowered):
            capabilities.add("projects")
        if re.search(r"\b(?:terminal|command)\b", lowered):
            capabilities.add("system")
        if re.search(r"\b(?:weather|forecast|time|calculate|system status|ram|cpu|disk)\b", lowered):
            capabilities.add("information")
        if capabilities:
            return _base(raw, normalized, analysis, intent="interpret_action", capabilities=frozenset(capabilities))
        return _base(raw, normalized, analysis, intent="interpret_action", capabilities=frozenset({"general"}))

    return _base(raw, normalized, analysis)


def build_user_request(
    text: str,
    context: dict | None = None,
    analysis: UtteranceAnalysis | None = None,
) -> UserRequest:
    context = context or {}
    return _parse_one(text, context, allow_mixed=True, analysis_override=analysis)
