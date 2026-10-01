import logging
import re
import time
from urllib.parse import quote_plus
from urllib.parse import urlparse

import pyautogui
import pyperclip

from app.core import config
from app.tools.apps import _process_names, focus_app, get_active_window_info, open_app, resolve_application_name
from app.tools.browser_adapters import adapter_for
from app.tools.browser_session import get_browser_session
from app.tools.browser_targets import resolve_target
from app.tools.registry import Tool, ToolResult, register

log = logging.getLogger("jarvis.browser")

SITE_URLS = {
    "wikipedia": "https://en.wikipedia.org",
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "github": "https://github.com",
    "reddit": "https://reddit.com",
}
SITE_SEARCH = {
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "google": "https://www.google.com/search?q={q}",
}


def _launch_brave(url: str, action: str, query: str = "") -> ToolResult:
    try:
        session = get_browser_session()

        def navigate():
            page = session.page("browser_navigation", url)
            expected_host = (urlparse(url).hostname or "").lower().removeprefix("www.")
            actual_host = (urlparse(page.url).hostname or "").lower().removeprefix("www.")
            if page.url == "about:blank" or not expected_host or not (
                actual_host == expected_host or actual_host.endswith(f".{expected_host}")
            ):
                return ToolResult(
                    "failure", f"Sent navigation to {url}, but couldn't verify the page URL.",
                    data={"url": page.url, "query": query}, action=action, target=url,
                    verification_status="failed",
                )
            browser_name = "Brave"
            if query:
                message = f"Opened a search for '{query}' in {browser_name}. Verified page: {page.url}"
            else:
                message = f"Opened {url} in {browser_name}. Verified page: {page.url}"
            return ToolResult(
                "success", message, data={"url": page.url, "query": query},
                action=action, target=url, verification_status="verified",
            )

        return session.run(navigate)
    except Exception as exc:
        return ToolResult("failure", f"Could not open Brave for {url}: {exc}", action=action, target=url, verification_status="failed")


def _site_name(value: str) -> str:
    target = resolve_target(value)
    return target.name if target else value.strip().lower()


def _search_url(target_name: str, query: str) -> str | None:
    site = _site_name(target_name) if target_name else "google"
    template = SITE_SEARCH.get(site)
    if template:
        return template.format(q=quote_plus(query))
    if site == "github":
        return f"https://github.com/search?q={quote_plus(query)}"
    if site == "reddit":
        return f"https://www.reddit.com/search/?q={quote_plus(query)}"
    target = resolve_target(site)
    if target:
        from app.tools.browser_targets import browser_search_url

        return browser_search_url(target, query)
    return None


def _set_agent_site_state(site_name: str | None = None, search_query: str | None = None) -> None:
    """Keep the singleton's convenience state aligned for direct tool calls."""
    try:
        from app.agent.agent import agent

        if site_name is not None:
            agent.last_site = site_name
        if search_query is not None:
            agent.last_search_query = search_query
    except Exception:
        pass


def _run_target(target_name: str, operation: str, query: str = "") -> ToolResult:
    target = resolve_target(target_name)
    if target is None:
        return ToolResult("clarification_required", f"I don't recognize the browser target '{target_name}'. Please provide a known website or URL.")

    if operation == "open":
        return open_url(url=target.canonical_url)
    if operation == "search":
        url = _search_url(target.name, query)
        if not url:
            return ToolResult("clarification_required", f"I don't know how to search {target.name}. Please choose Google, Wikipedia, or YouTube.")
        return _launch_brave(url, "browser_search", query)
    if operation == "interact":
        return ToolResult("invalid_action", "Direct interaction with general web pages is not available. I can open or search supported sites.")
    return ToolResult("invalid_action", f"Unsupported browser operation: {operation}.")


def open_url(url: str = "", target: str = "", query: str = "") -> ToolResult:
    if target:
        if query:
            return browser_search(target, query)
        url = target
    target_name = _site_name(url)
    if target_name in SITE_URLS:
        url = SITE_URLS[target_name]
    else:
        target_info = resolve_target(url)
        if target_info is not None:
            url = target_info.canonical_url
        elif not re.match(r"^https?://", url, re.I):
            url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ToolResult("clarification_required", f"I don't recognize the browser target or URL '{url}'.")
    return _launch_brave(url, "open_url")


