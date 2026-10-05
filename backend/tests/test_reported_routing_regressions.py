from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agent import agent as agent_module
from app.agent.agent import Agent
from app.agent.request import build_user_request
from app.main import app as api_app
from app.core import config
from app.memory import store
from app.tools import browser
from app.tools.browser_adapters import ChatAdapter
from app.tools.registry import REGISTRY, Tool, ToolResult


@pytest.fixture
def isolated_agent(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jarvis-test.db")
    store.clear_runtime_context()
    monkeypatch.setattr(agent_module.store, "recent_messages", lambda *_args: [])
    monkeypatch.setattr(agent_module.store, "add_message", lambda *_args: None)
    monkeypatch.setattr(agent_module.runtime_context, "record_action", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(agent_module.runtime_context, "finish_task", lambda *_args: None)
    monkeypatch.setattr("app.tools.registry._memory_store.log_tool_execution", lambda *_args, **_kwargs: None)


@pytest.mark.parametrize("text", [
    "tell me about my system status",
    "can you tell me about my systame status?",
    "telll me about my system status",
])
def test_system_status_uses_registry_tool_without_a_model(isolated_agent, monkeypatch, text):
    calls = []
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: calls.append("model") or (_ for _ in ()).throw(RuntimeError("providers unavailable")))
    monkeypatch.setattr(REGISTRY["get_system_info"], "func", lambda: ToolResult(
        "success", "RAM: 7 GB used. CPU: 20%.", verification_status="verified",
    ))

    reply = Agent().respond(text)

    assert reply == "RAM: 7 GB used. CPU: 20%."
    assert calls == []


def test_system_status_chat_endpoint_does_not_return_500(isolated_agent, monkeypatch):
    monkeypatch.setattr(config, "API_SECRET", "test-secret")
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("providers unavailable")))
    monkeypatch.setattr(REGISTRY["get_system_info"], "func", lambda: ToolResult(
        "success", "RAM: 7 GB used. CPU: 20%.", verification_status="verified",
    ))

    response = TestClient(api_app).post(
        "/chat",
        headers={"X-Jarvis-Secret": "test-secret"},
        json={"message": "tell me about my system status", "background": False},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"
    assert "RAM: 7 GB" in response.json()["reply"]


@pytest.mark.parametrize(
    ("text", "intent", "query"),
    [
        ("okay can you search for the developer jobs for me?", "search_web", "developer jobs"),
        ("tell me about the PM of Nepal", "search_web", "PM of Nepal"),
    ],
)
def test_public_information_requests_have_a_deterministic_search_query(text, intent, query):
    request = build_user_request(text)

    assert request.intent == intent
    assert request.query.casefold() == query.casefold()


def test_open_chatgpt_uses_browser_tool_without_a_model(isolated_agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: calls.append("model") or (_ for _ in ()).throw(RuntimeError("providers unavailable")))
    monkeypatch.setattr(REGISTRY["browser_open"], "func", lambda target, browser="": ToolResult(
        "success", f"Opened {target}.", verification_status="verified",
    ))

    reply = Agent().respond("can you open chat gpt for me?")

    assert reply == "Opened chatgpt."
    assert calls == []


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("okay can you search for the developer jobs for me?", "developer jobs"),
        ("tell me about the PM of Nepal", "PM of Nepal"),
    ],
)
def test_public_search_executes_without_a_model(isolated_agent, monkeypatch, text, query):
    calls = []
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: pytest.fail("direct search must not call a model"))
    monkeypatch.setattr(REGISTRY["search_web"], "func", lambda query: calls.append(query) or ToolResult(
        "success", f"Retrieved results for {query}.", verification_status="verified",
    ))

    reply = Agent().respond(text)

    assert calls == [query]
    assert query in reply


