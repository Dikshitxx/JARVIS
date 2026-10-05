from dataclasses import replace
from statistics import quantiles
from time import perf_counter

import pytest

from app.agent.request import build_user_request
from app.agent.task_profile import build_task_profile
from app.agent.utterance import analyze_utterance
from app.llm import llm
from app.tools.registry import REGISTRY, Tool


@pytest.fixture(autouse=True)
def reset_provider_metrics(monkeypatch):
    monkeypatch.setattr(llm, "_PROVIDER_METRICS", {})


def _profile(text, *, private=False, candidates=None, classifier=None):
    analysis = analyze_utterance(text, {})
    request = build_user_request(text, {}, analysis)
    return build_task_profile(
        request,
        analysis,
        {},
        private=private,
        candidate_tool_names=candidates,
        classifier=classifier,
    )


def test_current_information_profile_requires_search_and_verification():
    profile = _profile(
        "What are the latest developments?",
        candidates={"search_web", "fetch_web_page"},
    )

    assert profile.category == "research_current"
    assert profile.fresh_information_required
    assert "tool_calling" in profile.required_capabilities
    assert profile.verification_required
    assert "fresh_information_workflow" in profile.required_capabilities


def test_ordinary_conversation_profile_does_not_require_tools():
    profile = _profile("I'm tired today. Let's chat.", candidates=set())

    assert profile.category == "conversation"
    assert not profile.fresh_information_required
    assert profile.required_tools == ()
    assert "tool_calling" not in profile.required_capabilities


def test_historical_weather_question_does_not_require_fresh_information():
    profile = _profile("Explain the history of weather forecasting.")

    assert not profile.fresh_information_required
    assert "fresh_information" not in profile.required_tool_capabilities
    assert profile.category != "research_current"


def test_current_task_capability_is_discovered_from_tool_metadata(monkeypatch):
    synthetic_name = "synthetic_live_lookup"
    monkeypatch.setitem(REGISTRY, synthetic_name, Tool(
        name=synthetic_name,
        description="A synthetic live information lookup.",
        parameters={"type": "object", "properties": {}},
        func=lambda: None,
        capabilities=frozenset({"synthetic"}),
        metadata={
            "task_capabilities": ["fresh_information"],
            "provider_capabilities": ["fresh_information_workflow"],
        },
    ))
    analysis = analyze_utterance("Latest service updates this week", {})
    request = build_user_request("Latest service updates this week", {}, analysis)
    profile = build_task_profile(
        request, analysis, {}, candidate_tool_names={synthetic_name},
    )

    assert profile.fresh_information_required
    assert "fresh_information" in profile.required_tool_capabilities
    assert "fresh_information_workflow" in profile.required_capabilities
    assert "tool_calling" in profile.required_capabilities


def test_private_profile_cannot_be_weakened_by_optional_classifier():
    def classifier(_request, signals):
        return replace(
            signals,
            category="research_current",
            privacy_level="standard",
            required_capabilities=frozenset(),
        )

    profile = _profile(
        "Review my confidential notes.",
        private=True,
        candidates={"read_file"},
        classifier=type("InjectedClassifier", (), {"classify": staticmethod(classifier)})(),
    )

    assert profile.category == "local_private"
    assert profile.privacy_level == "private"
    assert "local_execution" in profile.required_capabilities


def test_optional_classifier_failure_uses_deterministic_profile(caplog):
    class BrokenClassifier:
        def classify(self, _request, _signals):
            raise RuntimeError("unavailable")

    profile = _profile("Hello.", candidates=set(), classifier=BrokenClassifier())

    assert profile.category == "conversation"
    assert "using structured request signals" in caplog.text


def test_task_profile_builder_has_low_local_latency():
    analysis = analyze_utterance("What are the latest developments?", {})
    request = build_user_request("What are the latest developments?", {}, analysis)
    samples = []
    for _ in range(100):
        start = perf_counter()
        build_task_profile(request, analysis, {}, candidate_tool_names={"search_web"})
        samples.append((perf_counter() - start) * 1000)

    p95 = quantiles(samples, n=20)[18]
    assert p95 < 10


def test_profile_provider_selection_uses_configured_quality_before_legacy_order(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "gemini", raising=False)
    monkeypatch.setattr(llm.config, "GROQ_API_KEY", "groq", raising=False)
    monkeypatch.setattr(
        llm.config, "LLM_PROVIDER_QUALITY",
        '{"Gemini": 0.1, "Groq": 0.9, "Ollama": 0.0}', raising=False,
    )
    monkeypatch.setattr(llm.config, "LLM_PROVIDER_COST", '{"Gemini": 0.5, "Groq": 0.5}', raising=False)
    profile = _profile("Find current developments.", candidates={"search_web"})

    assert llm._select_capable_providers(profile, "smart", False, set()) == [
        "Groq", "Gemini",
    ]


def test_private_profile_eliminates_cloud_providers_even_when_they_score_higher(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "gemini", raising=False)
    monkeypatch.setattr(llm.config, "GROQ_API_KEY", "groq", raising=False)
    monkeypatch.setattr(llm.config, "LLM_PROVIDER_QUALITY", '{"Gemini": 1, "Groq": 1}', raising=False)
    profile = _profile("Use my private notes.", private=True, candidates={"read_file"})

    assert llm._select_capable_providers(profile, "smart", False, set()) == ["Ollama"]


def test_multistep_profile_requires_reasoning_capability():
    profile = _profile(
        "Find current AI jobs, compare the requirements, and summarize application links.",
        candidates={"search_web", "fetch_web_page"},
    )

    assert profile.multi_step_required
    assert profile.reasoning_level == "high"
    assert "reasoning" in profile.required_capabilities
