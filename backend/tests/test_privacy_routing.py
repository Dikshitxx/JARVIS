from app.agent import privacy
from app.llm import llm


def test_privacy_policy_is_deterministic_and_never_calls_a_model(monkeypatch):
    def unexpected_model_call(*_args, **_kwargs):
        raise AssertionError("privacy classification must not call an LLM")

    monkeypatch.setattr(llm, "chat_sync", unexpected_model_call)

    assert privacy.should_keep_local("Review my confidential medical notes.") is True
    assert privacy.should_keep_local("Send a note to alex@example.com") is True
    assert privacy.should_keep_local("What time is it?") is False


def test_privacy_policy_detects_secret_like_values():
    assert privacy.should_keep_local("My API key: sk-live-examplecredentialvalue") is True
    assert privacy.should_keep_local("यह निजी स्वास्थ्य रिकॉर्ड है") is True


def test_task_manager_passes_privacy_through_execution_context(monkeypatch, tmp_path):
    from app.agent import agent as agent_module
    from app.core import config
    from app.memory import store
    from app.tasks import TaskManager

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jarvis-test.db")
    store.clear_runtime_context()
    monkeypatch.setattr(agent_module.agent, "has_private_pending", lambda: False)
    observed = {}

    def respond(_request):
        observed["private"] = llm.is_private_request()
        return "Handled locally."

    monkeypatch.setattr(agent_module.agent, "respond", respond)
    manager = TaskManager(workers=1, queued=1, timeout_seconds=5)
    try:
        task_id, reply = manager.run_sync("Review my confidential notes.")
    finally:
        manager._executor.shutdown(wait=True)

    assert reply == "Handled locally."
    assert observed["private"] is True
    assert manager.task(task_id)["status"] == "SUCCEEDED"
