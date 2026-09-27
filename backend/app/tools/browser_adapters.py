from abc import ABC, abstractmethod
from urllib.parse import quote_plus
from urllib.parse import urlparse

from app.core import config
from app.tools.browser_targets import BrowserTarget
from app.tools.registry import ToolResult


def check_challenge(page) -> ToolResult | None:
    try:
        if hasattr(page, "locator"):
            content = page.locator("body").inner_text(timeout=config.BROWSER_INTERACTION_TIMEOUT).lower()
        else:
            content = page.content().lower()
        if any(marker in content for marker in ("captcha", "unusual traffic", "verify you are human", "security verification", "cloudflare")):
            return ToolResult("failure", "This page is showing a CAPTCHA or bot-verification challenge. Please solve it manually in the browser window, then try again.")
    except Exception:
        pass
    return None


class BrowserTargetAdapter(ABC):
    def __init__(self, session, target: BrowserTarget):
        self.session = session
        self.target = target

    @abstractmethod
    def open(self) -> ToolResult:
        raise NotImplementedError

    def search(self, query: str) -> ToolResult:
        return ToolResult("invalid_action", f"Search is unsupported for {self.target.name}.")

    def interact(self, query: str) -> ToolResult:
        return ToolResult("invalid_action", f"Interaction is unsupported for {self.target.name}.")

    def authentication_state(self, page) -> str:
        return "unknown"


class GenericTargetAdapter(BrowserTargetAdapter):
    def open(self) -> ToolResult:
        page = self.session.page(self.target.name, self.target.canonical_url)
        challenge = check_challenge(page)
        if challenge:
            return challenge
        if not page.url.startswith(self.target.canonical_url):
            return ToolResult("failure", f"Could not verify navigation to {self.target.name}.")
        return ToolResult("success", f"Opened {self.target.name}.")

    def search(self, query: str) -> ToolResult:
        if "search" not in self.target.capabilities or not self.target.search_url:
            return ToolResult("invalid_action", f"Search is unsupported for {self.target.name}.")
        url = self.target.search_url.format(query=quote_plus(query))
        page = self.session.page(self.target.name, url)
        challenge = check_challenge(page)
        if challenge:
            return challenge
        expected_host = urlparse(self.target.canonical_url).netloc.removeprefix("www.")
        actual_host = urlparse(page.url).netloc.removeprefix("www.")
        if page.url == "about:blank" or not (actual_host == expected_host or actual_host.endswith(f".{expected_host}")):
            return ToolResult("failure", f"Could not verify search navigation on {self.target.name}.")
        return ToolResult("success", f"Searched {self.target.name} for: {query}")

    def interact(self, query: str) -> ToolResult:
        if "interact" not in self.target.capabilities:
            return super().interact(query)
        page = self.session.page(self.target.name, self.target.canonical_url)
        selectors = self.target.selectors or ("textarea", "input[type='text']")
        for selector in selectors:
            field = page.locator(selector).first
            try:
                field.wait_for(state="visible", timeout=config.BROWSER_INTERACTION_TIMEOUT)
                field.fill(query)
                field.press("Enter")
                return ToolResult("success", f"Asked {self.target.name}: {query}")
            except Exception:
                continue
        if any(marker in page.content().lower() for marker in ("log in", "sign in", "login")):
            return ToolResult("authentication_required", f"{self.target.name} requires login before interaction.")
        return ToolResult("failure", f"Could not find a usable interaction control on {self.target.name}.")


class YouTubeAdapter(GenericTargetAdapter):
    def search(self, query: str) -> ToolResult:
        result = super().search(query)
        return result

    def play(self, query: str) -> ToolResult:
        page = self.session.page(self.target.name)
        page.goto(self.target.search_url.format(query=quote_plus(query)), timeout=config.BROWSER_NAVIGATION_TIMEOUT)
        try:
            result = page.locator("ytd-video-renderer a#video-title").first
            result.wait_for(state="visible", timeout=config.BROWSER_INTERACTION_TIMEOUT)
            result.click()
            page.wait_for_selector("video", state="attached", timeout=config.BROWSER_INTERACTION_TIMEOUT)
        except Exception as exc:
            return ToolResult("failure", f"Could not select a YouTube result: {exc}")
        self.session.set_page("youtube_playback", page)
        return ToolResult("success", f"Playing YouTube result for: {query}")

    def toggle_playback(self) -> ToolResult:
        page = self.session.get_page("youtube_playback")
        if page is None or page.is_closed():
            return ToolResult("failure", "No YouTube video is currently tracked.")
        try:
            page.keyboard.press("k")
            return ToolResult("success", "Toggled play/pause on the current YouTube video.")
        except Exception as exc:
            return ToolResult("failure", f"Could not control YouTube playback: {exc}")


class ChatAdapter(GenericTargetAdapter):
    def open(self) -> ToolResult:
        page = self.session.page(self.target.name, self.target.canonical_url)
        challenge = check_challenge(page)
        if challenge:
            return challenge
        body = page.locator("body").inner_text(timeout=config.BROWSER_INTERACTION_TIMEOUT).lower()
        if any(marker in body for marker in ("log in", "sign in", "login")):
            return ToolResult("authentication_required", f"{self.target.name} requires login before interaction.")
        if not page.locator("textarea, input[type='text']").count():
            return ToolResult("failure", f"{self.target.name} did not expose a usable conversation input.")
        return ToolResult("success", f"Opened {self.target.name}.")

    def interact(self, query: str) -> ToolResult:
        ready = self.open()
        if ready.status != "success":
            return ready
        return super().interact(query)


def adapter_for(session, target: BrowserTarget) -> BrowserTargetAdapter:
    if target.adapter == "youtube":
        return YouTubeAdapter(session, target)
    if target.adapter == "chat":
        return ChatAdapter(session, target)
    return GenericTargetAdapter(session, target)