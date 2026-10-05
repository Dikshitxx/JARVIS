import threading
from types import SimpleNamespace

import pytest

import app.tools.browser_session as session_module
from app.agent.router import _open_target_or_app
from app.tools.browser_adapters import ChatAdapter, GenericTargetAdapter, YouTubeAdapter
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


def test_browser_session_recovery_replaces_the_stale_session(monkeypatch):
    class OldSession:
        closed = False

        def shutdown(self):
            self.closed = True

    old = OldSession()
    replacement = object()
    monkeypatch.setattr(session_module, "_SESSION", old)
    monkeypatch.setattr(session_module, "BrowserSession", lambda: replacement)

    assert session_module.recover_browser_session() is True
    assert old.closed is True
    assert session_module.get_browser_session() is replacement


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
    assert _open_target_or_app("ExampleSite") == ("browser_open", {"target": ""})


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
    assert result == ToolResult("success", "Opened wikipedia.", verification_status="verified")


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


def test_youtube_adapter_retries_playback_once_and_verifies_state():
    class VideoLocator:
        def __init__(self, page):
            self.page = page
            self.first = self

        def evaluate(self, _script):
            self.page.play_requested = True
            return True

    class ResultLocator:
        def __init__(self, page):
            self.page = page
            self.first = self

        def wait_for(self, **_kwargs):
            return None

        def count(self):
            return 1

        def nth(self, _index):
            return self

        def get_attribute(self, name):
            return "Ram Ram | MC SQUARE | Hustle 2.0" if name == "title" else "/watch?v=ram123"

        def inner_text(self):
            return "Ram Ram | MC SQUARE | Hustle 2.0"

        def click(self):
            self.page.url = "https://www.youtube.com/watch?v=ram123"

    class PlaybackPage(FakePage):
        def __init__(self):
            super().__init__()
            self.play_requested = False
            self.wait_calls = 0

        def locator(self, selector):
            if selector == "video":
                return VideoLocator(self)
            return ResultLocator(self)

        def wait_for_selector(self, *_args, **_kwargs):
            return None

        def wait_for_function(self, *_args, **_kwargs):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise TimeoutError("autoplay did not start")
            if not self.play_requested:
                raise TimeoutError("video still paused")

    class PlaybackSession(FakeSession):
        def __init__(self, page):
            super().__init__(page)
            self.pages = {}

        def get_page(self, key):
            return self.pages.get(key)

        def set_page(self, key, page):
            self.pages[key] = page

    page = PlaybackPage()
    session = PlaybackSession(page)
    result = YouTubeAdapter(session, resolve_target("youtube")).play("Ram Ram from Hustle 2.0")

    assert result.status == "success"
    assert result.verification_status == "verified"
    assert page.play_requested is True
    assert page.wait_calls == 2


def test_generic_engine_has_no_youtube_or_whatsapp_selectors():
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    browser_source = (app_dir / "tools" / "browser.py").read_text(encoding="utf-8").lower()
    whatsapp_source = (app_dir / "tools" / "whatsapp.py").read_text(encoding="utf-8").lower()
    assert "ytd-video-renderer" not in browser_source
    assert "data-tab" not in whatsapp_source


def test_tool_result_supports_authentication_state():
    result = ToolResult("authentication_required", "Please log in")
    assert result.status == "authentication_required"


def test_environment_observation_does_not_start_managed_browser(monkeypatch):
    from app.tools.apps import inspect_environment
    import app.tools.browser_session as browser_session

    monkeypatch.setattr("app.tools.apps.get_active_window_info", lambda: {"title": "JARVIS - Notes", "application": "notepad.exe", "pid": 42})
    session = browser_session.BrowserSession()
    monkeypatch.setattr(browser_session, "get_browser_session", lambda: session)
    monkeypatch.setattr(browser_session, "sync_playwright", lambda: pytest.fail("snapshot unexpectedly started Playwright"))

    try:
        result = inspect_environment(force_refresh=True)
    finally:
        session.shutdown()
    assert result.status == "success"
    assert result.data["active_window"]["title"] == "JARVIS - Notes"
    assert result.data["browser"] == {"count": 0, "pages": [], "visible_page": None}
    assert "observed_at" in result.data


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


