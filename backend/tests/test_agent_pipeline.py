from types import SimpleNamespace

import pytest

import app.agent.router as router_module
from app.agent import agent as agent_module
from app.agent.agent import Agent
from app.tools.registry import ToolResult


def _message(content="", tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(name, arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


@pytest.mark.parametrize("text", ["How are you?", "Tell me what you can do?"])
def test_conversation_is_llm_handled_with_tool_descriptions_available(monkeypatch, text):
    seen = []

    def fake_chat(messages, tools=None):
        seen.append(tools)
        return _message("I can help with conversation and practical tasks.")

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond(text)

    assert "I can help" in reply
    assert len(seen) == 1
    names = {tool["function"]["name"] for tool in seen[0]}
    assert {"search_web", "browser_open", "open_app"} <= names


def test_time_request_uses_only_time_tool(monkeypatch):
    calls = []

    def fake_get_time(name, args, confirmed=False):
        calls.append((name, args))
        return ToolResult("success", "09:00 PM", verification_status="verified")

    monkeypatch.setattr(router_module, "run_tool_result", fake_get_time)
    reply = Agent().respond("What time is it?")

    assert calls == [("get_time", {})]
    assert reply == "09:00 PM"


@pytest.mark.parametrize("text", ["Find files in my browser", "Delete files in my browser"])
def test_browser_files_request_reaches_llm_for_clarification(monkeypatch, text):
    seen = []

    def fake_chat(messages, tools=None):
        seen.append(tools)
        return _message("Do you mean downloaded files, files on a webpage, or files on your computer?")

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond(text)

    assert "downloaded files" in reply
    assert "computer" in reply
    assert len(seen) == 1
    assert "find_file" in {tool["function"]["name"] for tool in seen[0]}


def test_whatsapp_greeting_is_drafted_and_requires_confirmation(monkeypatch):
    call = _tool_call("send_whatsapp_message", {"contact": "Ishan", "message": "greet him"})
    monkeypatch.setattr(agent_module.client, "chat", lambda *args, **kwargs: _message(tool_calls=[call]))

    reply = Agent().respond("He is my friend Ishan. Greet him.")

    assert "Send this to Ishan?" in reply
    assert "Hello Ishan, how are you?" in reply
    assert agent_module.agent is not None


def test_confirmed_whatsapp_uses_drafted_message(monkeypatch):
    agent = Agent()
    sent = []
    agent.pending = ("send_whatsapp_message", {"contact": "Ishan", "message": "Hello Ishan, how are you?"}, 9999999999)

    def fake_send(name, args, confirmed=False):
        sent.append((name, args, confirmed))
        return ToolResult("success", "Sent WhatsApp message to Ishan: Hello Ishan, how are you?", verification_status="verified")

    monkeypatch.setattr(agent_module, "run_tool_result", fake_send)
    reply = agent.respond("yes")

    assert sent == [("send_whatsapp_message", {"contact": "Ishan", "message": "Hello Ishan, how are you?"}, True)]
    assert "Hello Ishan" in reply


def test_weather_uses_weather_tool_and_final_natural_response(monkeypatch):
    calls = []
    tool_call = _tool_call("get_weather", {"location": "Kathmandu"})
    responses = iter([
        _message(tool_calls=[tool_call]),
        _message("Today's weather in Kathmandu is clear and mild."),
    ])

    def fake_chat(messages, tools=None):
        return next(responses)

    def fake_run(name, args):
        calls.append((name, args))
        return ToolResult("success", "Current weather in Kathmandu: 20°C.")

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    monkeypatch.setattr(agent_module, "run_tool_result", fake_run)
    reply = Agent().respond("What is today's weather in Kathmandu?")

    assert calls == [("get_weather", {"location": "Kathmandu"})]
    assert reply == "Today's weather in Kathmandu is clear and mild."


def test_unknown_tool_json_is_not_exposed(monkeypatch):
    monkeypatch.setattr(
        agent_module.client,
        "chat",
        lambda *args, **kwargs: _message('{"name":"list_applications","parameters":{"name":"all"}}'),
    )

    reply = Agent().respond("Tell me what you can do?")

    assert "list_applications" not in reply
    assert "parameters" not in reply


def test_playwright_task_wrapper_keeps_execution_boundary(monkeypatch):
    import app.tools.whatsapp as whatsapp

    class FakeSession:
        def run(self, func, *args):
            return "sent"

    monkeypatch.setattr(whatsapp, "get_browser_session", lambda: FakeSession())

    assert whatsapp.send_whatsapp_message("Ishan", "Hello") == "sent"
