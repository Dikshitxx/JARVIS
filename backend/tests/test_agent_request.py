from types import SimpleNamespace


import pytest

from app.agent import router
from app.agent.agent import Agent, _strip_stray_tool_json
from app.agent.request import build_user_request
from app.tools.registry import REGISTRY, Tool, ToolResult, names_for_capabilities, register, run_tool_result


@pytest.mark.parametrize(
    ("text", "intent", "target", "target_type", "query"),
    [
        ("open chat gpt for me", "open_website", "chatgpt", "website", ""),
        ("open chatgpt", "open_website", "chatgpt", "website", ""),
        ("can you open ChatGPT?", "open_website", "chatgpt", "website", ""),
        ("play Hustle 2.0", "play_media_content", "youtube", "media_service", "Hustle 2.0"),
        ("play Believer", "play_media_content", "youtube", "media_service", "Believer"),
        ("pause the current song", "pause_current_media", "current_media", "media", ""),
        ("open notepad", "open_application", "notepad", "application", ""),
    ],
)
def test_exact_examples_have_structured_intents_and_entities(text, intent, target, target_type, query):
    request = build_user_request(text)
    assert request.intent == intent
    assert request.target == target
    assert request.target_type == target_type
    assert request.query == query
    if text == "can you open ChatGPT?":
        assert request.kind == "ACTION"


def test_play_again_resumes_only_the_contextual_paused_item():
    paused = build_user_request(
        "play the song again",
        {"active_media": "youtube", "current_media": "Believer", "last_query": "Believer", "media_state": "paused"},
    )
    fresh = build_user_request("play the song again")

    assert paused.intent == "resume_current_media"
    assert fresh.intent == "play_media_content"
    assert fresh.query == "music"


def test_another_song_uses_recent_query_and_marks_new_result():
    request = build_user_request("play another song", {"last_query": "relaxing music"})

    assert request.intent == "play_media_content"
    assert request.query == "relaxing music"
    assert "avoid_current" in request.modifiers


def test_follow_up_media_result_uses_the_recent_search_query():
    first = build_user_request("play the first one", {"last_query": "relaxing music"})
    another = build_user_request("play another one", {"last_query": "relaxing music"})

    assert first.intent == "play_media_content"
    assert first.query == "relaxing music"
    assert "result_index=0" in first.modifiers
    assert another.query == "relaxing music"
    assert "avoid_current" in another.modifiers


def test_media_query_strips_explicit_service_suffix():
    request = build_user_request("play parvati songs on youtube")

    assert request.intent == "play_media_content"
    assert request.target == "youtube"
    assert request.query == "parvati songs"


def test_live_media_question_is_information_request_with_live_capability():
    request = build_user_request("what song is currently playing?")

    assert request.kind == "INFORMATION_REQUEST"
    assert request.intent == "inspect_current_media"
    assert "media" in request.capabilities
    assert "inspect_current_media" in names_for_capabilities(request.capabilities)


@pytest.mark.parametrize(
    ("text", "intent", "tool", "capability"),
    [
        ("Is Notepad currently open?", "inspect_application", "inspect_application", "windows"),
        ("What page am I on?", "inspect_current_page", "inspect_current_page", "browser"),
    ],
)
def test_application_and_browser_state_questions_use_live_inspection(monkeypatch, text, intent, tool, capability):
    from app.agent import agent as agent_module

    calls = []
    request = build_user_request(text)

    def fake_chat(_messages, tools=None, **_kwargs):
        calls.append({schema["function"]["name"] for schema in tools or []})
        return SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=SimpleNamespace(
            name=tool, arguments={"name": request.target} if tool == "inspect_application" else {},
        ))])

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    monkeypatch.setattr(REGISTRY[tool], "func", lambda **_args: ToolResult(
        "success", "live state inspected", verification_status="verified",
    ))
    monkeypatch.setattr(agent_module.runtime_context, "record_action", lambda *_args, **_kwargs: {})
    reply = Agent().respond(text)

    assert request.kind == "INFORMATION_REQUEST"
    assert request.intent == intent
    assert capability in request.capabilities
    assert reply == "live state inspected"
    assert tool in calls[0]


def test_chat_cancellation_and_context_references_are_separate():
    chat = build_user_request("how are you?")
    cancel = build_user_request("actually don't do that")
    context = {"current_window": "Untitled - Notepad"}
    copy = build_user_request("copy that", context)
    paste = build_user_request("paste it", context)
    typed = build_user_request("type hello world", context)

    assert chat.kind == "CHAT"
    assert not chat.capabilities
    assert cancel.kind == "CANCELLATION"
    assert cancel.intent == "cancel_pending"
    assert (typed.intent, typed.query, typed.target) == ("type_text", "hello world", "Untitled - Notepad")
    assert (copy.intent, copy.target) == ("copy_selection", "Untitled - Notepad")
    assert (paste.intent, paste.target) == ("paste_text", "Untitled - Notepad")


