from app.tools.browser_session import get_browser_session
from app.tools.registry import Tool, ToolResult, register
from app.tools.whatsapp_adapter import WhatsAppAdapter


def send_whatsapp_message(contact: str, message: str) -> ToolResult:
    try:
        return get_browser_session().run(WhatsAppAdapter(get_browser_session()).send, contact, message)
    except Exception as exc:
        return ToolResult("failure", f"WhatsApp message failed: {exc}")


register(Tool(
    name="send_whatsapp_message",
    description="Send a WhatsApp message to a contact by name. Requires WhatsApp Web to be logged in.",
    parameters={
        "type": "object",
        "properties": {"contact": {"type": "string"}, "message": {"type": "string"}},
        "required": ["contact", "message"],
    },
    func=send_whatsapp_message,
    risk="confirm",
))
