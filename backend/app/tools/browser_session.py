import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
from playwright.sync_api import sync_playwright

from app.core import config
from app.recovery import register_resource_recoverer

log = logging.getLogger("jarvis.browser.session")


def is_managed_browser_process(pid: int | None) -> bool:
    """Tell JARVIS's Playwright profile apart from a user's installed browser."""
    if not pid:
        return False
    profile = Path(config.BROWSER_PROFILE_DIR)
    if not profile.is_absolute():
        profile = config.DATA_DIR / profile
    try:
        expected = str(profile.resolve()).casefold().rstrip("\\/")
        arguments = psutil.Process(pid).cmdline()
    except (OSError, psutil.Error):
        return False
    for argument in arguments:
        if argument.casefold().startswith("--user-data-dir="):
            actual = argument.split("=", 1)[1].strip('"').casefold().rstrip("\\/")
            return actual == expected
    return False


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
        elif config.BROWSER_PATH:
            kwargs["executable_path"] = config.BROWSER_PATH
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
        try:
            page_missing = page is None or page.is_closed()
        except Exception:
            page_missing = True
        if page_missing:
            try:
                page = context.new_page()
            except Exception:
                # A user can close the Playwright-owned browser while JARVIS is
                # running. Recover the persistent context once instead of
                # leaving every later browser action stuck on a dead target.
                log.warning("Browser context closed while creating page %s; relaunching it.", key)
                self._close_context()
                context = self._ensure_context()
                page = context.new_page()
            self._pages[key] = page
        if url and page.url != url:
            page.goto(url, timeout=config.BROWSER_NAVIGATION_TIMEOUT)
        return page

    def get_page(self, key: str):
        return self._pages.get(key)

    def snapshot(self) -> list[dict]:
        """Return page keys and URLs from the session's owner thread."""
        def read_pages():
            pages = []
            for key, page in self._pages.items():
                try:
                    if not page.is_closed():
                        pages.append({"key": key, "url": page.url})
                except Exception:
                    continue
            return pages

        return self.run(read_pages)

    def existing_pages(self) -> list[dict]:
        """Read already-open pages without launching a browser context."""
        def read_pages():
            pages = []
            if self._context is None:
                return pages
            for key, page in self._pages.items():
                try:
                    if not page.is_closed():
                        pages.append({"key": key, "page": page})
                except Exception:
                    continue
            return pages

        return self.run(read_pages)

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


def recover_browser_session() -> bool:
    """Dispose stale Playwright state and create a fresh managed session."""
    global _SESSION
    old_session = _SESSION
    try:
        old_session.shutdown()
    except Exception:
        log.info("Stale browser session shutdown did not complete cleanly.", exc_info=True)
    _SESSION = BrowserSession()
    return True


register_resource_recoverer("browser", recover_browser_session)


def get_browser_session() -> BrowserSession:
    return _SESSION


def shutdown_browser_session() -> None:
    _SESSION.shutdown()
