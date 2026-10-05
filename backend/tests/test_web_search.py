import pytest

from app.tools import browser
from app.tools.registry import ToolResult
from app.tools.web_search import HttpWebSearchProvider


def test_http_search_provider_combines_and_deduplicates_sources(monkeypatch, caplog):
    duckduckgo = """
    <div class="result"><a class="result__a" href="https://example.org/a">First source</a>
    <a class="result__snippet">Evidence from provider one.</a></div>
    """
    bing = """
    <li class="b_algo"><h2><a href="https://example.org/a">Duplicate result</a></h2><p>Duplicate evidence.</p></li>
    <li class="b_algo"><h2><a href="https://other.example/b">Second source</a></h2><p>Evidence from provider two.</p></li>
    """
    provider = HttpWebSearchProvider("auto")
    monkeypatch.setattr(provider, "_get_html", lambda name, _query: duckduckgo if name == "duckduckgo" else bing)

    with caplog.at_level("INFO", logger="jarvis.web_search"):
        results = provider.search("latest movie")

    assert {result["url"] for result in results} == {"https://example.org/a", "https://other.example/b"}
    assert {result["provider"] for result in results} == {"duckduckgo", "bing"}
    assert all(result["title"] and result["snippet"] and result["source"] for result in results)
    assert "latest movie" not in caplog.text


def test_extract_content_omits_scripts_and_bounds_page_text(monkeypatch):
    provider = HttpWebSearchProvider("duckduckgo")
    monkeypatch.setattr(provider, "fetch", lambda _url: "<html><body><script>fake text</script><main><p>Visible page evidence.</p></main></body></html>")

    content = provider.extract_content("https://example.org/article")

    assert content == "Visible page evidence."
    assert "fake text" not in content


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434/api/tags", "http://localhost:8000/", "file:///C:/Windows/win.ini"])
def test_page_fetch_refuses_private_and_non_http_targets(url):
    with pytest.raises(ValueError):
        HttpWebSearchProvider().fetch(url)


def test_search_web_returns_actual_source_evidence_without_opening_a_browser(monkeypatch):
    class Provider:
        def search(self, query):
            return [{"title": "Current report", "url": "https://news.example/report", "source": "news.example",
                     "snippet": f"Retrieved evidence for {query}.", "provider": "mock"}]

    monkeypatch.setattr("app.tools.web_search.get_search_provider", Provider)
    monkeypatch.setattr(browser, "_set_agent_site_state", lambda **_kwargs: None)

    result = browser.search_web("current prime minister of Nepal")

    assert isinstance(result, ToolResult)
    assert result.status == "success"
    assert result.verification_status == "verified"
    assert result.data["results"][0]["url"] == "https://news.example/report"
    assert "Retrieved evidence" in result.message
