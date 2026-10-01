from datetime import datetime
import sys
import threading
import time
import types
from types import SimpleNamespace

import pytest

from app.agent.agent import Agent
from app.agent import runtime_context
from app.agent.utterance import analyze_utterance, relevant_tool_names
from app.core import config
from app.memory import store
from app.tools.registry import Tool, ToolResult, register, REGISTRY, run_tool_result
from app.tools import apps
from app.voice import VoiceService


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.jarvis.db")
    store.clear_runtime_context()


def _recent_action_context(**overrides):
    context = {
        "current_task": "Play a song",
        "current_target": "youtube",
        "active_service": "youtube",
        "active_media": "youtube",
        "current_media": "Imagine Dragons - Whatever It Takes",
        "last_action": {"tool": "play_youtube_song", "status": "success", "at": datetime.now().isoformat()},
    }
    context.update(overrides)
    return context


def test_conversation_is_not_forced_into_the_previous_action():
    assert analyze_utterance("How are you?", _recent_action_context()).kind == "conversation"
    assert analyze_utterance("What is Python?", _recent_action_context()).kind in {"conversation", "information"}


def test_new_action_and_contextual_follow_up_are_distinct():
    assert analyze_utterance("Open Brave").kind == "action"
    follow_up = analyze_utterance("Play another song", _recent_action_context())
    assert follow_up.kind == "follow_up"
    assert follow_up.refers_to_context


@pytest.mark.parametrize("message", ["Search it", "Search that", "Play the first one"])
def test_references_use_recent_task_context(message):
    result = analyze_utterance(message, _recent_action_context())
    assert result.refers_to_context
    assert result.kind == "follow_up"


def test_correction_and_mixed_message_are_classified_without_site_rules():
    assert analyze_utterance("Actually, something calmer", _recent_action_context()).kind == "follow_up"
    mixed = analyze_utterance("Open Brave, and by the way how are you?", {})
    assert mixed.kind == "mixed"


def test_weather_question_selects_current_information_tool():
    analysis = analyze_utterance("Is the weather nice today?")
    assert analysis.kind == "information"
    assert relevant_tool_names("Is the weather nice today?", analysis) == {"get_weather"}


def test_prompt_context_separates_action_and_conversation_history():
    store.append_runtime_turn("Play Imagine Dragons", "Playing Imagine Dragons.", "action")
    store.append_runtime_turn("How are you?", "I'm doing well.", "conversation")
    context = store.get_runtime_context()
    context_data = runtime_context.prompt_context("What do you think?", context)
    conversation_turns = context_data["conversation_context"]["recent_turns"]
    action_turns = context_data["action_context"]["recent_action_turns"]
    assert [item["user"] for item in conversation_turns] == ["How are you?"]
    assert [item["user"] for item in action_turns] == ["Play Imagine Dragons"]


def test_conversation_action_conversation_flow(monkeypatch):
    from app.agent import agent as agent_module

    agent = Agent()
    seen_tools = []
    monkeypatch.setattr(
        agent_module.client,
        "chat",
        lambda _messages, tools=None: (seen_tools.append(tools) or SimpleNamespace(content="I'm doing well.", tool_calls=[])),
    )
    monkeypatch.setattr(
        agent_module,
        "try_fast_route",
        lambda text, _context, _request=None: ("open_app", ToolResult("success", "Opened Brave."), {"name": "Brave"})
        if text == "Open Brave" else None,
    )
    monkeypatch.setattr(runtime_context, "record_action", lambda *_args, **_kwargs: {})

    assert agent.respond("How are you?") == "I'm doing well."
    assert agent.respond("Open Brave") == "Opened Brave."
    assert agent.respond("By the way, how are you doing?") == "I'm doing well."
    assert len(seen_tools) == 2
    assert all("search_web" in {item["function"]["name"] for item in tools} for tools in seen_tools)


def test_follow_up_keeps_the_same_task_and_prior_result():
    first = analyze_utterance("Play Imagine Dragons")
    context = runtime_context.begin_turn("Play Imagine Dragons", first)
    task_id = context["current_task_id"]
    runtime_context.record_action("play_youtube_song", {"query": "Imagine Dragons"}, ToolResult("success", "Playing a song."))

    follow_up = analyze_utterance("Play another song", store.get_runtime_context())
    updated = runtime_context.begin_turn("Play another song", follow_up)
    assert updated["current_task_id"] == task_id
    assert len(updated["task_actions"]) == 1