def search_web(query: str, target: str = "") -> ToolResult:
    if not query.strip():
        return ToolResult("clarification_required", "Tell me what you want to search for.")
    from app.tools.web_search import get_search_provider

    provider = get_search_provider()
    failures = []
    log.info("SEARCH_REQUEST query=%r provider=%s", query, config.WEB_SEARCH_PROVIDER)
    try:
        results = provider.search(query)
    except Exception as exc:
        failures.append(str(exc))
        log.warning("HTTP web search failed; trying browser fallback: %s", exc)
        try:
            results = provider.browser_fallback(query)
        except Exception as browser_exc:
            failures.append(str(browser_exc))
            return ToolResult(
                "failure", f"Web search could not retrieve results: {'; '.join(failures)}",
                action="search_web", target=query, verification_status="failed",
                data={"query": query, "results": [], "errors": failures},
            )

    if not results:
        return ToolResult("failure", "The search provider returned no readable results.", action="search_web",
                          target=query, verification_status="failed", data={"query": query, "results": []})
    results = results[:config.WEB_SEARCH_RESULT_LIMIT]
    for rank, result in enumerate(results, 1):
        result["rank"] = rank
    evidence = "\n\n".join(
        f"{item['rank']}. {item['title']}\nSource: {item['source']}\nURL: {item['url']}\nSnippet: {item['snippet']}"
        for item in results
    )
    _set_agent_site_state(search_query=query)
    log.info("SEARCH_EXECUTED query=%r count=%s", query, len(results))
    providers = sorted({item.get("provider", config.WEB_SEARCH_PROVIDER) for item in results})
    return ToolResult(
        "success", f"Retrieved {len(results)} web results for '{query}'.\n\n{evidence}",
        data={"query": query, "provider": providers, "results": results},
        action="search_web", target=query, verification_status="verified",
    )


def fetch_web_page(url: str) -> ToolResult:
    """Fetch and extract bounded page text from an HTTP(S) URL returned by search."""
    try:
        from app.tools.web_search import get_search_provider

        content = get_search_provider().extract_content(url)
        if not content:
            return ToolResult("failure", f"No readable page text was extracted from {url}.",
                              action="fetch_web_page", target=url, verification_status="failed")
        return ToolResult("success", f"Extracted page content from {url}:\n{content}",
                          data={"url": url, "content": content}, action="fetch_web_page",
                          target=url, verification_status="verified")
    except Exception as exc:
        return ToolResult("failure", f"Could not retrieve {url}: {exc}", action="fetch_web_page",
                          target=url, verification_status="failed")


def open_and_remember_site(site_name: str) -> ToolResult:
    site = site_name.strip().lower()
    url = SITE_URLS.get(site)
    if url is None:
        return ToolResult("clarification_required", f"I don't know the site '{site_name}'.")
    result = open_url(url=url)
    if result.status == "success":
        _set_agent_site_state(site_name=site)
    return result


def browser_search(target: str, query: str) -> ToolResult:
    return _run_target(target, "search", query)


def _navigate_in_application(name: str, url: str, expected: str) -> ToolResult:
    app_name = resolve_application_name(name)
    if app_name not in {"brave", "chrome", "edge"}:
        return ToolResult("clarification_required", f"'{name}' is not a supported browser application.")
    opened = open_app(app_name)
    if opened.status != "success":
        return opened
    focused = focus_app(app_name)
    if focused.lower().startswith("error:"):
        return ToolResult("failure", focused)

    before = get_active_window_info()
    expected_processes = _process_names(app_name)
    active_process = str(before.get("application", "") or "").lower()
    if not before.get("pid") or active_process not in expected_processes:
        return ToolResult(
            "failure",
            f"I couldn't verify that {app_name} has focus, so I did not send navigation keystrokes. "
            f"The foreground application is {active_process or 'unknown'}.",
            action="open_website_in_application", target=app_name, verification_status="failed",
        )
    previous_clipboard = pyperclip.paste()
    try:
        pyautogui.hotkey("ctrl", "l")
        pyperclip.copy(url)
        pyautogui.hotkey("ctrl", "v")
        pyautogui.press("enter")
    except Exception as exc:
        return ToolResult("failure", f"Could not navigate {app_name}: {exc}")
    finally:
        pyperclip.copy(previous_clipboard)

    expected_markers = {expected.lower(), urlparse(url).hostname.lower().removeprefix("www.")}
    deadline = time.monotonic() + max(3, config.BROWSER_NAVIGATION_TIMEOUT / 1000)
    latest_title = ""
    while time.monotonic() < deadline:
        active = get_active_window_info()
        latest_title = str(active.get("title", ""))
        if (
            active.get("pid") == before.get("pid")
            and str(active.get("application", "") or "").lower() in expected_processes
            and latest_title
        ):
            normalized_title = latest_title.lower()
            if any(marker and marker in normalized_title for marker in expected_markers):
                return ToolResult(
                    "success", f"Opened {expected} in {app_name}. Verified window: {latest_title}",
                    action="open_website_in_application", target=app_name, verification_status="verified",
                )
        time.sleep(0.25)
    return ToolResult(
        "failure", f"Sent the navigation to {app_name}, but couldn't verify that {expected} opened. Window title: {latest_title or 'unavailable'}",
        action="open_website_in_application", target=app_name, verification_status="failed",
    )


