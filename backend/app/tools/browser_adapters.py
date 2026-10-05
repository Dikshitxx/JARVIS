from abc import ABC, abstractmethod
import re
from urllib.parse import quote_plus
from urllib.parse import urlparse

from app.core import config
from app.tools.browser_targets import BrowserTarget, target_matches_url
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
        if "interact" in self.target.capabilities:
            return self.interact(query)
        if "search" in self.target.capabilities and self.target.search_url:
            url = self.target.search_url.format(query=quote_plus(query))
            return self._navigate_and_verify(url, "search")

        # New URL targets need no registered site entry: try the page's
        # standard search controls before reporting that the capability is absent.
        page = self.session.page(self.target.name, self.target.canonical_url)
        challenge = check_challenge(page)
        if challenge:
            return challenge
        start_url = page.url
        selectors = (
            "input[type='search']", "[role='searchbox']",
            "input[placeholder*='search' i]", "input[aria-label*='search' i]",
        )
        for selector in selectors:
            try:
                field = page.locator(selector).first
                field.wait_for(state="visible", timeout=min(config.BROWSER_INTERACTION_TIMEOUT, 2500))
                field.fill(query)
                field.press("Enter")
                page.wait_for_timeout(500)
                if page.url != start_url:
                    return ToolResult("success", f"Searched {self.target.name} for: {query}")
            except Exception:
                continue
        return ToolResult("invalid_action", f"I opened {self.target.name}, but it has no usable search control that I can verify.")

    def _navigate_and_verify(self, url: str, operation: str) -> ToolResult:
        page = self.session.page(self.target.name, url)
        challenge = check_challenge(page)
        if challenge:
            return challenge
        if page.url == "about:blank":
            return ToolResult("failure", f"Could not verify {operation} on {self.target.name}.")
        return ToolResult("success", f"Searched {self.target.name}.", verification_status="verified")

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
        return ToolResult("success", f"Opened {self.target.name}.", verification_status="verified")

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
        return ToolResult("success", f"Searched {self.target.name} for: {query}", verification_status="verified")

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

    def play(self, query: str, avoid_current: bool = False, result_index: int = 0) -> ToolResult:
        page = self.session.page(self.target.name)
        previous_url = page.url
        current_page = self.session.get_page("youtube_playback")
        current_url = current_page.url if current_page is not None and not current_page.is_closed() else previous_url
        current_video = re.search(r"[?&]v=([^&]+)", current_url)
        page.goto(self.target.search_url.format(query=quote_plus(query)), timeout=config.BROWSER_NAVIGATION_TIMEOUT)
        try:
            results = page.locator("ytd-video-renderer a#video-title")
            results.first.wait_for(state="visible", timeout=config.BROWSER_INTERACTION_TIMEOUT)
            count = min(results.count(), 12)
            result = results.nth(min(max(result_index, 0), count - 1))
            if avoid_current:
                for index in range(min(result_index, count - 1), count):
                    candidate = results.nth(index)
                    href = candidate.get_attribute("href") or ""
                    candidate_video = re.search(r"[?&]v=([^&]+)", href)
                    if href and (not current_video or not candidate_video or candidate_video.group(1) != current_video.group(1)):
                        result = candidate
                        break
            title = (result.get_attribute("title") or result.inner_text()).strip()
            result.click()
            page.wait_for_selector("video", state="attached", timeout=config.BROWSER_INTERACTION_TIMEOUT)
        except Exception as exc:
            return ToolResult("failure", f"Could not select a YouTube result: {exc}")
        self.session.set_page("youtube_playback", page)
        playing = "() => { const video = document.querySelector('video'); return video && !video.paused && video.currentTime > 0; }"
        try:
            page.wait_for_function(playing, timeout=min(config.BROWSER_INTERACTION_TIMEOUT, 4000))
        except Exception:
            # YouTube occasionally leaves the selected result paused after
            # navigation. Request playback once and verify the actual element
            # state before reporting success.
            try:
                page.locator("video").first.evaluate(
                    "video => video.paused ? video.play().then(() => true).catch(() => false) : true"
                )
                page.wait_for_function(playing, timeout=min(config.BROWSER_INTERACTION_TIMEOUT, 8000))
            except Exception:
                return ToolResult(
                    "failure",
                    f"Opened {title or query} on YouTube, but playback did not start after one retry.",
                    data={"media_title": title or query, "url": page.url},
                    verification_status="failed",
                )
        return ToolResult("success", f"Playing {title or query} on YouTube.", data={"media_title": title or query, "url": page.url}, verification_status="verified")

    def toggle_playback(self) -> ToolResult:
        page = self.session.get_page("youtube_playback")
        if page is None or page.is_closed():
            return ToolResult("failure", "No YouTube video is currently tracked.")
        try:
            paused = bool(page.locator("video").first.evaluate("video => video.paused"))
            return self.set_playback("resume" if paused else "pause")
        except Exception as exc:
            return ToolResult("failure", f"Could not control YouTube playback: {exc}")

    def set_playback(self, action: str) -> ToolResult:
        page = self.session.get_page("youtube_playback")
        if page is None or page.is_closed():
            return ToolResult("failure", "No YouTube video is currently tracked.")
        try:
            video = page.locator("video").first
            paused = bool(video.evaluate("video => video.paused"))
            should_pause = action == "pause"
            if paused == should_pause:
                state = "paused" if paused else "playing"
                return ToolResult("success", f"The current YouTube video is already {state}.", verification_status="verified")
            page.keyboard.press("k")
            page.wait_for_function(
                "(shouldPause) => { const video = document.querySelector('video'); return video && video.paused === shouldPause; }",
                arg=should_pause,
                timeout=config.BROWSER_INTERACTION_TIMEOUT,
            )
            state = "paused" if should_pause else "playing"
            return ToolResult("success", f"YouTube playback is {state}.", verification_status="verified")
        except Exception as exc:
            return ToolResult("failure", f"Could not verify YouTube {action}: {exc}")


