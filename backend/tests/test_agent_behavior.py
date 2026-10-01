from types import SimpleNamespace

import pytest

from app.agent.agent import Agent
from app.agent.request import build_user_request
from app.core import config
from app.llm import client
from app.memory import store
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
    monkeypatch.setattr(client, "chat", lambda *args, **kwargs: _tool_call("open_app", {"name": "notepad"}))
    monkeypatch.setattr(REGISTRY["open_app"], "func", lambda name: called.append(name) or ToolResult("success", "Opened Notepad.", verification_status="verified"))
    monkeypatch.setattr("app.agent.agent.runtime_context.record_action", lambda *args, **kwargs: {})

    request = build_user_request("open notepad")
    reply = Agent()._run_tool_loop(
        "open notepad", [{"role": "user", "content": "open notepad"}], request.analysis, request,
    )

    assert reply == "Opened Notepad."
    assert called == ["notepad"]


def test_close_app_tool_call_still_requires_confirmation(monkeypatch, isolated_store):
    monkeypatch.setattr(client, "chat", lambda *args, **kwargs: _tool_call("close_app", {"name": "notepad"}))
    agent = Agent()
    name, arguments = agent._tool_calls(client.chat([], tools=[]))[0]
    with pytest.raises(NeedsConfirmation):
        run_tool_result(name, arguments)


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