def test_failed_media_action_preserves_service_and_reference_context():
    store.update_runtime_context(
        active_service="youtube", active_media="youtube", current_media="Current song", current_target="youtube"
    )
    runtime_context.record_action("control_media", {"action": "pause"}, ToolResult("failure", "Playback could not be verified."))
    context = store.get_runtime_context()
    assert context["active_service"] == "youtube"
    assert context["current_media"] == "Current song"
    assert context["failed_operation"]["tool"] == "control_media"
    assert analyze_utterance("Play another song", context).kind == "follow_up"


def test_recent_turns_persist_as_short_term_state():
    store.append_runtime_turn("Open GitHub", "Opened GitHub.", "action")
    reloaded = store.get_runtime_context()
    assert reloaded["recent_turns"][-1]["user"] == "Open GitHub"
    assert reloaded["recent_turns"][-1]["intent"] == "action"


def test_browser_action_updates_current_page_and_service(monkeypatch):
    import app.tools.browser_session as browser_session_module

    class FakeSession:
        def snapshot(self):
            return [{"key": "wikipedia", "url": "https://www.wikipedia.org/w/index.php?search=Python"}]

    monkeypatch.setattr(browser_session_module, "get_browser_session", lambda: FakeSession())
    runtime_context.record_action(
        "browser_search",
        {"target": "wikipedia", "query": "Python"},
        ToolResult("success", "Searched wikipedia for Python."),
    )
    context = store.get_runtime_context()
    assert context["current_target"] == "wikipedia"
    assert context["active_service"] == "wikipedia"
    assert context["page_url"].startswith("https://www.wikipedia.org/")


def test_independent_safe_tools_can_run_in_parallel_but_same_browser_cannot():
    agent = Agent()
    assert agent._can_run_parallel(
        [("open_app", {"name": "Brave"}), ("get_weather", {"location": "Tokyo"})],
        "Open Brave and check the weather in Tokyo",
    )
    assert not agent._can_run_parallel(
        [("browser_open", {"target": "github"}), ("browser_search", {"target": "wikipedia", "query": "Python"})],
        "Open GitHub and search Wikipedia for Python",
    )


def test_parallel_safe_tools_overlap_in_execution():
    barrier = threading.Barrier(2)
    names = ["_test_parallel_one", "_test_parallel_two"]

    def build_operation(label):
        def operation():
            barrier.wait(timeout=2)
            return f"finished {label}"
        return operation

    for index, name in enumerate(names):
        register(Tool(
            name=name,
            description="Temporary parallel test operation",
            parameters={"type": "object", "properties": {}},
            func=build_operation(index),
            parallel_safe=True,
            resource=f"parallel-{index}",
        ))
    try:
        outcomes, confirmation = Agent()._execute_calls([(names[0], {}), (names[1], {})], "Run both checks")
    finally:
        for name in names:
            REGISTRY.pop(name, None)
    assert confirmation is None
    assert len(outcomes) == 2


def test_pending_action_can_be_cancelled_naturally():
    agent = Agent()
    agent.pending = ("close_app", {"name": "notepad"}, 9999999999)
    reply = agent.respond("Don't do that")
    assert "cancel" in reply.lower()
    assert agent.pending is None


def test_closing_the_current_browser_clears_stale_browser_and_media_context():
    runtime_context.update_context(
        current_application="brave", current_browser="brave", current_target="youtube",
        browser_target="youtube", page_url="https://youtube.com/watch?v=abc",
        active_pages=[{"key": "youtube", "url": "https://youtube.com/watch?v=abc"}],
        active_media="youtube", current_media="Example song", media_state="playing",
    )

    runtime_context.record_action(
        "close_app", {"name": "brave"},
        ToolResult("success", "Closed Brave. Verified no matching process remains.", verification_status="verified"),
    )

    context = runtime_context.get_context()
    assert context["current_application"] == ""
    assert context["current_browser"] == ""
    assert context["current_target"] == ""
    assert context["browser_target"] == ""
    assert context["page_url"] == ""
    assert context["active_pages"] == []
    assert context["active_media"] == ""
    assert context["media_state"] == "stopped"


def test_close_app_resolves_that_browser_from_conversation_context(monkeypatch):
    runtime_context.update_context(current_application="brave", current_browser="brave")
    monkeypatch.setattr(apps, "_matching_processes", lambda _targets: [])

    result = apps.close_app("that browser")

    assert result.status == "success"
    assert result.message == "Brave is already closed."

    runtime_context.record_action("close_app", {"name": "that browser"}, result)
    context = runtime_context.get_context()
    assert context["current_application"] == ""
    assert context["current_browser"] == ""
    assert context["page_url"] == ""


