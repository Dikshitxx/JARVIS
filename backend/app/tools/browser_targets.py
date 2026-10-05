"""Generic browser target metadata and intent parsing."""

import re
from dataclasses import dataclass
from urllib.parse import quote_plus
from urllib.parse import urlparse


@dataclass(frozen=True)
class BrowserTarget:
    name: str
    canonical_url: str
    search_url: str | None = None
    capabilities: frozenset[str] = frozenset({"open"})
    adapter: str = "generic"
    selectors: tuple[str, ...] = ()
    host_aliases: tuple[str, ...] = ()


TARGETS = {
    "google": BrowserTarget("google", "https://www.google.com", "https://www.google.com/search?q={query}", frozenset({"open", "search"})),
    "youtube": BrowserTarget("youtube", "https://www.youtube.com", "https://www.youtube.com/results?search_query={query}", frozenset({"open", "search", "playback"}), "youtube"),
    "wikipedia": BrowserTarget("wikipedia", "https://www.wikipedia.org", "https://www.wikipedia.org/w/index.php?search={query}", frozenset({"open", "search"})),
    "github": BrowserTarget("github", "https://github.com", "https://github.com/search?q={query}", frozenset({"open", "search"})),
    "amazon": BrowserTarget("amazon", "https://www.amazon.com", "https://www.amazon.com/s?k={query}", frozenset({"open", "search"})),
    "whatsapp": BrowserTarget("whatsapp", "https://web.whatsapp.com", capabilities=frozenset({"open", "interact"}), adapter="chat"),
    "chatgpt": BrowserTarget(
        "chatgpt", "https://chatgpt.com", capabilities=frozenset({"open", "interact"}),
        adapter="chat", host_aliases=("chat.openai.com", "auth.openai.com"),
    ),
    "claude": BrowserTarget("claude", "https://claude.ai", capabilities=frozenset({"open", "interact"}), adapter="chat"),
    "grok": BrowserTarget("grok", "https://grok.com", capabilities=frozenset({"open", "interact"}), adapter="chat"),
}

ALIASES = {
    "google.com": "google",
    "yt": "youtube",
    "you tube": "youtube",
    "chat gpt": "chatgpt",
    "chat-gpt": "chatgpt",
    "whatsappweb": "whatsapp",
    "whatsapp web": "whatsapp",
    "wa": "whatsapp",
}


def normalize_target(value: str) -> str:
    target = value.strip().strip(".!?,").lower()
    target = re.sub(r"[-_]+", " ", target)
    if target in ALIASES:
        return ALIASES[target]
    if target in TARGETS:
        return target

    noise_removed = re.sub(r"\b(?:web|browser|messenger|application|app|desktop)\b", " ", target).strip()
    for candidate in (noise_removed, re.sub(r"\s+", "", target), re.sub(r"\s+", "", noise_removed)):
        if candidate in TARGETS:
            return candidate
        if candidate in ALIASES:
            return ALIASES[candidate]

    collapsed = re.sub(r"\s+", "", target)
    return ALIASES.get(target, ALIASES.get(noise_removed, collapsed))


def resolve_target(value: str) -> BrowserTarget | None:
    target = normalize_target(value)
    if target in TARGETS:
        return TARGETS[target]
    if target.startswith(("http://", "https://")):
        known = next((item for item in TARGETS.values() if target_matches_url(item, target)), None)
        if known is not None:
            return known
    if re.fullmatch(r"(?:https?://)?[a-z0-9.-]+\.[a-z]{2,}(?:/.*)?", target):
        url = target if target.startswith("http") else f"https://{target}"
        return BrowserTarget(target, url, capabilities=frozenset({"open"}))
    return None


def browser_search_url(target: BrowserTarget, query: str) -> str | None:
    if target.search_url is None:
        return None
    return target.search_url.format(query=quote_plus(query))


def target_matches_url(target: BrowserTarget, url: str) -> bool:
    actual = (urlparse(url).hostname or "").lower().removeprefix("www.")
    hosts = {
        (urlparse(target.canonical_url).hostname or "").lower().removeprefix("www."),
        *(host.lower().removeprefix("www.") for host in target.host_aliases),
    }
    return bool(actual) and any(actual == host or actual.endswith(f".{host}") for host in hosts if host)


def parse_browser_intent(user_text: str) -> dict | None:
    text = user_text.strip().rstrip(".!?")
    # General web search is not a site-targeted browser operation.
    if re.match(r"^(?:search|look up|find)\s+(?:the\s+web|online|the\s+internet)\s+for\s+", text, re.I):
        return None
    match = re.match(r"^(?:search|find|look up)\s+(?:on\s+)?(.+?)\s+for\s+(.+)$", text, re.I)
    if match:
        target_name, query = match.group(1).strip(), match.group(2).strip()
        target = resolve_target(target_name)
        if target is not None:
            return {"intent": "browser_search", "target": target.name, "query": query, "operation": "search"}
    match = re.match(r"^(?:search|find|look up)\s+(.+?)\s+on\s+(.+)$", text, re.I)
    if match:
        return {"intent": "browser_search", "target": normalize_target(match.group(2)), "query": match.group(1).strip(), "operation": "search"}
    match = re.match(r"^ask\s+(.+?)\s+(?:about|to explain|to tell me about)\s+(.+)$", text, re.I)
    if match:
        return {"intent": "browser_interaction", "target": normalize_target(match.group(1)), "query": match.group(2).strip(), "operation": "interact"}
    match = re.match(r"^(?:say|tell|send|write)\s+(.+?)\s+to\s+(.+)$", text, re.I)
    if match:
        target = resolve_target(match.group(2).strip())
        if target is not None and target.name != "whatsapp" and "interact" in target.capabilities:
            return {"intent": "browser_interaction", "target": target.name, "query": match.group(1).strip(), "operation": "interact"}
    match = re.match(r"^go to\s+(.+?)\s+and\s+(?:find|search for|look up)\s+(.+)$", text, re.I)
    if match:
        return {"intent": "browser_search", "target": normalize_target(match.group(1)), "query": match.group(2).strip(), "operation": "navigate_search"}
    match = re.match(r"^open\s+(.+)$", text, re.I)
    if match:
        target_name = match.group(1).strip()
        from app.tools.apps import resolve_application_name

        app_name = resolve_application_name(target_name)
        # "WhatsApp Messenger" explicitly names the web target; "WhatsApp"
        # alone can still resolve to the installed desktop application.
        explicit_web_target = "messenger" in target_name.lower() or "web" in target_name.lower()
        if resolve_target(target_name) is not None and (app_name is None or explicit_web_target):
            return {"intent": "browser_open", "target": normalize_target(target_name), "query": "", "operation": "open"}
    return None