def test_weather_location_transcript_falls_back_to_search_without_weather_tool(isolated_agent, monkeypatch):
    calls = []
    weather_tool = REGISTRY.pop("get_weather", None)

    def fake_chat(messages, tools=None):
        system = messages[0]["content"]
        if "Classify these two messages" in system:
            return SimpleNamespace(content='{"user_requires_tool":true,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}', tool_calls=[])
        if "requested_deliverable_complete" in system:
            return SimpleNamespace(content='{"requested_deliverable_complete":true}', tool_calls=[])
        if tools == []:
            return SimpleNamespace(content='{"user_requires_tool":false,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}', tool_calls=[])
        if any(item.get("role") == "tool" for item in messages):
            query = next(item["content"] for item in messages if item.get("role") == "user")
            return SimpleNamespace(content=f"Retrieved current weather results for {query}.", tool_calls=[])
        query = next(item["content"] for item in messages if item.get("role") == "user")
        return SimpleNamespace(content="", tool_calls=[SimpleNamespace(
            function=SimpleNamespace(name="search_web", arguments={"query": query}),
        )])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    monkeypatch.setattr(REGISTRY["search_web"], "func", lambda query: calls.append(query) or ToolResult(
        "success", f"Retrieved results for {query}.", verification_status="verified",
    ))

    try:
        first = Agent().respond("current weather in kathmandu")
        second = Agent().respond("kathmandu")
    finally:
        if weather_tool is not None:
            REGISTRY["get_weather"] = weather_tool

    assert calls == ["current weather in kathmandu", "kathmandu"]
    assert "current weather in kathmandu" in first
    assert "kathmandu" in second


def test_conversational_followup_after_unverified_result_is_not_blocked(isolated_agent, monkeypatch):
    task_updates = []
    store.update_runtime_context(
        last_action={
            "tool": "type_text",
            "args": {"target_window": "Notepad"},
            "status": "success",
            "verification_status": "unknown",
            "result": "Sent text to Notepad. I couldn't verify that it took effect.",
        },
        recent_turns=[{
            "user": "type hello in notepad",
            "assistant": "Sent text to Notepad. I couldn't verify that it took effect.",
            "intent": "action",
        }],
    )

    calls = 0

    def fake_chat(_messages, tools=None, **_kwargs):
        nonlocal calls
        calls += 1
        if calls > 1:
            pytest.fail("plain conversational follow-up must not be converted into a BLOCKED action")
        assert tools == []
        return SimpleNamespace(content="Because the app did not expose a readable confirmation state.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    monkeypatch.setattr(agent_module, "_mark_current_task", lambda *args: task_updates.append(args))

    reply = Agent().respond("why can't you verify it")

    assert reply == "Because the app did not expose a readable confirmation state."
    assert [update for update in task_updates if update[0] == "BLOCKED"] == []


def test_close_tab_uses_the_current_browser_target_without_a_model(isolated_agent, monkeypatch):
    calls = []
    context = {"current_target": "youtube_playback", "recent_turns": []}
    close_tool = Tool(
        name="close_browser_tab",
        description="Close one JARVIS-managed browser tab.",
        parameters={"type": "object", "properties": {"target": {"type": "string"}}},
        func=lambda target: ToolResult("success", f"Closed {target}.", verification_status="verified"),
        capabilities=frozenset({"browser"}),
        side_effect=True,
        metadata={
            "direct_routes": {"close_browser_tab": {"target": "$context.current_target"}},
            "offline_summary": "close one tracked browser tab after confirmation",
        },
    )
    monkeypatch.setitem(REGISTRY, "close_browser_tab", close_tool)
    from app.permissions.classify import CONFIRM_TOOLS
    monkeypatch.setattr(
        "app.permissions.classify.CONFIRM_TOOLS", {*CONFIRM_TOOLS, "close_browser_tab"},
    )
    monkeypatch.setattr(agent_module.runtime_context, "get_context", lambda: context)
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: calls.append("model") or (_ for _ in ()).throw(RuntimeError("providers unavailable")))
    monkeypatch.setattr(REGISTRY["close_browser_tab"], "func", lambda target: ToolResult(
        "success", f"Closed {target}.", verification_status="verified",
    ))

    reply = Agent().respond("close that tab")

    assert "should i close browser tab" in reply.lower()
    assert calls == []


def test_say_hello_to_chatgpt_waits_for_confirmation_without_a_model(isolated_agent, monkeypatch):
    calls = []
    assistant = Agent()
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: calls.append("model") or (_ for _ in ()).throw(RuntimeError("providers unavailable")))

    reply = assistant.respond("now say hello to chat gpt")

    assert "should i interact with chatgpt" in reply.lower()
    assert assistant.pending[0] == "browser_interaction"
    assert calls == []


