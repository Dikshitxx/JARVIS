import json
import logging

from app import tools  # noqa: F401  (loads and registers tools)
from app.agent.prompts import build_system_prompt
from app.core import config
from app.llm import client
from app.tools.registry import REGISTRY, get_schemas, run_tool

log = logging.getLogger("jarvis.agent")

MAX_TOOL_STEPS = 4
DIRECT_REPLY_TOOLS = {"remember_fact", "forget_memory", "list_memories"}


class Agent:
    def __init__(self):
        self.history: list[dict] = []  # only user/assistant text is kept between turns

    def respond(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})
        self.history = self.history[-config.MAX_HISTORY_MESSAGES:]

        messages = [{"role": "system", "content": build_system_prompt()}] + self.history
        reply = "I couldn't complete that request."

        for _ in range(MAX_TOOL_STEPS):
            msg = None
            for attempt in range(2):
                try:
                    msg = client.chat(messages, tools=get_schemas())
                    break
                except Exception as e:
                    print(f"[agent] model error (attempt {attempt + 1}): {e}", flush=True)
            if msg is None:
                reply = "Sorry boss, I could not process that. Try rephrasing, or give me one fact at a time."
                break
            print(f"[agent] tool_calls={msg.tool_calls} content={msg.content!r}", flush=True)
            calls = []
            if msg.tool_calls:
                calls = [(c.function.name, dict(c.function.arguments or {})) for c in msg.tool_calls]
            else:
                # 3B fallback: model wrote the call as JSON text instead of calling it
                try:
                    data = json.loads(msg.content or "")
                    if isinstance(data, dict) and data.get("name") in REGISTRY:
                        calls = [(data["name"], data.get("parameters") or data.get("arguments") or {})]
                except (json.JSONDecodeError, TypeError):
                    pass

            if not calls:
                reply = msg.content or ""
                break

            messages.append({"role": "assistant", "content": msg.content or ""})
            results = []
            for name, args in calls:
                result = run_tool(name, args)
                results.append((name, result))
                print(f"[agent] ran {name} {args} -> {result[:200]!r}", flush=True)
                log.info("Tool %s -> %s", name, result)
                messages.append({"role": "tool", "content": result, "tool_name": name})
            if all(n in DIRECT_REPLY_TOOLS for n, _ in results):
                reply = "\n".join(r for _, r in results)
                break

        self.history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self):
        self.history.clear()


agent = Agent()