def test_tool_strings_are_classified_as_failures_and_context_kept():
    name = "_test_failure_tool"
    register(Tool(name=name, description="Temporary failure test tool", parameters={"type": "object", "properties": {}}, func=lambda: "Error: operation failed"))
    try:
        result = run_tool_result(name, {})
    finally:
        REGISTRY.pop(name, None)
    assert result.status == "failure"


def test_voice_transcript_deduplication_and_speech_filter():
    service = VoiceService()
    assert service._is_new_transcript("Open GitHub", now=1.0)
    assert not service._is_new_transcript(" open   github ", now=2.0)
    assert service._is_new_transcript("Open GitHub", now=4.0)
    text = service._speech_text("Done.\n```json\n{\"tool_calls\": []}\n```")
    assert "tool_calls" not in text
    assert text.startswith("Done.")


def test_stt_transcription_and_vad_end_of_speech(monkeypatch):
    import numpy as np

    class FakeModel:
        def transcribe(self, _samples, **_kwargs):
            return [SimpleNamespace(text="open github")], None

    service = VoiceService()
    service._stt_model = FakeModel()
    assert service._transcribe(bytes(3200), np) == "open github"

    class FakeStream:
        def read(self, _frames):
            time.sleep(0.045)
            return bytes(VoiceService.WAKE_FRAME_SAMPLES * 2), False

    class FakeVad:
        def __init__(self):
            self.frame = 0

        def is_speech(self, _frame, _sample_rate):
            self.frame += 1
            return self.frame <= 3

    monkeypatch.setattr(config, "VOICE_END_SILENCE_MS", 300)
    monkeypatch.setattr(config, "VOICE_MAX_COMMAND_SECONDS", 3)
    service._stop.clear()
    captured = service._capture_command(FakeStream(), FakeVad())
    assert len(captured) >= VoiceService.VAD_FRAME_BYTES * 3


def test_voice_listener_start_stop_releases_its_worker():
    service = VoiceService()
    ready = threading.Event()
    service._load_models = lambda: None

    def fake_listen():
        ready.set()
        service._stop.wait(2)

    service._listen = fake_listen
    service.start()
    assert ready.wait(1)
    service.stop()
    status = service.status()
    assert status["phase"] == "stopped"
    assert status["enabled"] is False
    assert service._thread is None


def test_voice_service_marks_disabled_after_stop_and_retries_on_mic_failure(monkeypatch):
    service = VoiceService()
    service._stop.clear()
    service._load_models = lambda: None

    def failing_listen():
        raise OSError("No microphone available")

    service._listen = failing_listen
    service.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        phase = service.status()["phase"]
        if phase in {"recovering", "stopped", "starting"}:
            break
        time.sleep(0.05)
    assert service.status()["phase"] in {"starting", "recovering", "stopped"}
    service.stop()
    status = service.status()
    assert status["enabled"] is False
    assert status["phase"] in {"stopped", "stopping"}


def test_stopping_during_model_load_is_responsive_and_does_not_open_mic():
    service = VoiceService()
    loading = threading.Event()
    release = threading.Event()
    opened_mic = []

    def slow_model_load():
        loading.set()
        release.wait(4)

    service._load_models = slow_model_load
    service._listen = lambda: opened_mic.append(True)
    service.start()
    assert loading.wait(1)

    started = time.monotonic()
    service.stop()
    assert time.monotonic() - started < 3
    assert service.status()["phase"] == "stopping"

    release.set()
    thread = service._thread
    assert thread is not None
    thread.join(timeout=1)
    service.stop()
    assert not opened_mic
    assert service.status()["phase"] == "stopped"
    assert service._thread is None


def test_tts_engine_uses_final_text_and_returns_after_synthesis(monkeypatch):
    calls = []

    class FakeEngine:
        def setProperty(self, name, value):
            calls.append(("property", name, value))

        def say(self, text):
            calls.append(("say", text))

        def runAndWait(self):
            calls.append(("wait",))

    monkeypatch.setitem(sys.modules, "pyttsx3", types.SimpleNamespace(init=lambda _driver: FakeEngine()))
    service = VoiceService()
    service._speak("The site is open. ```json {\"name\": \"browser_open\"}```")
    assert calls[-2][0] == "say"
    assert "browser_open" not in calls[-2][1]
    assert calls[-1] == ("wait",)