def test_generic_open_website_uses_registered_direct_route(monkeypatch):
    from app.agent import agent as agent_module
    from app.agent import runtime_context
    from app.tools.registry import REGISTRY

    runtime_context.update_context(current_browser="", current_target="", browser_target="")
    exposed = []

    def fake_chat(_messages, tools=None, **_kwargs):
        exposed.extend(schema["function"]["name"] for schema in tools or [])
        return SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=SimpleNamespace(
            name="browser_open", arguments={"target": "youtube"},
        ))])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    monkeypatch.setattr(REGISTRY["browser_open"], "func", lambda target: ToolResult(
        "success", f"Opened {target}.", verification_status="verified",
    ))
    monkeypatch.setattr(runtime_context, "record_action", lambda *_args, **_kwargs: {})

    agent = agent_module.Agent()
    reply = agent.respond("Open YouTube")

    assert reply == "Opened youtube."
    assert exposed == []


def test_edge_is_registered_as_a_local_launchable_and_closable_application():
    from app.core import config
    from app.tools.apps import CLOSE_PROCESS_NAMES, _process_names, resolve_application_name

    assert resolve_application_name("Microsoft Edge") == "edge"
    assert "edge" in config.ALLOWED_APPS
    assert CLOSE_PROCESS_NAMES["edge"] == ["msedge.exe"]
    assert "msedge.exe" in _process_names("edge")


def test_application_inspection_distinguishes_background_process_from_open_window(monkeypatch):
    import sys
    from types import SimpleNamespace

    import app.tools.apps as apps

    class FakeDesktop:
        def __init__(self, backend):
            assert backend == "uia"

        def windows(self):
            return []

    monkeypatch.setitem(sys.modules, "pywinauto", SimpleNamespace(Desktop=FakeDesktop))
    monkeypatch.setattr(apps, "_matching_processes", lambda _targets: [object()])

    result = apps.inspect_application("edge")

    assert result.status == "success"
    assert result.data["is_open"] is False
    assert result.data["is_running"] is True
    assert "no open window detected" in result.message
    assert "process(es) are still running" in result.message


def test_navigation_is_refused_if_requested_browser_does_not_have_focus(monkeypatch):
    import app.tools.browser as browser
    from app.tools.registry import ToolResult

    monkeypatch.setattr(browser, "open_app", lambda _name: ToolResult("success", "Edge open."))
    monkeypatch.setattr(browser, "focus_app", lambda _name: "Focused edge: Microsoft Edge")
    monkeypatch.setattr(browser, "get_active_window_info", lambda: {
        "title": "JARVIS | System Interface - Brave", "application": "brave.exe", "pid": 42,
    })
    sent = []
    monkeypatch.setattr(browser.pyautogui, "hotkey", lambda *args: sent.append(args))

    result = browser._navigate_in_application("edge", "https://www.youtube.com", "YouTube")

    assert result.status == "failure"
    assert "I did not send navigation keystrokes" in result.message
    assert sent == []


def test_youtube_playback_normalizes_model_null_result_index(monkeypatch):
    import app.tools.browser as browser
    from app.tools.registry import ToolResult

    observed = []

    class InlineSession:
        def run(self, callback):
            return callback()

    class FakeAdapter:
        def play(self, query, *, avoid_current, result_index):
            observed.append((query, avoid_current, result_index))
            return ToolResult("success", "Playing the selected YouTube result.", verification_status="verified")

    monkeypatch.setattr(browser, "get_browser_session", lambda: InlineSession())
    monkeypatch.setattr(browser, "adapter_for", lambda *_args: FakeAdapter())

    result = browser.play_youtube_song("NJk songs", avoid_current="false", result_index="null")

    assert result.status == "success"
    assert observed == [("NJk songs", False, 0)]
