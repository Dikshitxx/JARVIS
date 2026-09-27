"""Generic browser target metadata and intent parsing."""

import re
from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class BrowserTarget:
    name: str
    canonical_url: str
    search_url: str | None = None
    capabilities: frozenset[str] = frozenset({"open"})
    adapter: str = "generic"
    selectors: tuple[str, ...] = ()


TARGETS = {
    "google": BrowserTarget("google", "https://www.google.com", "https://www.google.com/search?q={query}", frozenset({"open", "search"})),
    "youtube": BrowserTarget("youtube", "https://www.youtube.com", "https://www.youtube.com/results?search_query={query}", frozenset({"open", "search", "playback"}), "youtube"),
    "wikipedia": BrowserTarget("wikipedia", "https://www.wikipedia.org", "https://www.wikipedia.org/w/index.php?search={query}", frozenset({"open", "search"})),
    "github": BrowserTarget("github", "https://github.com", "https://github.com/search?q={query}", frozenset({"open", "search"})),
    "amazon": BrowserTarget("amazon", "https://www.amazon.com", "https://www.amazon.com/s?k={query}", frozenset({"open", "search"})),
    "chatgpt": BrowserTarget("chatgpt", "https://chatgpt.com", capabilities=frozenset({"open", "interact"}), adapter="chat"),
    "claude": BrowserTarget("claude", "https://claude.ai", capabilities=frozenset({"open", "interact"}), adapter="chat"),
    "grok": BrowserTarget("grok", "https://grok.com", capabilities=frozenset({"open", "interact"}), adapter="chat"),
}

ALIASES = {
    "google.com": "google",
    "yt": "youtube",
    "you tube": "youtube",
    "chat gpt": "chatgpt",
    "chat-gpt": "chatgpt",
}


def normalize_target(value: str) -> str:
    target = value.strip().strip(".!?,").lower()
    return ALIASES.get(target, target.replace(" ", ""))


def resolve_target(value: str) -> BrowserTarget | None:
    target = normalize_target(value)
    if target in TARGETS:
        return TARGETS[target]
    if re.fullmatch(r"(?:https?://)?[a-z0-9.-]+\.[a-z]{2,}(?:/.*)?", target):
        url = target if target.startswith("http") else f"https://{target}"
        return BrowserTarget(target, url, capabilities=frozenset({"open"}))
    return None


def browser_search_url(target: BrowserTarget, query: str) -> str | None:
    if target.search_url is None:
        return None
    return target.search_url.format(query=quote_plus(query))


def parse_browser_intent(user_text: str) -> dict | None:
    text = user_text.strip().rstrip(".!?")
    match = re.match(r"^(?:search|find|look up)\s+(.+?)\s+on\s+(.+)$", text, re.I)
    if match:
        return {"intent": "browser_search", "target": normalize_target(match.group(2)), "query": match.group(1).strip(), "operation": "search"}
    match = re.match(r"^ask\s+(.+?)\s+(?:about|to explain|to tell me about)\s+(.+)$", text, re.I)
    if match:
        return {"intent": "browser_interaction", "target": normalize_target(match.group(1)), "query": match.group(2).strip(), "operation": "interact"}
    match = re.match(r"^go to\s+(.+?)\s+and\s+(?:find|search for|look up)\s+(.+)$", text, re.I)
    if match:
        return {"intent": "browser_search", "target": normalize_target(match.group(1)), "query": match.group(2).strip(), "operation": "navigate_search"}
    match = re.match(r"^open\s+(.+)$", text, re.I)
    if match and resolve_target(match.group(1)) is not None:
        return {"intent": "browser_open", "target": normalize_target(match.group(1)), "query": "", "operation": "open"}
    return None