class ChatAdapter(GenericTargetAdapter):
    _COMPOSER_SELECTORS = (
        "#prompt-textarea",
        "[data-testid='composer-text-input']",
        "[contenteditable='true'][data-placeholder*='Message' i]",
        "textarea",
        "input[type='text']",
        "[contenteditable='true']",
    )

    def _pages(self):
        if hasattr(self.session, "current_pages"):
            return self.session.current_pages()
        if hasattr(self.session, "existing_pages"):
            return self.session.existing_pages()
        return []

    def _select_page(self, *, create: bool = False):
        pages = [
            item for item in self._pages()
            if target_matches_url(self.target, str(getattr(item["page"], "url", "")))
        ]
        preferred = next((item for item in pages if item.get("key") == self.target.name), None)
        if preferred:
            return preferred["page"], ""
        if len(pages) == 1:
            return pages[0]["page"], ""
        if len(pages) > 1:
            return None, f"More than one {self.target.name} tab is open. Specify which one to use."
        if create:
            return self.session.page(self.target.name, self.target.canonical_url), ""
        return None, f"I couldn't find an already-open {self.target.name} tab. I didn't type anything."

    def _composer(self, page):
        for selector in self._COMPOSER_SELECTORS:
            try:
                field = page.locator(selector).first
                if not field.count():
                    continue
                field.wait_for(state="visible", timeout=min(config.BROWSER_INTERACTION_TIMEOUT, 2500))
                if hasattr(field, "is_enabled") and not field.is_enabled():
                    continue
                return field
            except Exception:
                continue
        return None

    @staticmethod
    def _field_text(field) -> str | None:
        try:
            return field.input_value(timeout=1000)
        except Exception:
            try:
                return field.inner_text(timeout=1000)
            except Exception:
                return None

    def open(self) -> ToolResult:
        page, error = self._select_page(create=True)
        if error:
            return ToolResult("clarification_required", error)
        challenge = check_challenge(page)
        if challenge:
            return challenge
        body = page.locator("body").inner_text(timeout=config.BROWSER_INTERACTION_TIMEOUT).lower()
        if any(marker in body for marker in ("log in", "sign in", "login")):
            return ToolResult("authentication_required", f"{self.target.name} requires login before interaction.")
        if self._composer(page) is None:
            return ToolResult("failure", f"{self.target.name} did not expose a usable conversation input.")
        return ToolResult("success", f"Opened {self.target.name}.", verification_status="verified")

    def type_text(self, text: str) -> ToolResult:
        page, error = self._select_page()
        if error:
            return ToolResult("clarification_required", error, verification_status="failed")
        challenge = check_challenge(page)
        if challenge:
            return challenge
        field = self._composer(page)
        if field is None:
            body = page.locator("body").inner_text(timeout=config.BROWSER_INTERACTION_TIMEOUT).lower()
            if any(marker in body for marker in ("log in", "sign in", "login")):
                return ToolResult("authentication_required", f"{self.target.name} requires login before interaction.")
            return ToolResult("failure", f"I couldn't find a visible input in the open {self.target.name} tab.", verification_status="failed")
        try:
            field.fill(text)
            if self._field_text(field) == text:
                return ToolResult(
                    "success", f"Typed and verified {len(text)} characters in the open {self.target.name} tab.",
                    target=self.target.name, verification_status="verified",
                )
            return ToolResult(
                "failure", f"The text did not match the input in the open {self.target.name} tab.",
                target=self.target.name, verification_status="failed",
            )
        except Exception as exc:
            return ToolResult("failure", f"Could not type into the open {self.target.name} tab: {exc}", verification_status="failed")

    def interact(self, query: str) -> ToolResult:
        ready = self.open()
        if ready.status != "success":
            return ready
        page, error = self._select_page()
        if error:
            return ToolResult("clarification_required", error)
        field = self._composer(page)
        if field is None:
            return ToolResult("failure", f"I couldn't find a usable input in {self.target.name}.", verification_status="failed")
        try:
            field.fill(query)
            if self._field_text(field) != query:
                return ToolResult("failure", f"I couldn't verify the prompt in {self.target.name}'s input.", verification_status="failed")
            field.press("Enter")
            page.wait_for_function(
                "query => Array.from(document.querySelectorAll('main *')).some(element => "
                "element.children.length === 0 && element.innerText?.trim() === query && "
                "!element.closest('[contenteditable=true], textarea, input'))",
                arg=query,
                timeout=config.BROWSER_INTERACTION_TIMEOUT,
            )
            return ToolResult(
                "success", f"Sent and verified the message in {self.target.name}.",
                target=self.target.name, verification_status="verified",
            )
        except Exception:
            return ToolResult(
                "failure", f"I submitted the prompt to {self.target.name}, but couldn't verify it appeared in the conversation.",
                target=self.target.name, verification_status="failed",
            )

    def search(self, query: str) -> ToolResult:
        return self.interact(query)


def adapter_for(session, target: BrowserTarget) -> BrowserTargetAdapter:
    if target.adapter == "youtube":
        return YouTubeAdapter(session, target)
    if target.adapter == "chat":
        return ChatAdapter(session, target)
    return GenericTargetAdapter(session, target)
