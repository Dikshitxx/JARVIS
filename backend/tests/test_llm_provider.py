import asyncio
from types import SimpleNamespace

import pytest

from app.core import config
from app.llm import llm


def _response(content="", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _FakeClient:
    def __init__(self, result):
        self.result = result
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **_kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def reset_provider_metrics(monkeypatch):
    monkeypatch.setattr(llm, "_PROVIDER_METRICS", {})


def test_invalid_gemini_key_falls_back_to_groq(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "bad-key", raising=False)
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key", raising=False)
    providers = []
    clients = iter([
        _FakeClient(RuntimeError("invalid key")),
        _FakeClient(_response("groq answer")),
    ])

    def get_client(provider):
        providers.append(provider)
        return next(clients)

    monkeypatch.setattr(llm, "_client", get_client)

    result = asyncio.run(llm.chat([{"role": "user", "content": "Hello"}]))

    assert result == {"provider": "Groq", "model": config.GROQ_MODEL, "text": "groq answer", "tool_calls": []}
    assert providers == ["Gemini", "Groq"]


def test_rate_limit_falls_back_to_next_configured_provider(monkeypatch):
    class RateLimitError(RuntimeError):
        pass

    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-key", raising=False)
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key", raising=False)
    providers = []

    def get_client(provider):
        providers.append(provider)
        if provider == "Gemini":
            return _FakeClient(RateLimitError("rate limit"))
        return _FakeClient(_response("groq reply"))

    monkeypatch.setattr(llm, "_client", get_client)

    result = asyncio.run(llm.chat([{"role": "user", "content": "Hello"}]))

    assert result == {"provider": "Groq", "model": config.GROQ_MODEL, "text": "groq reply", "tool_calls": []}
    assert providers == ["Gemini", "Groq"]


def test_chat_sync_reuses_persistent_loop_across_calls(monkeypatch):
    async def fake_chat(*args, **kwargs):
        return {"provider": "Ollama", "model": config.OLLAMA_MODEL, "text": "reply", "tool_calls": []}

    monkeypatch.setattr(llm, "chat", fake_chat)
    first = llm.chat_sync([{"role": "user", "content": "one"}])
    second = llm.chat_sync([{"role": "user", "content": "two"}])

    assert first == {"provider": "Ollama", "model": config.OLLAMA_MODEL, "text": "reply", "tool_calls": []}
    assert second == first


def test_private_request_uses_only_local_and_parses_tool_arguments(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-key", raising=False)
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key", raising=False)
    calls = []
    providers = []
    response = _response(tool_calls=[SimpleNamespace(
        id="call-1",
        function=SimpleNamespace(name="get_time", arguments='{"timezone":"UTC"}'),
    )])

    async def create(**kwargs):
        calls.append(kwargs)
        return response

    def get_client(provider):
        providers.append(provider)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(llm, "_client", get_client)

    result = asyncio.run(llm.chat([{"role": "user", "content": "time"}], private=True))

    assert len(calls) == 1
    assert providers == ["Ollama"]
    assert result["tool_calls"] == [{
        "id": "call-1", "name": "get_time", "arguments": {"timezone": "UTC"},
    }]


def test_profile_provider_ranking_drives_chat_selection_and_attribution(monkeypatch):
    from app.agent.task_profile import TaskProfile

    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-key", raising=False)
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key", raising=False)
    monkeypatch.setattr(
        config, "LLM_PROVIDER_QUALITY",
        '{"Gemini": 0.1, "Groq": 0.9, "Ollama": 0.0}', raising=False,
    )
    providers = []

    def get_client(provider):
        providers.append(provider)
        return _FakeClient(_response("ranked provider reply"))

    monkeypatch.setattr(llm, "_client", get_client)
    profile = TaskProfile(
        intent="search_web",
        category="research_current",
        reasoning_level="high",
        fresh_information_required=True,
        required_tools=("search_web",),
        available_tools=("search_web",),
        privacy_level="standard",
        action_risk="none",
        multi_step_required=False,
        verification_required=True,
        context_required=False,
        required_capabilities=frozenset({"tool_calling"}),
    )

    with llm.task_profile_scope(profile):
        result = asyncio.run(llm.chat(
            [{"role": "user", "content": "Find current information."}],
            tools=[{"type": "function"}],
        ))

    assert providers == ["Groq"]
    assert result["provider"] == "Groq"
    assert result["text"] == "ranked provider reply"


def test_profile_without_a_capable_provider_fails_before_calling_any_provider(monkeypatch):
    from app.agent.task_profile import TaskProfile

    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-key", raising=False)
    monkeypatch.setattr(config, "GROQ_API_KEY", "groq-key", raising=False)
    monkeypatch.setattr(llm, "_PROVIDER_CAPABILITIES", {
        "Gemini": frozenset({"chat"}),
        "Groq": frozenset({"chat"}),
        "Ollama": frozenset({"chat", "local_execution"}),
    })
    client_calls = []
    monkeypatch.setattr(llm, "_client", lambda provider: client_calls.append(provider))
    profile = TaskProfile(
        intent="search_web",
        category="research_current",
        reasoning_level="high",
        fresh_information_required=True,
        required_tools=("search_web",),
        available_tools=("search_web",),
        privacy_level="standard",
        action_risk="none",
        multi_step_required=False,
        verification_required=True,
        context_required=False,
        required_capabilities=frozenset({"tool_calling"}),
    )

    with llm.task_profile_scope(profile):
        with pytest.raises(RuntimeError, match="No configured LLM provider satisfies"):
            asyncio.run(llm.chat(
                [{"role": "user", "content": "Find current information."}],
                tools=[{"type": "function"}],
            ))

    assert client_calls == []


def test_normalize_response_keeps_provider_and_tool_call_shape(monkeypatch):
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content="Answer",
        tool_calls=[SimpleNamespace(
            id="call-42",
            function=SimpleNamespace(
                name="search_web",
                arguments='{"query":"latest nasa news","result_index":0}',
            ),
        )],
    ))])

    assert llm._normalize_response(response, "Groq") == {
        "provider": "Groq",
        "model": "",
        "text": "Answer",
        "tool_calls": [{
            "id": "call-42",
            "name": "search_web",
            "arguments": {"query": "latest nasa news", "result_index": 0},
        }],
    }


def test_vision_request_prefers_gemini_and_sends_image_as_data_url(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-key", raising=False)
    image = tmp_path / "screen.png"
    image.write_bytes(b"image-bytes")
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return _response("The desktop is visible.")

    monkeypatch.setattr(llm, "_client", lambda provider: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    ))

    result = asyncio.run(llm.chat(
        [{"role": "user", "content": "What is on screen?"}],
        vision=True,
        image_path=str(image),
    ))

    image_url = calls[0]["messages"][0]["content"][1]["image_url"]["url"]
    assert result["provider"] == "Gemini"
    assert image_url == "data:image/png;base64,aW1hZ2UtYnl0ZXM="
