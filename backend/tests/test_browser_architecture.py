import threading

import app.tools.browser_session as session_module
from app.agent.router import _open_target_or_app
from app.tools.browser_adapters import ChatAdapter, GenericTargetAdapter
from app.tools.browser_session import BrowserSession
from app.tools.browser_targets import browser_search_url, resolve_target
from app.tools.registry import ToolResult


class FakePage:
    def __init__(self, url="about:blank", content=""):
        self.url = url
        self._content = content
        self.closed = False

    def is_closed(self):
        return self.closed

    def goto(self, url, timeout=None):
        self.url = url

    def content(self):
        return self._content


class FakeSession:
    def __init__(self, page):
        self._page = page

    def page(self, key, url=None):
        if url:
            self._page.goto(url)
        return self._page


def test_browser_session_serializes_on_one_owner_thread():
    session = BrowserSession()
    try:
        thread_ids = [session.run(threading.get_ident) for _ in range(3)]
        assert len(set(thread_ids)) == 1
    finally:
        session.shutdown()


def test_browser_session_shutdown_is_explicit_and_idempotent():
    session = BrowserSession()
    session.shutdown()
    session.shutdown()
    assert session._closed is True


def test_browser_session_recovers_from_stale_context(monkeypatch):
    class DeadContext:
        @property
        def pages(self):
            raise RuntimeError("closed")

    class FreshContext:
        pages = []

    class Chromium:
        def launch_persistent_context(self, *args, **kwargs):
            return FreshContext()

    class FakePlaywright:
        chromium = Chromium()

        def stop(self):
            pass

    class FakePlaywrightManager:
        def start(self):
            return FakePlaywright()

    session = BrowserSession()
    session._context = DeadContext()
    monkeypatch.setattr(session_module, "sync_playwright", FakePlaywrightManager)
    try:
        assert session._ensure_context().__class__ is FreshContext
    finally:
        session.shutdown()


def test_target_resolution_and_aliases_are_data_driven():
    assert resolve_target("Chat GPT").name == "chatgpt"
    assert resolve_target("YT").name == "youtube"
    assert resolve_target("https://example.com").canonical_url == "https://example.com"
    assert resolve_target("ExampleSite") is None


def test_unknown_open_target_does_not_fall_back_to_open_app():
    assert _open_target_or_app("ExampleSite") == ("browser_open", {"target": "ExampleSite"})


def test_url_based_search_encodes_query():
    target = resolve_target("wikipedia")
    url = browser_search_url(target, "Python decorators & tips")
    assert "Python+decorators+%26+tips" in url


def test_target_without_search_capability_is_unsupported():
    target = resolve_target("example.com")
    result = GenericTargetAdapter(FakeSession(FakePage("https://example.com")), target).search("anything")
    assert result.status == "invalid_action"
    assert "unsupported" in result.message.lower()


def test_generic_adapter_contract_verifies_open_success():
    target = resolve_target("wikipedia")
    page = FakePage()
    result = GenericTargetAdapter(FakeSession(page), target).open()
    assert result == ToolResult("success", "Opened wikipedia.")


def test_generic_adapter_reports_open_failure():
    target = resolve_target("wikipedia")
    page = FakePage()
    page.goto = lambda url, timeout=None: None
    result = GenericTargetAdapter(FakeSession(page), target).open()
    assert result.status == "failure"


def test_generic_adapter_reports_captcha():
    target = resolve_target("wikipedia")
    page = FakePage(content="Please verify you are human")
    result = GenericTargetAdapter(FakeSession(page), target).open()
    assert result.status == "failure"
    assert "captcha" in result.message.lower()


def test_generic_engine_has_no_youtube_or_whatsapp_selectors():
    browser_source = open("app/tools/browser.py", encoding="utf-8").read().lower()
    whatsapp_source = open("app/tools/whatsapp.py", encoding="utf-8").read().lower()
    assert "ytd-video-renderer" not in browser_source
    assert "data-tab" not in whatsapp_source


def test_tool_result_supports_authentication_state():
    result = ToolResult("authentication_required", "Please log in")
    assert result.status == "authentication_required"


def test_chat_adapter_reports_login_before_interaction():
    target = resolve_target("chatgpt")
    page = FakePage(content="Log in to continue")

    class Locator:
        count = lambda self: 1
        wait_for = lambda self, **kwargs: None
        fill = lambda self, value: None
        press = lambda self, key: None
        inner_text = lambda self, **kwargs: page._content

        @property
        def first(self):
            return self

    page.locator = lambda selector: Locator()
    result = ChatAdapter(FakeSession(page), target).open()
    assert result.status == "authentication_required"