def open_website_in_application(name: str, target: str) -> ToolResult:
    website = resolve_target(target)
    if website is None:
        return ToolResult("clarification_required", f"I don't recognize the website '{target}'.")
    return _navigate_in_application(name, website.canonical_url, website.name)


def browser_open(target: str, browser: str = "") -> ToolResult:
    if browser:
        return open_website_in_application(browser, target)
    return _run_target(target, "open")


def browser_interaction(target: str, query: str) -> ToolResult:
    return _run_target(target, "interact", query)


def play_youtube_song(query: str, avoid_current: bool = False, result_index: int = 0) -> ToolResult:
    target = resolve_target("youtube")

    if isinstance(avoid_current, str):
        normalized = avoid_current.strip().lower()
        if normalized not in {"true", "false", "1", "0", "yes", "no"}:
            return ToolResult("invalid_action", "avoid_current must be true or false.")
        avoid_current = normalized in {"true", "1", "yes"}
    if not isinstance(avoid_current, bool):
        return ToolResult("invalid_action", "avoid_current must be true or false.")
    try:
        if result_index is None or (isinstance(result_index, str) and result_index.strip().lower() in {"", "none", "null"}):
            result_index = 0
        result_index = int(result_index)
    except (TypeError, ValueError):
        return ToolResult("invalid_action", "result_index must be a non-negative integer.")
    if result_index < 0:
        return ToolResult("invalid_action", "result_index must be a non-negative integer.")

    def execute():
        return adapter_for(get_browser_session(), target).play(query, avoid_current=avoid_current, result_index=result_index)

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


def inspect_current_media() -> ToolResult:
    """Report that live playback inspection is unavailable in external players."""
    return ToolResult(
        "failure",
        "I can't inspect live playback state yet. I can send a system media key, but I can't verify which item is playing.",
        action="inspect_current_media", verification_status="unknown",
    )


def inspect_current_page() -> ToolResult:
    """Live inspection of the user's external Brave window is not available."""
    return ToolResult(
        "failure", "I can't inspect the visible page in your Brave window yet.",
        action="inspect_current_page", verification_status="unknown",
    )


def control_media(action: str) -> ToolResult:
    action = action.strip().lower()
    if action not in {"pause", "resume", "toggle"}:
        return ToolResult("invalid_action", "Choose pause, resume, or toggle. To play requested content, provide its title.")
    session = get_browser_session()

    def execute():
        page = session.get_page("youtube_playback")
        if page is not None and not page.is_closed():
            adapter = adapter_for(session, resolve_target("youtube"))
            if action == "toggle":
                return adapter.toggle_playback()
            return adapter.set_playback(action)

        # There is no tracked JARVIS YouTube player, so fall back to the
        # system-wide media key and report that its target cannot be verified.
        from app.tools.media import media_control

        return media_control("play_pause")

    try:
        return session.run(execute)
    except Exception as exc:
        return ToolResult("failure", f"Could not control media playback: {exc}")


