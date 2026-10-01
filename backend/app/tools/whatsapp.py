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
    description="Send exactly the user-authorized message to a named contact through JARVIS's logged-in WhatsApp Web profile. Use only when the user clearly asks to send a message and supplies its content; the safety layer will request confirmation before sending. Never use for general questions or web research. A separately opened native WhatsApp app is not controlled.",
    parameters={
        "type": "object",
        "properties": {"contact": {"type": "string"}, "message": {"type": "string"}},
        "required": ["contact", "message"],
    },
    func=send_whatsapp_message,
    risk="confirm",
))
