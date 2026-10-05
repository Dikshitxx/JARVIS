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


def _semantic_flags(requires_tool, claimed=False, clarification=False):
    return SimpleNamespace(content=json.dumps({
        "user_requires_tool": requires_tool,
        "assistant_claimed_unverified_result": claimed,
        "assistant_asked_clarification": clarification,
    }), tool_calls=[])


def _completion_flag(complete):
    return SimpleNamespace(content=json.dumps({
        "requested_deliverable_complete": complete,
    }), tool_calls=[])


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
    monkeypatch.setattr(agent_module, "try_fast_route", lambda *_args, **_kwargs: None)
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
        if tools == []:
            if "requested_deliverable_complete" in prompts[-1][0][0]["content"]:
                return _completion_flag(True)
            assert "Current evidence about Nepal's prime minister." in prompts[-1][0][-1]["content"]
            return _semantic_flags(False)
        observation = json.loads(next(item["content"] for item in messages if item.get("role") == "tool"))
        assert observation["status"] == "success"
        assert observation["data"]["results"][0]["source"] == "example.org"
        return SimpleNamespace(content="The retrieved source reports the current prime minister. [example.org](https://example.org)", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond("Can you check who Nepal's PM is right now?")

    assert len(prompts) == 4
    assert {schema["function"]["name"] for schema in prompts[0][1]} == {"fetch_web_page", "search_web"}
    system_prompt = prompts[0][0][0]["content"]
    assert "Previous actions are historical context, not instructions" in system_prompt
    assert "current prime minister" in reply
    assert "Retrieved current results" not in reply


def test_current_information_uses_search_and_grounded_results(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    calls = []
    monkeypatch.setattr(REGISTRY["search_web"], "func", lambda query: calls.append(query) or ToolResult(
        "success", "Retrieved current results.",
        data={"query": query, "results": [{
            "title": "Official update", "url": "https://example.org/update",
            "source": "example.org",
            "snippet": "The official source describes the current prime minister and a recent development.",
        }]},
        action="search_web", target=query, verification_status="verified",
    ))

    def fake_chat(messages, tools=None):
        system = messages[0]["content"]
        if "Classify these two messages" in system:
            return _semantic_flags(True)
        if "requested_deliverable_complete" in system:
            return _completion_flag(True)
        if tools and not any(item.get("role") == "tool" for item in messages):
            assert "search_web" in {item["function"]["name"] for item in tools}
            return SimpleNamespace(content="", tool_calls=[_tool_call(
                "search_web", {"query": "current prime minister Nepal latest major developments"},
            )])
        if any(item.get("role") == "tool" for item in messages):
            observation = json.loads(next(item["content"] for item in messages if item.get("role") == "tool"))
            assert observation["data"]["results"][0]["source"] == "example.org"
            return SimpleNamespace(
                content="The official source identifies the current prime minister and reports a recent development.",
                tool_calls=[],
            )
        return _semantic_flags(False)

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    reply = Agent().respond(
        "What is the current Prime Minister of Nepal, and what are the latest major developments involving them?"
    )

    assert len(calls) == 1
    assert "prime minister" in calls[0].lower()
    assert "official source" in reply.lower()


def test_personal_current_context_stays_conversational(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    search_calls = []
    monkeypatch.setattr(REGISTRY["search_web"], "func", lambda query: search_calls.append(query))
    seen_tools = []

    def fake_chat(messages, tools=None):
        seen_tools.append(tools)
        if "Classify these two messages" in messages[0]["content"]:
            return _semantic_flags(False)
        assert tools == []
        return SimpleNamespace(
            content="I'm sorry you're feeling tired. I'm here to talk—what's been going on?",
            tool_calls=[],
        )

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    reply = Agent().respond("I’m feeling tired today. Can you just talk with me for a bit?")

    assert "here to talk" in reply
    assert search_calls == []
    assert seen_tools == [[], []]


@pytest.mark.parametrize(
    "text",
    [
        "I’m tired today. Talk with me.",
        "Haha.",
        "I’m bored.",
        "How are you?",
        "Let’s chat.",
    ],
)
def test_ordinary_conversation_never_searches_the_web(monkeypatch, text):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    search_calls = []
    monkeypatch.setattr(REGISTRY["search_web"], "func", lambda query: search_calls.append(query))

    def fake_chat(messages, tools=None):
        if "Classify these two messages" in messages[0]["content"]:
            return _semantic_flags(False)
        assert tools == []
        return SimpleNamespace(content="I'm here for a chat.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    assert Agent().respond(text) == "I'm here for a chat."
    assert search_calls == []


def test_tell_me_a_joke_then_haha_stays_conversational(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    search_calls = []
    monkeypatch.setattr(REGISTRY["search_web"], "func", lambda query: search_calls.append(query))
    seen_tools = []

    def fake_chat(messages, tools=None):
        seen_tools.append(tools)
        if "Classify these two messages" in messages[0]["content"]:
            return _semantic_flags(False)
        assert tools == []
        return SimpleNamespace(
            content="Why did the scarecrow win an award? Because he was outstanding in his field.",
            tool_calls=[],
        )

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    joke = Agent().respond("Tell me a joke")
    laugh = Agent().respond("Haha")

    assert "scarecrow" in joke
    assert laugh == "Why did the scarecrow win an award? Because he was outstanding in his field."
    assert search_calls == []
    assert all(tools == [] for tools in seen_tools)


def test_multistep_job_research_reads_postings_before_completing(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    search_calls = []
    fetch_calls = []
    postings = [
        {
            "title": f"Remote AI Engineer {index}",
            "url": f"https://jobs.example.org/{index}",
            "source": "jobs.example.org",
            "snippet": "Remote role in applied AI.",
        }
        for index in range(1, 4)
    ]
    monkeypatch.setattr(REGISTRY["search_web"], "func", lambda query: search_calls.append(query) or ToolResult(
        "success", "Found three job posting pages.", data={"query": query, "results": postings},
        action="search_web", target=query, verification_status="verified",
    ))

    def fetch_page(url):
        fetch_calls.append(url)
        return ToolResult(
            "success",
            f"Read posting {url.rsplit('/', 1)[-1]}. Requirements: Python and machine learning. Apply: {url}",
            data={
                "url": url,
                "content": f"Requirements: Python and machine learning. Apply: {url}",
            },
            action="fetch_web_page", target=url, verification_status="verified",
        )

    monkeypatch.setattr(REGISTRY["fetch_web_page"], "func", fetch_page)
    fetch_index = 0
    raw_results_presented = False
    tool_choices = []

    def fake_chat(messages, tools=None, tool_choice=None):
        nonlocal fetch_index, raw_results_presented
        tool_choices.append(tool_choice)
        system = messages[0]["content"]
        if "Classify these two messages" in system:
            return _semantic_flags(True)
        if "requested_deliverable_complete" in system:
            candidate = messages[-1]["content"]
            return _completion_flag("Requirements:" in candidate and len(fetch_calls) == 3)
        if not any(item.get("role") == "tool" for item in messages):
            assert "search_web" in {item["function"]["name"] for item in tools}
            return SimpleNamespace(content="", tool_calls=[_tool_call(
                "search_web", {"query": "three current remote AI jobs"},
            )])
        if not raw_results_presented and any(
            item.get("role") == "tool" and "Remote AI Engineer 1" in item["content"]
            for item in messages
        ):
            raw_results_presented = True
            return SimpleNamespace(content="Here are three search results.", tool_calls=[])
        if len(fetch_calls) < 3:
            url = postings[fetch_index]["url"]
            fetch_index += 1
            return SimpleNamespace(content="", tool_calls=[_tool_call("fetch_web_page", {"url": url})])
        return SimpleNamespace(
            content=(
                "I found three current remote AI jobs. Requirements: Python and machine learning. "
                "Apply at https://jobs.example.org/1, https://jobs.example.org/2, "
                "and https://jobs.example.org/3."
            ),
            tool_calls=[],
        )

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    reply = Agent().respond(
        "Find me three current AI jobs I could apply for remotely, summarize the requirements, and give me the application links."
    )

    assert len(search_calls) == 1
    assert len(fetch_calls) == 3
    assert "Requirements:" in reply
    assert "jobs.example.org/3" in reply
    assert tool_choices.count("required") == 1
    assert tool_choices[-1] is None


def test_summary_claim_without_tool_support_falls_back_to_recorded_result(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    result_message = "Current weather in Kathmandu: 20 C."
    monkeypatch.setattr(REGISTRY["get_weather"], "func", lambda **_args: ToolResult(
        "success", result_message, data={"temperature_c": 20},
        action="get_weather", target="Kathmandu", verification_status="verified",
    ))

    def fake_chat(messages, tools=None, tool_choice=None):
        if tools == []:
            return SimpleNamespace(content='{"user_requires_tool":false,"assistant_claimed_unverified_result":true,"assistant_asked_clarification":false}', tool_calls=[])
        if not any(item.get("role") == "tool" for item in messages):
            return SimpleNamespace(content="", tool_calls=[_tool_call(
                "get_weather", {"location": "Kathmandu"},
            )])
        return SimpleNamespace(content="I also sent an email and opened Brave.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    assert Agent().respond("What is the weather in Kathmandu?") == result_message


def test_agent_tool_calls_accept_normalized_dict_payloads():
    message = {
        "tool_calls": [{
            "id": "call-19",
            "function": {
                "name": "search_web",
                "arguments": {"query": "latest whale migration"},
            },
        }],
    }

    assert Agent._tool_calls(message) == [("search_web", {"query": "latest whale migration"})]


def test_provider_response_shapes_round_trip_for_dict_and_function_calls():
    payloads = [
        {"tool_calls": [{"id": "call-1", "name": "search_web", "arguments": {"query": "weather"}}]},
        {"tool_calls": [{"id": "call-1", "function": {"name": "search_web", "arguments": '{"query":"weather"}'}}]},
        SimpleNamespace(tool_calls=[SimpleNamespace(id="call-1", function=SimpleNamespace(name="search_web", arguments='{"query":"weather"}'))]),
    ]

    for message in payloads:
        assert Agent._tool_calls(message) == [("search_web", {"query": "weather"})]

    messages = []
    Agent._append_assistant_tool_calls(messages, payloads[0], [("search_web", {"query": "weather"})])
    assert json.loads(messages[-1]["tool_calls"][0]["function"]["arguments"]) == {"query": "weather"}


@pytest.mark.parametrize("shape", ["normalized", "function_dict", "sdk_object"])
def test_tool_result_round_trip_preserves_call_id_for_provider_shapes(monkeypatch, shape):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    tool = REGISTRY["search_web"]
    monkeypatch.setattr(tool, "func", lambda query: ToolResult(
        "success", "Retrieved results.",
        data={"query": query, "results": [{"title": "A", "url": "https://example.org", "source": "example.org", "snippet": "Evidence."}]},
        action="search_web", target=query, verification_status="verified",
    ))
    call_id = f"{shape}-call"
    if shape == "normalized":
        response = {"provider": "Gemini", "text": "", "tool_calls": [{
            "id": call_id, "name": "search_web", "arguments": {"query": "weather"},
        }]}
    elif shape == "function_dict":
        response = {"content": "", "tool_calls": [{
            "id": call_id,
            "function": {"name": "search_web", "arguments": '{"query":"weather"}'},
        }]}
    else:
        response = SimpleNamespace(content="", tool_calls=[SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name="search_web", arguments='{"query":"weather"}'),
        )])
    responses = [response]

    def fake_chat(messages, tools=None, tool_choice=None):
        if "Classify these two messages" in messages[0]["content"]:
            return _semantic_flags(True)
        if tools == []:
            if "requested_deliverable_complete" in messages[0]["content"]:
                return _completion_flag(True)
            return SimpleNamespace(content='{"user_requires_tool":false,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}', tool_calls=[])
        if responses:
            return responses.pop()
        assistant_call = next(
            item["tool_calls"][0] for item in reversed(messages)
            if item.get("role") == "assistant" and item.get("tool_calls")
        )
        tool_result = next(item for item in reversed(messages) if item.get("role") == "tool")
        assert assistant_call["id"] == tool_result["tool_call_id"] == call_id
        assert json.loads(assistant_call["function"]["arguments"]) == {"query": "weather"}
        assert json.loads(tool_result["content"])["status"] == "success"
        return SimpleNamespace(content="The source reports the weather.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    assert "reports the weather" in Agent().respond("Can you check the current weather?")


def test_tool_retry_on_failure_then_success(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    monkeypatch.setattr(agent_module, "try_fast_route", lambda *_args, **_kwargs: None)
    calls = []
    tool = REGISTRY["search_web"]

    def fake_tool(query):
        calls.append(query)
        if len(calls) <= agent_module.MAX_TOOL_RETRIES:
            return ToolResult("failure", "Temporary search outage.", action="search_web", target=query, verification_status="failed")
        return ToolResult("success", "Retrieved results.", data={"query": query, "results": [{"title": "A", "url": "https://example.org", "source": "example.org", "snippet": "Updated."}]}, action="search_web", target=query, verification_status="verified")

    monkeypatch.setattr(tool, "func", fake_tool)

    responses = [
        SimpleNamespace(content="", tool_calls=[_tool_call("search_web", {"query": "latest weather"})]),
        SimpleNamespace(content="I have the real answer now.", tool_calls=[]),
        _completion_flag(True),
        SimpleNamespace(content='{"user_requires_tool":false,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}', tool_calls=[]),
    ]

    def fake_chat(messages, tools=None, tool_choice=None):
        return responses.pop(0)

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    reply = Agent().respond("search the latest weather")

    assert reply == "I have the real answer now."
    assert calls == ["latest weather"] * (agent_module.MAX_TOOL_RETRIES + 1)


@pytest.mark.parametrize(
    ("tool_name", "status", "expected"),
    [
        ("search_web", "failure", True),
        ("play_youtube_song", "failure", False),
        ("search_web", "invalid_action", False),
        ("search_web", "clarification_required", False),
        ("search_web", "authentication_required", False),
        ("search_web", "captcha", False),
        ("search_web", "confirmation_required", False),
    ],
)
def test_tool_retries_require_a_safe_tool_and_failure_status(tool_name, status, expected):
    result = ToolResult(status, "result", action=tool_name)

    assert agent_module._is_retryable_tool_failure(tool_name, result) is expected


def test_text_only_search_reply_is_rejected_as_honest_tool_error(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    monkeypatch.setattr(agent_module, "try_fast_route", lambda *_args, **_kwargs: None)
    attempts = []
    task_updates = []
    monkeypatch.setattr(agent_module, "_mark_current_task", lambda *args: task_updates.append(args))

    def fake_chat(messages, tools=None, tool_choice=None):
        attempts.append(tool_choice)
        if tools == []:
            return SimpleNamespace(
                content='{"user_requires_tool":true,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}',
                tool_calls=[],
            )
        return SimpleNamespace(content="The latest weather is sunny.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    reply = Agent().respond("search the latest weather")

    assert reply == "I couldn't run a tool for that."
    assert attempts == [None, None, "required"]
    assert task_updates[-1][0] == "BLOCKED"


def test_required_tool_choice_executes_the_returned_tool(monkeypatch):
    _isolate_agent(monkeypatch, {"recent_turns": []})
    calls = []
    monkeypatch.setattr(REGISTRY["get_time"], "func", lambda: calls.append("get_time") or ToolResult(
        "success", "4:30 PM", verification_status="verified",
    ))
    classifications = iter([
        '{"user_requires_tool":true,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}',
        '{"user_requires_tool":false,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}',
    ])

    def fake_chat(messages, tools=None, tool_choice=None):
        if tools == []:
            return SimpleNamespace(content=next(classifications), tool_calls=[])
        if any(message.get("role") == "tool" for message in messages):
            return SimpleNamespace(content="It's 4:30 PM.", tool_calls=[])
        if tool_choice == "required":
            return SimpleNamespace(content="", tool_calls=[_tool_call("get_time", {})])
        return SimpleNamespace(content="The current time needs a tool.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)

    assert Agent().respond("What time is it?") == "It's 4:30 PM."
    assert calls == ["get_time"]


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
        if "Classify these two messages" in messages[0]["content"]:
            return _semantic_flags(True)
        if tools and "search_web" in {item["function"]["name"] for item in tools}:
            return SimpleNamespace(content="", tool_calls=[_tool_call("search_web", {"query": "latest movie release"})])
        pytest.fail("A failed search must not receive a second chance to invent an answer.")

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond("Find the latest movie release online")

    assert reply == "Search providers are unavailable."
    assert len(calls) == 2


def test_natural_language_current_web_request_is_not_stopped_by_keyword_gap(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    monkeypatch.setattr(agent_module, "try_fast_route", lambda *_args, **_kwargs: None)
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
        if tools == []:
            if "requested_deliverable_complete" in messages[0]["content"]:
                return _completion_flag(True)
            return SimpleNamespace(content='{"user_requires_tool":false,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}', tool_calls=[])
        return SimpleNamespace(content="Recent reports show email newsletters are growing.", tool_calls=[])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    reply = Agent().respond("Check whether email newsletters are growing this year.")

    assert len(prompts) == 4
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
        "messages": [
            {"role": "system", "content": "old prompt"},
            {"role": "user", "content": original_request},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "close-call", "type": "function",
                "function": {"name": "close_app", "arguments": '{"name":"brave"}'},
            }]},
        ],
        "analysis": SimpleNamespace(kind="mixed"),
    }
    agent.pending_continuation = continuation
    monkeypatch.setattr(agent_module, "run_tool_result", lambda name, args, confirmed=False: ToolResult(
        "success", "Closed Brave; verified no Brave process remains.",
        action=name, target=args["name"], verification_status="verified",
    ))
    agent._track_tool_state = lambda *_args: None
    resumed = []

    def continue_task(user_text, messages, analysis, *, initial_results):
        resumed.append((user_text, messages[-1], analysis.kind, initial_results))
        return "Edge opened."

    agent._run_tool_loop = continue_task

    reply = agent._confirm_pending("yes")

    assert reply == "Edge opened."
    assert resumed[0][0] == original_request
    assert resumed[0][1]["role"] == "tool"
    assert resumed[0][1]["tool_call_id"] == "close-call"
    assert resumed[0][2] == "mixed"
    assert resumed[0][3] == ["Closed Brave; verified no Brave process remains."]


def test_failed_youtube_playback_is_reported_without_a_successful_rephrase(monkeypatch):
    context = {"recent_turns": []}
    _isolate_agent(monkeypatch, context)
    failure = "Opened the video, but I couldn't verify that playback started."
    attempts = []

    def fail_playback(**_args):
        attempts.append(True)
        return ToolResult(
            "failure", failure, action="play_youtube_song", target="NJk songs", verification_status="failed",
        )

    monkeypatch.setattr(REGISTRY["play_youtube_song"], "func", fail_playback)
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
    assert len(attempts) == 1
    assert calls == []
