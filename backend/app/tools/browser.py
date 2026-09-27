from urllib.parse import quote_plus

from app.core import config
from app.tools.browser_adapters import adapter_for, check_challenge
from app.tools.browser_session import get_browser_session
from app.tools.browser_targets import resolve_target
from app.tools.registry import Tool, ToolResult, register


def _run_target(target_name: str, operation: str, query: str = "") -> ToolResult:
    target = resolve_target(target_name)
    if target is None:
        return ToolResult("clarification_required", f"I don't recognize the browser target '{target_name}'. Please provide a known website or URL.")

    def execute():
        adapter = adapter_for(get_browser_session(), target)
        if operation == "open":
            return adapter.open()
        if operation == "search":
            return adapter.search(query)
        if operation == "interact":
            return adapter.interact(query)
        return ToolResult("invalid_action", f"Unsupported browser operation: {operation}.")

    try:
        return get_browser_session().run(execute)
    except Exception as exc:
        return ToolResult("failure", f"Browser operation failed for {target.name}: {exc}")


def open_url(url: str = "", target: str = "", query: str = "") -> ToolResult:
    if target:
        if query:
            return browser_search(target, query)
        url = target
    target = resolve_target(url)
    if target is None:
        return ToolResult("clarification_required", f"I don't recognize the browser target or URL '{url}'.")
    return _run_target(target.name, "open")


def search_web(query: str, target: str = "") -> ToolResult:
    if target:
        return browser_search(target, query)
    url = config.BROWSER_SEARCH_PROVIDER.format(query=quote_plus(query))

    def execute():
        session = get_browser_session()
        page = session.page("general-search", url)
        challenge = check_challenge(page)
        if challenge:
            return challenge
        if page.url == "about:blank":
            return ToolResult("failure", "General web search did not navigate to a result page.")
        return ToolResult("success", f"Searched the web for: {query}")

    try:
        return get_browser_session().run(execute)
    except Exception as exc:
        return ToolResult("failure", f"General web search failed: {exc}")


def browser_search(target: str, query: str) -> ToolResult:
    return _run_target(target, "search", query)


def browser_open(target: str) -> ToolResult:
    return _run_target(target, "open")


def browser_interaction(target: str, query: str) -> ToolResult:
    return _run_target(target, "interact", query)


def play_youtube_song(query: str) -> ToolResult:
    target = resolve_target("youtube")

    def execute():
        return adapter_for(get_browser_session(), target).play(query)

    try:
        return get_browser_session().run(execute)
    except Exception as exc:
        return ToolResult("failure", f"YouTube playback failed: {exc}")


def toggle_youtube_playback() -> ToolResult:
    target = resolve_target("youtube")

    def execute():
        return adapter_for(get_browser_session(), target).toggle_playback()

    try:
        return get_browser_session().run(execute)
    except Exception as exc:
        return ToolResult("failure", f"YouTube playback control failed: {exc}")


register(Tool(
    name="open_url",
    description="Open a known website target or URL in the browser. If a target and query are supplied, use its browser search operation.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}, "target": {"type": "string"}, "query": {"type": "string"}},
    },
    func=open_url,
))
register(Tool(
    name="search_web",
    description="Search the general web using the configured search provider. If target is supplied, search that explicit website through the browser target registry.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}, "target": {"type": "string"}},
        "required": ["query"],
    },
    func=search_web,
))
register(Tool(
    name="browser_search",
    description="Search an explicitly named website or web application using its registered browser adapter.",
    parameters={
        "type": "object",
        "properties": {"target": {"type": "string"}, "query": {"type": "string"}},
        "required": ["target", "query"],
    },
    func=browser_search,
))
register(Tool(
    name="browser_open",
    description="Open an explicitly named website or web application in the browser.",
    parameters={"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]},
    func=browser_open,
))
register(Tool(
    name="browser_interaction",
    description="Ask or interact with an explicitly named web application using its registered browser adapter.",
    parameters={
        "type": "object",
        "properties": {"target": {"type": "string"}, "query": {"type": "string"}},
        "required": ["target", "query"],
    },
    func=browser_interaction,
))
register(Tool(
    name="play_youtube_song",
    description="Open YouTube, search for a song/video, and play the first result.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    func=play_youtube_song,
))
register(Tool(
    name="toggle_youtube_playback",
    description="Pause or resume the currently playing YouTube video.",
    parameters={"type": "object", "properties": {}},
    func=toggle_youtube_playback,
))
