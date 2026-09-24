import logging

from app import tools  # noqa: F401  (loads and registers tools)
from app.agent.prompts import build_system_prompt
from app.core import config
from app.llm import client
from app.tools.registry import get_schemas, run_tool

log = logging.getLogger("jarvis.agent")

MAX_TOOL_STEPS = 4


class Agent:
    def __init__(self):
        self.history: list[dict] = []  # only user/assistant text is kept between turns

    def respond(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})
        self.history = self.history[-config.MAX_HISTORY_MESSAGES:]

        messages = [{"role": "system", "content": build_system_prompt()}] + self.history
        reply = "I couldn't complete that request."

        for _ in range(MAX_TOOL_STEPS):
            msg = client.chat(messages, tools=get_schemas())
            if not msg.tool_calls:
                reply = msg.content or ""
                break
            messages.append(msg)
            for call in msg.tool_calls:
                name = call.function.name
                args = dict(call.function.arguments or {})
                result = run_tool(name, args)
                log.info("Tool %s -> %s", name, result)
                messages.append({"role": "tool", "content": result, "tool_name": name})

        self.history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self):
        self.history.clear()


agent = Agent()
