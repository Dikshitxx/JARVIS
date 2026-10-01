import threading
import time
from types import SimpleNamespace

import pytest

from app.agent import agent as agent_module
from app.agent import runtime_context
from app.agent.agent import Agent
from app.agent.utterance import UtteranceAnalysis
from app.api.routes import chat
from app.core import config
from app.llm import client as llm_client
from app.memory import store
from app.tasks import TaskManager, create_task, normalize_task_status, task_scope, task_manager, update_task
from app.tools import apps, registry
from app.tools.registry import Tool, ToolResult, register, run_tool_result


@pytest.fixture
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jarvis-test.db")
    store.clear_runtime_context()


def test_request_context_only_commits_for_the_latest_task(isolated_database):
    store.clear_runtime_context()
    first = "first-task"
    first_context = runtime_context.activate_request(first)
    with runtime_context.request_context_scope(first, first_context):
        runtime_context.update_context(current_task="older request")
        second = "second-task"
        second_context = runtime_context.activate_request(second)
        with runtime_context.request_context_scope(second, second_context):
            runtime_context.update_context(current_task="newer request")

    assert store.get_runtime_context()["current_task"] == "newer request"
    assert store.get_runtime_context()["active_request_id"] == second


def test_cancelling_waiting_confirmation_clears_pending_agent_state(isolated_database, monkeypatch):
    from app.agent.agent import agent

    task_id = create_task("close Brave")
    update_task(task_id, status="WAITING_CONFIRMATION", current_step="Waiting for confirmation")
    monkeypatch.setattr(agent, "pending", ("close_app", {"name": "brave"}, time.time()))
    monkeypatch.setattr(agent, "pending_task_id", task_id)
    monkeypatch.setattr(agent, "pending_continuation", {"user_text": "close Brave and open Edge"})
    runtime_context.update_context(pending_operation={
        "tool": "close_app", "args": {"name": "brave"}, "status": "confirmation_required",
        "created_at": time.time(), "task_id": task_id,
    })

    cancelled = task_manager.cancel_latest()

    assert cancelled["status"] == "CANCELLED"
    assert agent.pending is None
    assert agent.pending_task_id is None
    assert agent.pending_continuation is None
    assert runtime_context.get_context()["pending_operation"] == {}


def test_tool_execution_is_recorded_and_sensitive_arguments_are_redacted(isolated_database, monkeypatch):
    name = "test_task_recorded_tool"
    tool = Tool(
        name=name,
        description="A tool used by the task engine test.",
        parameters={"type": "object", "properties": {"text": {"type": "string"}, "token": {"type": "string"}}},
        func=lambda text, token: ToolResult("success", "completed", verification_status="verified"),
        capabilities=frozenset({"test"}),
        side_effect=True,
    )
    monkeypatch.setitem(registry.REGISTRY, name, tool)
    register(tool)
    task_id = create_task("record a test tool step")
    runtime_context.activate_request(task_id)
    initial = runtime_context.get_context()

    with task_scope(task_id, threading.Event()), runtime_context.request_context_scope(task_id, initial):
        result = run_tool_result(name, {"text": "private note", "token": "secret"})

    assert result.status == "success"
    step = TaskManager().task(task_id)["steps"][0]
    assert step["status"] == "success"
    assert step["arguments"] == {"text": "[redacted; 12 characters]", "token": "[redacted]"}
    assert step["verification"] == "verified"