def search_in_application(name: str = "", query: str = "") -> ToolResult:
    if not name or not query:
        return ToolResult("clarification_required", "Tell me which browser to search in and what to search for.")
    app_name = resolve_application_name(name)
    if app_name not in {"brave", "chrome", "edge"}:
        return ToolResult("clarification_required", f"'{name}' is not a supported installed browser name.")
    opened = open_app(app_name)
    if opened.status != "success":
        return opened
    focused = focus_app(app_name)
    if focused.lower().startswith("error:"):
        return ToolResult("failure", focused)

    before = get_active_window_info()
    url = config.BROWSER_SEARCH_PROVIDER.format(query=quote_plus(query))
    if re.search(r"\b(?:latest|recent|today|current|breaking|news)\b", query, re.I) and "google." in url:
        url += "&tbm=nws&tbs=qdr:m"
    previous_clipboard = pyperclip.paste()
    try:
        pyautogui.hotkey("ctrl", "l")
        pyperclip.copy(url)
        pyautogui.hotkey("ctrl", "v")
        pyautogui.press("enter")
    except Exception as exc:
        return ToolResult("failure", f"Could not submit the search to {app_name}: {exc}")
    finally:
        pyperclip.copy(previous_clipboard)

    deadline = time.monotonic() + max(3, config.BROWSER_NAVIGATION_TIMEOUT / 1000)
    while time.monotonic() < deadline:
        active = get_active_window_info()
        if active.get("pid") == before.get("pid") and query.lower() in active.get("title", "").lower():
            return ToolResult("success", f"Searched for '{query}' in {app_name}. Verified the results title: {active['title']}", verification_status="verified")
        time.sleep(0.25)
    return ToolResult("failure", f"The search was sent to {app_name}, but I could not verify a results page for '{query}'.")


