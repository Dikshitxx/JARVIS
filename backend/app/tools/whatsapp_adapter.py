from app.tools.browser_session import get_browser_session
from app.tools.registry import ToolResult


class WhatsAppAdapter:
    def __init__(self, session=None):
        self.session = session or get_browser_session()

    def send(self, contact: str, message: str) -> ToolResult:
        page = self.session.page("whatsapp", "https://web.whatsapp.com")
        search = page.locator('div[contenteditable="true"][data-tab="3"]')
        try:
            search.wait_for(state="visible", timeout=60000)
        except Exception:
            return ToolResult("authentication_required", "WhatsApp Web is not ready. Please log in or scan the QR code in the browser, then try again.")
        try:
            search.fill(contact)
            page.wait_for_timeout(1500)
            page.locator(f'span[title="{contact}"]').click()
            composer = page.locator('div[contenteditable="true"][data-tab="10"]')
            composer.wait_for(state="visible", timeout=10000)
            before = page.locator("div.message-out").count()
            composer.fill(message)
            composer.press("Enter")
            after = page.locator("div.message-out").count()
            if after <= before:
                return ToolResult("failure", "WhatsApp did not verify that the message was sent.")
            return ToolResult("success", f"Sent WhatsApp message to {contact}: {message}")
        except Exception as exc:
            return ToolResult("failure", f"WhatsApp message failed: {exc}")