def test_chatgpt_type_request_uses_the_open_tab_without_submitting(isolated_agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: calls.append("model") or (_ for _ in ()).throw(RuntimeError("providers unavailable")))
    monkeypatch.setattr(REGISTRY["browser_type_text"], "func", lambda target, text: calls.append((target, text)) or ToolResult(
        "success", f"Typed and verified {len(text)} characters in {target}.", verification_status="verified",
    ))

    reply = Agent().respond("just simply type hello chat gpt in my opened chatgpt tab")

    assert "typed and verified" in reply.lower()
    assert calls == [("chatgpt", "hello chat gpt")]


def test_capability_answer_is_registry_derived_and_model_independent(isolated_agent, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: calls.append("model") or (_ for _ in ()).throw(RuntimeError("providers unavailable")))

    reply = Agent().respond("what can you do for me for now?")

    assert "system status" in reply.lower()
    assert "web search" in reply.lower()
    assert "terminal" not in reply.lower()
    assert calls == []


class _FakeField:
    def __init__(self):
        self.value = ""
        self.pressed = []
        self.first = self

    def count(self):
        return 1

    def wait_for(self, **_kwargs):
        return None

    def is_visible(self):
        return True

    def is_enabled(self):
        return True

    def fill(self, value):
        self.value = value

    def input_value(self, **_kwargs):
        return self.value

    def inner_text(self, **_kwargs):
        return self.value

    def press(self, key):
        self.pressed.append(key)


class _FakePage:
    def __init__(self, url):
        self.url = url
        self.field = _FakeField()
        self.closed = False

    def is_closed(self):
        return self.closed

    def locator(self, _selector):
        return self.field

    def close(self):
        self.closed = True


class _FakeBrowserSession:
    def __init__(self, pages):
        self.pages = pages

    def existing_pages(self):
        return [{"key": key, "page": page} for key, page in self.pages]


def test_chatgpt_type_fills_the_open_composer_without_submitting():
    page = _FakePage("https://chatgpt.com/?model=gpt-4o")
    adapter = ChatAdapter(_FakeBrowserSession([("browser_navigation", page)]), __import__(
        "app.tools.browser_targets", fromlist=["resolve_target"],
    ).resolve_target("chatgpt"))

    result = adapter.type_text("hello")

    assert result.status == "success"
    assert result.verification_status == "verified"
    assert page.field.value == "hello"
    assert page.field.pressed == []


def test_chatgpt_type_asks_when_multiple_matching_tabs_are_open():
    first = _FakePage("https://chatgpt.com/")
    second = _FakePage("https://chat.openai.com/")
    adapter = ChatAdapter(_FakeBrowserSession([("page:1", first), ("page:2", second)]), __import__(
        "app.tools.browser_targets", fromlist=["resolve_target"],
    ).resolve_target("chatgpt"))

    result = adapter.type_text("hello")

    assert result.status == "clarification_required"
    assert first.field.value == second.field.value == ""


def test_browser_tab_close_selects_and_verifies_one_tracked_page(monkeypatch):
    class FakeSession:
        def __init__(self, pages):
            self.pages = pages

        def run(self, callback):
            return callback()

        def current_pages(self):
            return [{"key": key, "page": page} for key, page in self.pages]

    video = _FakePage("https://www.youtube.com/watch?v=abc")
    other = _FakePage("https://chatgpt.com/")
    monkeypatch.setattr(browser, "get_browser_session", lambda: FakeSession([
        ("youtube_playback", video), ("browser_navigation", other),
    ]))

    result = browser.close_browser_tab("youtube_playback")

    assert result.status == "success"
    assert result.verification_status == "verified"
    assert video.closed is True
    assert other.closed is False


def test_chatgpt_navigation_accepts_openai_login_redirect_but_rejects_other_hosts(monkeypatch):
    class FakeSession:
        def __init__(self, actual_url):
            self.actual_url = actual_url

        def run(self, callback):
            return callback()

        def page(self, _key, _url):
            return SimpleNamespace(url=self.actual_url)

    monkeypatch.setattr(browser, "get_browser_session", lambda: FakeSession(
        "https://auth.openai.com/log-in?continue=%2Fchatgpt",
    ))
    redirected = browser._launch_brave("https://chatgpt.com", "open_url")
    assert redirected.status == "success"
    assert redirected.verification_status == "verified"

    monkeypatch.setattr(browser, "get_browser_session", lambda: FakeSession("https://example.net/"))
    unrelated = browser._launch_brave("https://chatgpt.com", "open_url")
    assert unrelated.status == "failure"
    assert unrelated.verification_status == "failed"