register(Tool(
    name="open_url",
    description="Open an HTTP(S) website or URL in the managed visible Brave session. Use to bring a site up; success is reported only after navigation is verified. This is safe to retry after browser infrastructure failure.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}, "target": {"type": "string"}, "query": {"type": "string"}},
    },
    func=open_url,
    keywords=("open website", "navigate", "url", "website"),
    parallel_safe=True,
    resource="browser",
    capabilities=frozenset({"browser"}),
    side_effect=True,
    retry_safe=True,
))
register(Tool(
    name="search_web",
    description="Search the public internet and retrieve current external evidence as ranked titles, URLs, source names, and snippets. Use for explicit online research, current/latest/recent or externally verifiable facts, and whenever your knowledge is uncertain or insufficient. Do not claim to have searched unless this tool returns success; use its evidence when answering. This is knowledge search, not a search inside a named website.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    func=search_web,
    keywords=("search web", "web search", "search the internet", "look up online"),
    parallel_safe=True,
    resource="browser",
    capabilities=frozenset({"browser"}),
    side_effect=True,
    retry_safe=True,
))
register(Tool(
    name="fetch_web_page",
    description="Fetch and extract readable text from an HTTP(S) page URL, usually one returned by search_web. Use when search snippets do not provide enough evidence or when the user asks about a specific page. The result is bounded page text; it does not submit forms or change the page.",
    parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    func=fetch_web_page,
    keywords=("read web page", "fetch page", "open source", "inspect search result"),
    resource="internet",
    capabilities=frozenset({"browser"}),
    retry_safe=True,
))
register(Tool(
    name="open_and_remember_site",
    description="Open Wikipedia, YouTube, Google, GitHub, or Reddit in the user's real Brave browser and remember that site for a follow-up search.",
    parameters={
        "type": "object",
        "properties": {"site_name": {"type": "string", "enum": sorted(SITE_URLS)}},
        "required": ["site_name"],
    },
    func=open_and_remember_site,
    keywords=("open website", "remember site", "go to website"),
    resource="browser",
    capabilities=frozenset({"browser"}),
    side_effect=True,
    retry_safe=True,
))
register(Tool(
    name="browser_search",
    description="Search within an explicitly named website using its registered adapter, for example YouTube or Wikipedia. Use for site-specific searches; use search_web for general knowledge research and current facts. This is safe to retry after browser infrastructure failure.",
    parameters={
        "type": "object",
        "properties": {"target": {"type": "string"}, "query": {"type": "string"}},
        "required": ["target", "query"],
    },
    func=browser_search,
    keywords=("search website", "search site", "site search"),
    parallel_safe=True,
    resource="browser",
    capabilities=frozenset({"browser"}),
    side_effect=True,
    retry_safe=True,
))
register(Tool(
    name="browser_open",
    description="Open or navigate to a named website in JARVIS's managed visible Brave browser. The target must be a website such as YouTube, not a browser application such as Edge or Brave. Use open_app to launch a browser application. Use this for bringing a website up, not factual research; use search_web to retrieve evidence. Reports success only after verified navigation.",
    parameters={
        "type": "object",
        "properties": {"target": {"type": "string"}, "browser": {"type": "string", "enum": ["brave", "chrome", "edge"]}},
        "required": ["target"],
    },
    func=browser_open,
    keywords=("open website", "navigate to website"),
    parallel_safe=True,
    resource="browser",
    capabilities=frozenset({"browser"}),
    side_effect=True,
    retry_safe=True,
))
register(Tool(
    name="open_website_in_application",
    description="Navigate a named website in an explicitly named Brave, Chrome, or Edge window. Both the website target and browser application must be named by the request (for example, 'open YouTube in Edge'). The target must be a website, never a browser application; to launch Edge itself use open_app. Verifies the foreground process is the requested browser before typing and verifies the resulting window title. Repeating the same navigation is safe after infrastructure failure.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "enum": ["brave", "chrome", "edge"]}, "target": {"type": "string"}},
        "required": ["name", "target"],
    },
    func=open_website_in_application,
    keywords=("open in brave", "open in edge", "open in chrome", "navigate browser app"),
    resource="desktop",
    capabilities=frozenset({"browser", "windows"}),
    side_effect=True,
    retry_safe=True,
))
register(Tool(
    name="browser_interaction",
    description="Interact with controls on a named site in JARVIS's managed browser session, such as submitting a prompt to a supported web app. Use only when the user asks to interact with that site; general interaction in a separate external browser is unsupported. This may change page state, so do not retry it blindly.",
    parameters={
        "type": "object",
        "properties": {"target": {"type": "string"}, "query": {"type": "string"}},
        "required": ["target", "query"],
    },
    func=browser_interaction,
    keywords=("ask website", "interact with website", "prompt web app"),
    parallel_safe=True,
    resource="browser",
    capabilities=frozenset({"browser"}),
    side_effect=True,
))
register(Tool(
    name="play_youtube_song",
    description="Search YouTube for the requested song, artist, or video and start a matching result. Use when the user asks for playback; set avoid_current to skip the tracked result when they ask for a different one. Reports success only after the video is observed playing.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "avoid_current": {"type": "boolean", "description": "Skip the currently playing result when choosing another match."},
            "result_index": {"type": "integer", "minimum": 0, "maximum": 11, "description": "Zero-based position of the requested search result."},
        },
        "required": ["query"],
    },
    func=play_youtube_song,
    keywords=("play song", "play music", "play video", "music", "song", "video"),
    parallel_safe=True,
    resource="browser",
    capabilities=frozenset({"media"}),
    side_effect=True,
))
register(Tool(
    name="toggle_youtube_playback",
    description="Pause or resume the currently playing YouTube video.",
    parameters={"type": "object", "properties": {}},
    func=toggle_youtube_playback,
    keywords=("pause media", "resume media", "toggle playback"),
    resource="browser",
    capabilities=frozenset({"media"}),
    side_effect=True,
))
register(Tool(
    name="inspect_current_media",
    description="Inspect current playback state. Live playback inspection is not available for external media players.",
    parameters={"type": "object", "properties": {}},
    func=inspect_current_media,
    keywords=("currently playing", "current song", "what song", "playback state", "paused video"),
    capabilities=frozenset({"media", "live_state"}),
))
register(Tool(
    name="inspect_current_page",
    description="Inspect the visible page in the user's real Brave window. This capability is not currently available.",
    parameters={"type": "object", "properties": {}},
    func=inspect_current_page,
    keywords=("what page am i on", "current browser page", "active website", "visible page"),
    capabilities=frozenset({"browser", "live_state"}),
))
register(Tool(
    name="control_media",
    description="Pause or resume the tracked JARVIS YouTube video and verify its state; if no JARVIS YouTube video is tracked, use the system media key and report that the target cannot be verified. Use media_control for next, previous, or volume actions, and play_youtube_song for requested content.",
    parameters={
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["pause", "resume", "toggle"]}},
        "required": ["action"],
    },
    func=control_media,
    keywords=("pause", "resume", "playback", "media", "music", "video"),
    resource="browser",
    capabilities=frozenset({"media"}),
    side_effect=True,
))
register(Tool(
    name="search_in_application",
    description="Open or focus a named installed browser application, search for a query in its address bar, and verify the results title. Use only for explicit requests to search in Brave, Chrome, or Edge.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string"}, "query": {"type": "string"}},
        "required": ["name", "query"],
    },
    func=search_in_application,
    keywords=("search browser app", "search brave", "search chrome", "search edge"),
    parallel_safe=True,
    resource="desktop",
    capabilities=frozenset({"browser", "windows"}),
    side_effect=True,
))