def test_media_capability_does_not_expose_messaging_tools():
    request = build_user_request("play the song that is currently paused")
    available = names_for_capabilities(request.capabilities)

    assert request.intent == "resume_current_media"
    assert "control_media" in available
    assert not any("whatsapp" in name or "message" in name for name in available)


def test_paraphrased_open_request_uses_registered_direct_route(monkeypatch):
    seen = []

    def fake_chat(messages, tools=None):
        seen.append({schema["function"]["name"] for schema in tools or []})
        return type("Message", (), {
            "content": "",
            "tool_calls": [type("Call", (), {"function": type("Function", (), {
                "name": "browser_open", "arguments": {"target": "chatgpt"},
            })()})()],
        })()

    monkeypatch.setattr("app.agent.agent.client.chat", fake_chat)
    monkeypatch.setattr(REGISTRY["browser_open"], "func", lambda target: ToolResult("success", f"Opened {target}.", verification_status="verified"))
    monkeypatch.setattr("app.agent.agent.runtime_context.record_action", lambda *args, **kwargs: {})

    reply = Agent().respond("Could you take me to ChatGPT?")

    assert reply == "Opened chatgpt."
    assert seen == []


def test_contextual_reference_requests_do_not_fast_route():
    request = build_user_request("Search the same thing there.")

    assert request.context_references
    assert router.try_fast_route("Search the same thing there.", {}, request) is None


@pytest.mark.parametrize(
    ("text", "intent", "target", "target_type"),
    [
        ("bring up Notepad", "open_application", "notepad", "application"),
        ("take me to ChatGPT", "open_website", "chatgpt", "website"),
        ("show me YouTube", "open_website", "youtube", "website"),
    ],
)
def test_natural_language_open_variants_use_generic_intent_matching(text, intent, target, target_type):
    request = build_user_request(text)

    assert request.intent == intent
    assert request.target == target
    assert request.target_type == target_type


def test_ordinary_text_and_clipboard_actions_do_not_require_confirmation():
    from app.permissions.classify import classify

    assert classify("type_text", {"text": "hello", "target_window": "Notepad"})[0] == "ALLOW"
    assert classify("copy_selection", {"target_window": "Notepad"})[0] == "ALLOW"
    assert classify("paste_text", {"target_window": "Notepad"})[0] == "ALLOW"


def test_mixed_request_keeps_an_ordered_structured_plan():
    request = build_user_request("open Brave and search YouTube for relaxing music")

    assert request.kind == "MIXED_REQUEST"
    assert request.intent == "execute_plan"
    assert request.ordered
    assert [step.intent for step in request.plan] == ["open_application", "browser_search"]
    assert request.plan[0].target == "brave"
    assert request.plan[1].target == "youtube"
    assert request.plan[1].query == "relaxing music"
    assert request.plan[1].depends_on == (0,)
    assert request.capabilities == frozenset({"windows", "browser"})


def test_natural_language_message_rephrases_are_extracted_as_actions():
    request = build_user_request("Let Ishan know I'll call him later on WhatsApp")

    assert request.kind == "ACTION"
    assert request.intent == "send_whatsapp_message"
    assert request.target == "Ishan"
    assert request.target_type == "contact"
    assert "call him later" in request.query
    assert "messaging" in request.capabilities


def test_email_message_variants_are_extracted_as_messaging_actions():
    request = build_user_request("Email Ishan I'll call him later")

    assert request.kind == "ACTION"
    assert request.intent == "send_whatsapp_message"
    assert request.target == "Ishan"
    assert request.target_type == "contact"
    assert "call him later" in request.query
    assert "messaging" in request.capabilities


def test_mixed_open_and_message_requests_are_preserved_as_a_plan():
    request = build_user_request("Open WhatsApp and tell Ishan I'll call him later")

    assert request.kind == "MIXED_REQUEST"
    assert request.intent == "execute_plan"
    assert [step.intent for step in request.plan] == ["open_application", "send_whatsapp_message"]
    assert request.plan[0].target == "whatsapp"
    assert request.plan[1].target == "Ishan"
    assert request.capabilities == frozenset({"windows", "messaging"})


def test_contextual_browser_corrections_use_latest_target_instead_of_conversation_mode():
    request = build_user_request("Actually use Claude instead.", {"current_browser": "brave", "current_window": "chatgpt"})

    assert request.kind == "MIXED_REQUEST"
    assert request.intent == "execute_plan"
    assert request.target == "claude"
    assert request.target_type == "website"
    assert [step.intent for step in request.plan] == ["open_application", "open_website"]
    assert request.capabilities == frozenset({"browser", "windows"})


def test_open_website_in_named_browser_becomes_two_ordered_steps():
    request = build_user_request("open GitHub in Brave")

    assert request.intent == "execute_plan"
    assert request.kind == "MIXED_REQUEST"
    assert [step.intent for step in request.plan] == ["open_application", "open_website"]
    assert [step.target for step in request.plan] == ["brave", "github"]
    assert request.ordered


