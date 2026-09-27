import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.core import config

log = logging.getLogger("jarvis.browser.session")


class BrowserSession:
    """Owns all sync Playwright objects on one persistent worker thread."""

    def __init__(self):
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-browser")
        self._pw = None
        self._context = None
        self._pages: dict[str, object] = {}
        self._closed = False

    def run(self, func, *args):
        if self._closed:
            raise RuntimeError("browser session is shut down")
        return self._executor.submit(func, *args).result()

    def _ensure_context(self):
        if self._context is not None:
            try:
                _ = self._context.pages
                return self._context
            except Exception:
                log.info("Browser context is stale; recovering it.")
                self._close_context()
        self._pw = sync_playwright().start()
        profile = Path(config.BROWSER_PROFILE_DIR)
        if not profile.is_absolute():
            profile = config.DATA_DIR / profile
        kwargs = {
            "headless": config.BROWSER_HEADLESS,
        }
        if config.BROWSER_EXECUTABLE_PATH:
            kwargs["executable_path"] = config.BROWSER_EXECUTABLE_PATH
        elif config.BROWSER_CHANNEL:
            kwargs["channel"] = config.BROWSER_CHANNEL
        self._context = self._pw.chromium.launch_persistent_context(str(profile), **kwargs)
        self._pages.clear()
        return self._context

    def context(self):
        return self._ensure_context()

    def page(self, key: str, url: str | None = None):
        context = self._ensure_context()
        page = self._pages.get(key)
        if page is None or page.is_closed():
            page = context.new_page()
            self._pages[key] = page
        if url and page.url != url:
            page.goto(url, timeout=config.BROWSER_NAVIGATION_TIMEOUT)
        return page

    def get_page(self, key: str):
        return self._pages.get(key)

    def set_page(self, key: str, page) -> None:
        self._pages[key] = page

    def _close_context(self):
        self._pages.clear()
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        self._context = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._pw = None

    def shutdown(self):
        if self._closed:
            return
        try:
            self.run(self._close_context)
        finally:
            self._closed = True
            self._executor.shutdown(wait=True)


_SESSION = BrowserSession()


def get_browser_session() -> BrowserSession:
    return _SESSION


def shutdown_browser_session() -> None:
    _SESSION.shutdown()