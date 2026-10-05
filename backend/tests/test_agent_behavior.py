from types import SimpleNamespace

import pytest

from app.agent.agent import Agent
from app.agent.request import build_user_request
from app.core import config
from app.llm import client
from app.memory import store
from app.permissions.classify import classify
from app.tools import media
from app.tools.registry import NeedsConfirmation, REGISTRY, ToolResult, run_tool_result


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jarvis-test.db")


def _tool_call(name, arguments):
    return SimpleNamespace(
        content="",
        tool_calls=[SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))],
    )


def test_open_app_tool_call_executes_without_confirmation(monkeypatch, isolated_store):
    called = []
    from app.agent import agent as agent_module

    monkeypatch.setattr(agent_module.client, "chat", lambda *args, **kwargs: _tool_call("open_app", {"name": "notepad"}))
    monkeypatch.setattr(REGISTRY["open_app"], "func", lambda name: called.append(name) or ToolResult("success", "Opened Notepad.", verification_status="verified"))
    monkeypatch.setattr("app.agent.agent.runtime_context.record_action", lambda *args, **kwargs: {})

    request = build_user_request("open notepad")
    reply = Agent()._run_tool_loop(
        "open notepad", [{"role": "user", "content": "open notepad"}], request.analysis,
    )

    assert reply == "Opened Notepad."
    assert called == ["notepad"]


def test_close_app_tool_call_still_requires_confirmation(monkeypatch, isolated_store):
    monkeypatch.setattr(client, "chat", lambda *args, **kwargs: _tool_call("close_app", {"name": "notepad"}))
    agent = Agent()
    name, arguments = agent._tool_calls(client.chat([], tools=[]))[0]
    with pytest.raises(NeedsConfirmation):
        run_tool_result(name, arguments)


def test_non_english_action_uses_model_tool_selection(monkeypatch, isolated_store):
    from app.agent import agent as agent_module

    calls = []

    def fake_chat(_messages, tools=None, **_kwargs):
        assert "open_app" in {item["function"]["name"] for item in tools or []}
        return _tool_call("open_app", {"name": "notepad"})

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    monkeypatch.setattr(REGISTRY["open_app"], "func", lambda name: calls.append(name) or ToolResult(
        "success", "Notepad opened and verified.", verification_status="verified",
    ))
    monkeypatch.setattr(agent_module.runtime_context, "record_action", lambda *_args, **_kwargs: {})

    reply = Agent().respond("Por favor, abre el Bloc de notas.")

    assert calls == ["notepad"]
    assert reply == "Notepad opened and verified."


def test_unverified_plain_text_action_claim_is_replaced_with_truthful_status(monkeypatch, isolated_store):
    from app.agent import agent as agent_module

    def fake_chat(_messages, tools=None, **_kwargs):
        if tools == []:
            return SimpleNamespace(content='{"user_requires_tool":true,"assistant_claimed_unverified_result":true,"assistant_asked_clarification":false}', tool_calls=[])
        return SimpleNamespace(content="I opened Notepad.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    # Exercise the model fallback's claim guard directly; a confident local
    # open request now takes the deterministic registered-tool route.
    monkeypatch.setattr(agent_module, "try_fast_route", lambda *_args, **_kwargs: None)

    reply = Agent().respond("Open Notepad")

    assert reply == "I couldn't verify that with a tool result, so I haven't done or confirmed it."


def test_agent_loads_persisted_messages_on_construction(isolated_store):
    store.add_message("user", "hello")
    store.add_message("assistant", "Hi there.")

    assert Agent().history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there."},
    ]


def test_media_control_is_registered_and_callable(monkeypatch, isolated_store):
    pressed = []
    monkeypatch.setattr(media.pyautogui, "press", pressed.append)

    tool = REGISTRY["media_control"]
    result = tool.func("next")

    assert tool.risk == "safe"
    assert result.status == "success"
    assert pressed == ["nexttrack"]


def test_copy_from_window_is_registered_and_callable():
    tool = REGISTRY["copy_from_window"]

    assert callable(tool.func)
    assert tool.risk == "safe"


def test_destructive_browser_and_desktop_actions_require_confirmation():
    assert classify("browser_interaction", {"query": "Send this email now"})[0] == "CONFIRM"
    assert classify("browser_interaction", {"query": "Delete this account"})[0] == "CONFIRM"
    assert classify("click_mouse", {"x": 10, "y": 20})[0] == "CONFIRM"
