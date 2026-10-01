"""Small, configurable HTTP search provider with bounded page extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import ipaddress
from html.parser import HTMLParser
import logging
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.core import config

log = logging.getLogger("jarvis.web_search")
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
_VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_Node"] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(part for part in [*self.parts, *(child.text for child in self.children)] if part).strip()

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in _VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag.lower(), {key.lower(): value or "" for key, value in attrs}))

    def handle_endtag(self, tag):
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == lowered:
                del self.stack[index:]
                break

    def handle_data(self, data):
        value = " ".join(data.split())
        if value:
            self.stack[-1].parts.append(value)


def _visible_text(node: _Node) -> str:
    if node.tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
        return ""
    return " ".join(part for part in [*node.parts, *(_visible_text(child) for child in node.children)] if part).strip()


def _class_has(node: _Node, class_name: str) -> bool:
    return class_name in node.attrs.get("class", "").split()


def _decode_search_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com"):
        destination = parse_qs(parsed.query).get("uddg", [""])[0]
        if destination:
            return destination
    if parsed.netloc.endswith("bing.com") and parsed.path.startswith("/ck/a"):
        destination = parse_qs(parsed.query).get("u", [""])[0]
        if destination.startswith("a1"):
            token = destination[2:]
            token += "=" * (-len(token) % 4)
            try:
                decoded = base64.urlsafe_b64decode(token).decode("utf-8", errors="replace")
                if decoded.startswith(("http://", "https://")):
                    return decoded
            except (ValueError, base64.binascii.Error):
                pass
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        destination = parse_qs(parsed.query).get("q", [""])[0]
        if destination.startswith(("http://", "https://")):
            return destination
    return url


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) URLs without embedded credentials can be fetched.")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private and local network addresses cannot be fetched.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("Private and local network addresses cannot be fetched.")


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebSearchProvider:
    """Interface used by the agent; provider choice is isolated from reasoning."""

    def search(self, query: str) -> list[dict]:
        raise NotImplementedError

    def fetch(self, url: str) -> str:
        raise NotImplementedError

    def extract_content(self, url: str) -> str:
        raise NotImplementedError

    def browser_fallback(self, query: str) -> list[dict]:
        raise NotImplementedError


class HttpWebSearchProvider(WebSearchProvider):
    def __init__(self, provider: str = "auto", timeout: int | None = None):
        self.provider = (provider or "auto").strip().lower()
        self.timeout = timeout or config.WEB_SEARCH_TIMEOUT_SECONDS

    def _request(self, url: str) -> bytes:
        _validate_public_url(url)
        request = Request(url, headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.8"})
        opener = build_opener(_PublicRedirectHandler())
        with opener.open(request, timeout=self.timeout) as response:
            return response.read(1_500_001)

    def fetch(self, url: str) -> str:
        raw = self._request(url)
        if len(raw) > 1_500_000:
            raw = raw[:1_500_000]
        return raw.decode("utf-8", errors="replace")

    def extract_content(self, url: str) -> str:
        source = self.fetch(url)
        parser = _DocumentParser()
        parser.feed(source)
        text_parts = [_visible_text(node) for node in parser.root.descendants() if node.tag == "body"]
        content = " ".join(text_parts or [parser.root.text])
        return " ".join(content.split())[:12_000]

    def _get_html(self, provider: str, query: str) -> str:
        encoded = quote_plus(query)
        if provider == "duckduckgo":
            url = f"https://html.duckduckgo.com/html/?q={encoded}"
        elif provider == "bing":
            url = f"https://www.bing.com/search?q={encoded}"
        else:
            raise ValueError(f"Unsupported web search provider: {provider}")
        return self._request(url).decode("utf-8", errors="replace")

    def _parse_results(self, html: str, provider: str) -> list[dict]:
        parser = _DocumentParser()
        parser.feed(html)
        nodes = list(parser.root.descendants())
        results: list[dict] = []
        if provider == "duckduckgo":
            cards = [node for node in nodes if _class_has(node, "result")]
            if not cards:
                cards = [node for node in nodes if _class_has(node, "result__body")]
            for card in cards:
                children = list(card.descendants())
                title_node = next((node for node in children if node.tag == "a" and _class_has(node, "result__a")), None)
                if title_node is None:
                    continue
                snippet_node = next((node for node in children if _class_has(node, "result__snippet")), None)
                results.append(self._result(title_node, snippet_node))
        else:
            cards = [node for node in nodes if _class_has(node, "b_algo")]
            for card in cards:
                children = list(card.descendants())
                heading = next((node for node in children if node.tag == "h2"), None)
                title_node = next((node for node in (list(heading.descendants()) if heading else [])
                                   if node.tag == "a" and node.text and node.attrs.get("href")), None)
                if title_node is None:
                    title_node = next((node for node in children if node.tag == "a" and node.text and node.attrs.get("href")), None)
                if title_node is None:
                    continue
                snippet_node = next((node for node in children if node.tag == "p"), None)
                results.append(self._result(title_node, snippet_node))
        return [item for item in results if item["title"] and item["url"]]

    @staticmethod
    def _result(title_node: _Node, snippet_node: _Node | None) -> dict:
        url = _decode_search_url(title_node.attrs.get("href", ""))
        return {
            "title": title_node.text[:300],
            "url": url,
            "snippet": (snippet_node.text if snippet_node else "")[:700],
            "source": urlparse(url).hostname or "",
        }

    def search(self, query: str) -> list[dict]:
        if self.provider in {"duckduckgo", "bing"}:
            providers = [self.provider]
        elif self.provider == "auto":
            providers = ["duckduckgo", "bing"]
        else:
            raise ValueError(f"Unsupported WEB_SEARCH_PROVIDER '{self.provider}'. Use auto, duckduckgo, or bing.")
        failures = []
        gathered = []

        def run(provider_name):
            html = self._get_html(provider_name, query)
            return provider_name, self._parse_results(html, provider_name)

        if len(providers) > 1:
            with ThreadPoolExecutor(max_workers=len(providers), thread_name_prefix="jarvis-search") as pool:
                futures = [pool.submit(run, provider_name) for provider_name in providers]
                for future in as_completed(futures):
                    try:
                        gathered.append(future.result())
                    except Exception as exc:
                        failures.append(str(exc))
        else:
            try:
                gathered.append(run(providers[0]))
            except Exception as exc:
                failures.append(str(exc))

        results = []
        seen_urls = set()
        for provider_name, provider_results in gathered:
            log.info("SEARCH_RESULTS_RECEIVED provider=%s query=%r count=%s", provider_name, query, len(provider_results))
            for item in provider_results:
                normalized_url = item["url"].rstrip("/").casefold()
                if normalized_url and normalized_url not in seen_urls:
                    seen_urls.add(normalized_url)
                    item["provider"] = provider_name
                    results.append(item)

        query_terms = {term.casefold().strip(".,!?;:'\"()[]") for term in query.split() if len(term) > 2}
        def relevance(item):
            text = f"{item['title']} {item['snippet']}".casefold()
            overlap = sum(term in text for term in query_terms)
            return (-overlap, providers.index(item["provider"]))
        results.sort(key=relevance)
        if results:
            return results
        if not failures:
            failures.append("No search provider returned readable result cards.")
        raise RuntimeError("; ".join(failures))

    def browser_fallback(self, query: str) -> list[dict]:
        """Last resort: search in managed Brave and extract real result cards."""
        from app.tools.browser_session import get_browser_session

        session = get_browser_session()

        def navigate_and_extract():
            url = config.BROWSER_SEARCH_PROVIDER.format(query=quote_plus(query))
            page = session.page("knowledge_search", url)
            anchors = page.locator("#search a:has(h3)")
            items = []
            for index in range(min(anchors.count(), config.WEB_SEARCH_RESULT_LIMIT)):
                anchor = anchors.nth(index)
                title = anchor.inner_text().strip()
                href = anchor.get_attribute("href") or ""
                try:
                    snippet = anchor.locator("xpath=../../..").inner_text().strip()
                except Exception:
                    snippet = ""
                if title and href.startswith(("http://", "https://")):
                    items.append({"title": title[:300], "url": href, "snippet": snippet[:700],
                                  "source": urlparse(href).hostname or "", "provider": "browser_fallback"})
            return items

        return session.run(navigate_and_extract)


def get_search_provider() -> WebSearchProvider:
    return HttpWebSearchProvider(config.WEB_SEARCH_PROVIDER, config.WEB_SEARCH_TIMEOUT_SECONDS)