def test_agent_observes_sequential_llm_tool_calls_without_parser_overrides(monkeypatch, tmp_path):
    from app.agent import agent as agent_module
    from app.agent import runtime_context
    from app.agent.agent import Agent
    from app.core import config
    from app.memory import store

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.jarvis.db")
    store.clear_runtime_context()
    calls = []
    exposed = []
    replies = [
        SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=SimpleNamespace(name="open_app", arguments={"name": "Wrong app"}))]),
        SimpleNamespace(content="", tool_calls=[SimpleNamespace(function=SimpleNamespace(name="browser_search", arguments={"target": "github", "query": "wrong query"}))]),
        SimpleNamespace(content="Brave is open and YouTube has the relaxing music search results.", tool_calls=[]),
        SimpleNamespace(content='{"user_requires_tool":false,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}', tool_calls=[]),
    ]

    def fake_chat(_messages, tools=None):
        if tools == []:
            return SimpleNamespace(content='{"user_requires_tool":false,"assistant_claimed_unverified_result":false,"assistant_asked_clarification":false}', tool_calls=[])
        exposed.append([item["function"]["name"] for item in (tools or [])])
        return replies.pop(0)

    def fake_run(name, args, confirmed=False):
        calls.append((name, args))
        return ToolResult("success", f"{name} completed", verification_status="verified")

    monkeypatch.setattr(agent_module.client, "chat", fake_chat)
    monkeypatch.setattr(agent_module, "run_tool_result", fake_run)
    monkeypatch.setattr(runtime_context, "record_action", lambda *_args, **_kwargs: {})

    reply = Agent().respond("Open Brave and search YouTube for relaxing music")

    assert calls == [
        ("open_app", {"name": "Wrong app"}),
        ("browser_search", {"target": "github", "query": "wrong query"}),
    ]
    assert len(exposed) == 3
    assert all("browser_search" in tools and "search_web" in tools for tools in exposed)
    assert "search results" in reply


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("open chat gpt for me", ("browser_open", {"target": "chatgpt"})),
        ("play Hustle 2.0", ("play_youtube_song", {"query": "Hustle 2.0"})),
        ("pause the current song", ("control_media", {"action": "pause"})),
        ("what song is currently playing?", None),
    ],
)
def test_fast_router_uses_only_registered_direct_routes(text, expected):
    assert router.is_fast_route_candidate(text) is (expected is not None)
    assert router.try_fast_route(text) == expected


def test_news_metadata_uses_registered_search_route():
    request = build_user_request("tell me recent news")

    assert request.intent == "search_web"
    assert router.try_fast_route("tell me recent news", request=request) == (
        "search_web", {"query": "latest news"},
    )


def test_recent_news_is_search_not_messaging():
    request = build_user_request("tell me recent news")

    assert request.intent == "search_web"
    assert request.target == "google"
    assert "news" in request.query.lower()
    available = names_for_capabilities(request.capabilities)
    assert "search_web" in available
    assert "send_whatsapp_message" not in available


def test_check_for_project_on_device_routes_to_safe_file_search():
    request = build_user_request("check for synaxis project in my device")

    assert request.intent == "find_file"
    assert request.query == "synaxis project"
    assert request.capabilities == frozenset({"files"})


def test_tool_results_keep_verification_and_error_fields(monkeypatch):
    import app.tools.registry as registry

    monkeypatch.setattr(registry._memory_store, "log_tool_execution", lambda *_args, **_kwargs: None)
    register(Tool(
        name="test_verified_request_tool",
        description="test tool",
        parameters={"type": "object", "properties": {}},
        func=lambda: "completed",
        verify=lambda _args, _message: True,
    ))
    result = run_tool_result("test_verified_request_tool", {})
    failed = ToolResult("failure", "could not focus", verification_status="failed")

    assert result.status == "success"
    assert result.verification_status == "verified"
    assert failed.error == "could not focus"
    monkeypatch.delitem(REGISTRY, "test_verified_request_tool")


def test_window_targeting_resolves_a_specific_title_and_confirms_focus(monkeypatch):
    import app.tools.apps as apps
    import app.tools.desktop_input as desktop_input

    class FakeWindow:
        handle = 17

        def window_text(self):
            return "Untitled - Notepad"

        def is_visible(self):
            return True

        def set_focus(self):
            pass

        def process_id(self):
            return 42

    class FakeDesktop:
        def __init__(self, backend):
            assert backend == "uia"

        def windows(self):
            return [FakeWindow()]

    monkeypatch.setattr(desktop_input, "Desktop", FakeDesktop)
    monkeypatch.setattr(desktop_input.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(apps, "get_active_window_info", lambda: {"hwnd": 17, "pid": 42, "title": "Untitled - Notepad"})

    window, error = desktop_input._resolve_and_focus_window("Untitled - Notepad")

    assert isinstance(window, FakeWindow)
    assert not error


def test_natural_response_cleanup_removes_raw_tool_json():
    assert _strip_stray_tool_json('Done. {"name":"open_app","parameters":{}}') == "Done."
    assert _strip_stray_tool_json('{"name":"open_app","parameters":{}}') == "I couldn't identify a valid action for that request."
