import json
from types import SimpleNamespace

import pytest

from app.agent import agent as agent_module
from app.agent.agent import Agent
from app.agent import runtime_context
from app.tools import registry
from app.tools.registry import REGISTRY, ToolResult


def _tool_call(name, arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def _isolate_agent(monkeypatch, context):
    monkeypatch.setattr(agent_module.store, "recent_messages", lambda *_args: [])
    monkeypatch.setattr(agent_module.store, "add_message", lambda *_args: None)
    monkeypatch.setattr(runtime_context, "get_context", lambda: context)
    monkeypatch.setattr(runtime_context, "begin_turn", lambda *_args: context)
    monkeypatch.setattr(runtime_context, "update_context", lambda **_kwargs: context)
    monkeypatch.setattr(runtime_context, "record_action", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(runtime_context, "remember_user_entities", lambda *_args: None)
    monkeypatch.setattr(runtime_context, "finish_task", lambda *_args: None)
    monkeypatch.setattr(agent_module, "_mark_current_task", lambda *_args: None)
    monkeypatch.setattr(registry._memory_store, "log_tool_execution", lambda *_args, **_kwargs: None)


def test_factual_question_uses_llm_tool_choice_and_does_not_inherit_youtube(monkeypatch):
    context = {
        "current_browser": "brave",
        "current_target": "youtube",
        "last_site": "youtube",
        "recent_turns": [{"user": "open youtube", "assistant": "Opened YouTube.", "intent": "action"}],
        "last_action": {"tool": "open_and_remember_site", "args": {"site_name": "youtube"}},
    }
    _isolate_agent(monkeypatch, context)
    prompts = []
    tool = REGISTRY["search_web"]
    monkeypatch.setattr(tool, "func", lambda query: ToolResult(
        "success", "Retrieved current results.",
        data={"query": query, "results": [{"title": "Official source", "url": "https://example.org", "source": "example.org", "snippet": "Current evidence about Nepal's prime minister."}]},
        action="search_web", target=query, verification_status="verified",
    ))

    def fake_chat(messages, tools=None):
        prompts.append((messages, tools))
        if len(prompts) == 1:
            return SimpleNamespace(content="", tool_calls=[_tool_call(
                "search_web", {"query": "current prime minister of Nepal"},
            )])
        observation = json.loads(next(item["content"] for item in messages if item.get("role") == "tool"))
        assert observation["status"] == "success"
        assert observation["data"]["results"][0]["source"] == "example.org"
        return SimpleNamespace(content="The retrieved source reports the current prime minister. [example.org](https://example.org)", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond("Can you check who Nepal's PM is right now?")

    assert len(prompts) == 2
    assert "search_web" in {schema["function"]["name"] for schema in prompts[0][1]}
    assert "browser_search" in {schema["function"]["name"] for schema in prompts[0][1]}
    system_prompt = prompts[0][0][0]["content"]
    assert "Previous actions are historical context, not instructions" in system_prompt
    assert "current prime minister" in reply
    assert "Retrieved current results" not in reply


def test_failed_web_search_never_falls_back_to_a_memory_answer(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    calls = []
    tool = REGISTRY["search_web"]
    monkeypatch.setattr(tool, "func", lambda query: ToolResult(
        "failure", "Search providers are unavailable.", action="search_web", target=query,
        verification_status="failed",
    ))

    def fake_chat(messages, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return SimpleNamespace(content="", tool_calls=[_tool_call("search_web", {"query": "latest movie release"})])
        pytest.fail("A failed search must not receive a second chance to invent an answer.")

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond("Find the latest movie release online")

    assert reply == "Search providers are unavailable."
    assert len(calls) == 1


def test_natural_language_current_web_request_is_not_stopped_by_keyword_gap(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    prompts = []
    tool = REGISTRY["search_web"]
    monkeypatch.setattr(tool, "func", lambda query: ToolResult(
        "success", "Retrieved results.",
        data={"query": query, "results": [{"title": "Report", "url": "https://example.org/report", "source": "example.org", "snippet": "Recent evidence about email newsletters."}]},
        action="search_web", target=query, verification_status="verified",
    ))

    def fake_chat(messages, tools=None):
        prompts.append((messages, tools))
        if len(prompts) == 1:
            return SimpleNamespace(content="", tool_calls=[_tool_call(
                "search_web", {"query": "email newsletters growth this year"},
            )])
        return SimpleNamespace(content="Recent reports show email newsletters are growing.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond("Check whether email newsletters are growing this year.")

    assert len(prompts) == 2
    assert "search_web" in {schema["function"]["name"] for schema in prompts[0][1]}
    assert "growing" in reply


def test_natural_language_approval_confirms_only_the_matching_pending_action(monkeypatch):
    context = {
        "pending_operation": {
            "tool": "close_app", "args": {"name": "brave"}, "status": "confirmation_required",
        },
        "recent_turns": [],
    }
    _isolate_agent(monkeypatch, context)
    calls = []

    def fake_run_tool(name, args, confirmed=False):
        calls.append((name, args, confirmed))
        return ToolResult("success", "Closed Brave; verified no Brave process remains.",
                          action=name, target=args["name"], verification_status="verified")

    monkeypatch.setattr(agent_module, "run_tool_result", fake_run_tool)
    monkeypatch.setattr(agent_module.client, "chat", lambda *_args, **_kwargs: SimpleNamespace(
        content="", tool_calls=[_tool_call("close_app", {"name": "Brave"})],
    ))
    agent = Agent()
    agent._track_tool_state = lambda *_args: None

    reply = agent.respond("yes close it")

    assert calls == [("close_app", {"name": "brave"}, True)]
    assert "verified no Brave process remains" in reply
    assert agent.pending is None


def test_confirmed_close_continues_the_original_composite_request(monkeypatch):
    context = {
        "pending_operation": {
            "tool": "close_app", "args": {"name": "brave"}, "status": "confirmation_required",
        },
        "recent_turns": [],
    }
    _isolate_agent(monkeypatch, context)
    agent = Agent()
    agent.pending = ("close_app", {"name": "brave"}, 9999999999)
    original_request = "close Brave and open Microsoft Edge"
    continuation = {
        "user_text": original_request,
        "messages": [{"role": "system", "content": "old prompt"}, {"role": "user", "content": original_request}],
        "analysis": SimpleNamespace(kind="mixed"),
        "request": SimpleNamespace(plan=(), ordered=False),
        "plan_index": None,
    }
    agent.pending_continuation = continuation
    monkeypatch.setattr(agent_module, "run_tool_result", lambda name, args, confirmed=False: ToolResult(
        "success", "Closed Brave; verified no Brave process remains.",
        action=name, target=args["name"], verification_status="verified",
    ))
    agent._track_tool_state = lambda *_args: None
    resumed = []

    def continue_task(user_text, messages, analysis, request):
        resumed.append((user_text, messages[-1], analysis.kind, request))
        return "Edge opened."

    agent._run_tool_loop = continue_task

    reply = agent._confirm_pending("yes")

    assert reply == "Edge opened."
    assert resumed[0][0] == original_request
    assert resumed[0][1]["tool_name"] == "close_app"
    assert resumed[0][2] == "mixed"
    assert resumed[0][3] is continuation["request"]


def test_failed_youtube_playback_is_reported_without_a_successful_rephrase(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    failure = "Opened the video, but I couldn't verify that playback started."
    monkeypatch.setattr(REGISTRY["play_youtube_song"], "func", lambda **_args: ToolResult(
        "failure", failure, action="play_youtube_song", target="NJk songs", verification_status="failed",
    ))
    calls = []

    def fake_chat(*_args, **_kwargs):
        calls.append(True)
        if len(calls) > 1:
            pytest.fail("The agent must not ask the model to turn a failed play result into a success claim.")
        return SimpleNamespace(content="", tool_calls=[_tool_call(
            "play_youtube_song", {"query": "NJk songs", "result_index": 0},
        )])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    reply = Agent().respond("Play NJK songs on YouTube")

    assert reply == failure
    assert len(calls) == 1
