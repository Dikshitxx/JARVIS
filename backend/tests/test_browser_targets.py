from app.agent.agent import _select_relevant_tools
from app.tools.browser_targets import normalize_target, parse_browser_intent, resolve_target


def test_generic_browser_search_intents():
    cases = [
        ("Search Jarvis AI on ChatGPT.", "chatgpt", "Jarvis AI", "browser_search"),
        ("Search FastAPI on Claude.", "claude", "FastAPI", "browser_search"),
        ("Search AI news on Grok.", "grok", "AI news", "browser_search"),
        ("Search Python decorators on Wikipedia.", "wikipedia", "Python decorators", "browser_search"),
        ("Search React tutorials on YouTube.", "youtube", "React tutorials", "browser_search"),
    ]
    for text, target, query, intent in cases:
        parsed = parse_browser_intent(text)
        assert parsed["target"] == target
        assert parsed["query"] == query
        assert parsed["intent"] == intent


def test_general_search_is_not_targeted_browser_search():
    assert parse_browser_intent("Search the web for Jarvis AI.") is None
    assert _select_relevant_tools("Search the web for Jarvis AI") == {"open_url", "search_web"}


def test_open_and_ask_and_navigate_intents():
    assert parse_browser_intent("Open Wikipedia.")["intent"] == "browser_open"
    asked = parse_browser_intent("Ask Claude to explain FastAPI.")
    assert asked == {"intent": "browser_interaction", "target": "claude", "query": "FastAPI", "operation": "interact"}
    navigated = parse_browser_intent("Go to GitHub and find FastAPI.")
    assert navigated["target"] == "github"
    assert navigated["query"] == "FastAPI"
    assert navigated["operation"] == "navigate_search"


def test_aliases_and_unknown_targets():
    assert resolve_target("google.com").name == "google"
    assert normalize_target("Chat GPT") == "chatgpt"
    assert normalize_target("YT") == "youtube"
    assert resolve_target("ExampleSite") is None
    assert parse_browser_intent("Search X on ExampleSite")["target"] == "examplesite"