from types import SimpleNamespace

from app.tools import browser
from app.tools.browser_targets import normalize_target, parse_browser_intent, resolve_target
from app.tools.registry import REGISTRY


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
    assert "current external evidence" in REGISTRY["search_web"].description


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


def test_whatsapp_browser_target_is_registered():
    assert resolve_target("whatsapp") is not None
    assert resolve_target("whatsapp messenger").name == "whatsapp"
    assert resolve_target("whatsapp web").name == "whatsapp"
    assert normalize_target("WhatsApp Messenger") == "whatsapp"
    assert parse_browser_intent("Open WhatsApp Messenger.") == {
        "intent": "browser_open",
        "target": "whatsapp",
        "query": "",
        "operation": "open",
    }


def test_brave_navigation_reports_verified_page_url(monkeypatch):
    class FakeSession:
        def run(self, func):
            return func()

        def page(self, _key, url):
            return SimpleNamespace(url=url)

    monkeypatch.setattr(browser, "get_browser_session", lambda: FakeSession())

    result = browser._launch_brave("https://en.wikipedia.org/w/index.php?search=floods", "search_web", "floods")

    assert result.status == "success"
    assert result.verification_status == "verified"
    assert "https://en.wikipedia.org/w/index.php?search=floods" in result.message