def test_task_cancellation_is_cooperative_and_keeps_result_truthful(isolated_database, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    manager = TaskManager(workers=1, queued=1, timeout_seconds=5)

    def blocking_response(_request):
        started.set()
        release.wait(3)
        return "The current operation finished."

    monkeypatch.setattr(agent_module.agent, "respond", blocking_response)
    task_id = manager.submit("perform a slow operation")
    assert started.wait(2)
    requested = manager.cancel(task_id)
    assert requested["cancellation_requested"] is True
    release.set()
    manager._futures[task_id].result(timeout=3)

    task = manager.task(task_id)
    assert task["status"] == "CANCELLED"
    assert "finished" in task["result"].lower()


def test_unverified_side_effect_is_not_retried_unless_declared_safe(monkeypatch):
    name = "test_nonretryable_side_effect"
    calls = []
    tool = Tool(
        name=name,
        description="A non-repeatable operation used by the task engine test.",
        parameters={"type": "object", "properties": {}},
        func=lambda: calls.append("ran") or "operation ran",
        verify=lambda _args, _result: False,
        side_effect=True,
    )
    monkeypatch.setitem(registry.REGISTRY, name, tool)
    register(tool)
    monkeypatch.setattr(registry._memory_store, "log_tool_execution", lambda *_args, **_kwargs: None)

    result = run_tool_result(name, {})

    assert calls == ["ran"]
    assert result.status == "failure"
    assert "did not retry" in result.message


def test_retry_safe_infrastructure_failure_recovers_resource_then_retries(monkeypatch):
    from app import recovery

    name = "test_retry_safe_browser_operation"
    calls = []
    recoveries = []

    def operation():
        calls.append("run")
        if len(calls) == 1:
            return ToolResult("failure", "Target page, context or browser has been closed", verification_status="failed")
        return ToolResult("success", "Opened and verified", verification_status="verified")

    tool = Tool(
        name=name,
        description="A safe browser operation used by the recovery test.",
        parameters={"type": "object", "properties": {}},
        func=operation,
        resource="test_browser_resource",
        side_effect=True,
        retry_safe=True,
    )
    monkeypatch.setitem(registry.REGISTRY, name, tool)
    monkeypatch.setitem(recovery._RESOURCE_RECOVERERS, "test_browser_resource", lambda: recoveries.append("recovered") or True)
    monkeypatch.setattr(registry._memory_store, "log_tool_execution", lambda *_args, **_kwargs: None)

    result = run_tool_result(name, {})

    assert calls == ["run", "run"]
    assert recoveries == ["recovered"]
    assert result.status == "success"
    assert result.verification_status == "verified"


def test_execution_state_distinguishes_success_without_evidence():
    unverified = ToolResult("success", "Launch command returned successfully.", verification_status="unknown")
    verified = ToolResult("success", "Launch confirmed in the app list.", verification_status="verified")

    assert unverified.execution_state == "executed"
    assert unverified.verification_state == "unverified"
    assert unverified.is_verified is False

    assert verified.execution_state == "verified"
    assert verified.verification_state == "verified"
    assert verified.is_verified is True


def test_false_success_requires_explicit_verification_before_task_completion():
    result = ToolResult("success", "Message send returned without a confirmed chat state.", verification_status="unknown")

    assert result.execution_state == "executed"
    assert result.verification_state == "unverified"
    assert result.final_outcome == "UNVERIFIED"


def test_background_task_status_uses_canonical_lifecycle_names():
    assert normalize_task_status("pending") == "QUEUED"
    assert normalize_task_status("waiting for user input") == "WAITING_FOR_USER_INPUT"
    assert normalize_task_status("waiting_confirmation") == "WAITING_FOR_USER_INPUT"
    assert normalize_task_status("timed_out") == "TIMED_OUT"
    assert normalize_task_status("interrupted") == "INTERRUPTED"


def test_background_chat_returns_immediate_progress_response():
    response = chat(type("Req", (), {"message": "Research this topic and prepare an email.", "background": True})())

    assert response["status"] == "QUEUED"
    assert "working on" in response["reply"].lower()
    assert response["task_id"]


def test_environment_snapshot_reuses_fresh_state(monkeypatch):
    calls = {"snapshot": 0}

    monkeypatch.setattr(apps, "get_active_window_info", lambda: {"title": "Test Window", "application": "chrome", "pid": 123})

    class FakeBrowser:
        def snapshot(self):
            calls["snapshot"] += 1
            return [{"url": "https://example.com", "key": "page-1"}]

    monkeypatch.setattr(apps, "_ENV_SNAPSHOT_CACHE", {"payload": None, "fetched_at": 0.0})
    import app.tools.browser_session as browser_session

    monkeypatch.setattr(browser_session, "get_browser_session", lambda: FakeBrowser())

    first = apps.inspect_environment()
    second = apps.inspect_environment()

    assert first.status == "success"
    assert second.status == "success"
    assert calls["snapshot"] == 1


def test_llm_metrics_record_latency_for_each_call(monkeypatch):
    llm_client.clear_llm_metrics()

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def chat(self, *args, **kwargs):
            self.calls += 1
            return {"message": {"content": "ok"}}

    fake = FakeClient()
    monkeypatch.setattr(llm_client, "_client", fake)

    llm_client.chat([{"role": "user", "content": "hi"}])
    llm_client.chat([{"role": "user", "content": "again"}])

    metrics = llm_client.get_llm_metrics()
    assert len(metrics) >= 2
    assert all("latency_ms" in item for item in metrics)
