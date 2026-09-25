import json
import logging

from app import tools  # noqa: F401  (loads and registers tools)
from app.agent.prompts import build_system_prompt
from app.core import config
from app.llm import client
from app.tools.registry import REGISTRY, NeedsConfirmation, get_schemas, run_tool

log = logging.getLogger("jarvis.agent")

MAX_TOOL_STEPS = 4
DIRECT_REPLY_TOOLS = {"remember_fact", "forget_memory", "list_memories", "open_app", "close_app", "take_screenshot", "remember_person", "list_known_people", "move_mouse", "click_mouse", "type_text", "press_key"}
YES = {"yes", "y", "yeah", "yep", "confirm", "confirmed", "do it", "go ahead"}
NO = {"no", "n", "nope", "cancel", "stop", "dont", "don't"}
REMEMBER_TRIGGERS = {"remember", "save", "note", "don't forget", "dont forget"}


class Agent:
    def __init__(self):
        self.history: list[dict] = []
        self.pending: tuple[str, dict] | None = None  # action waiting for the user's yes/no

    def _remember_turn(self, user_text: str, reply: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        self.history = self.history[-config.MAX_HISTORY_MESSAGES:]

    def _handle_pending(self, user_text: str) -> str | None:
        answer = user_text.strip().lower().strip(" .!")
        name, args = self.pending
        self.pending = None  # any message resolves or drops the pending action
        if answer in YES:
            log.info("CONFIRMED %s %s", name, args)
            return run_tool(name, args, confirmed=True)
        if answer in NO:
            return "Cancelled. Nothing was done."
        return None  # not an answer: the pending action is dropped, continue normally

    def respond(self, user_text: str) -> str:
        bare = user_text.strip().lower().strip(" .!")
        if not self.pending and (bare in YES or bare in NO):
            reply = "There is nothing waiting for your confirmation."
            self._remember_turn(user_text, reply)
            return reply

        if self.pending:
            outcome = self._handle_pending(user_text)
            if outcome is not None:
                self._remember_turn(user_text, outcome)
                return outcome

        self.history.append({"role": "user", "content": user_text})
        allow_remember = any(t in user_text.lower() for t in REMEMBER_TRIGGERS)
        self.history = self.history[-config.MAX_HISTORY_MESSAGES:]

        messages = [{"role": "system", "content": build_system_prompt()}] + self.history
        reply = "I couldn't complete that request."
        finished = False

        for _ in range(MAX_TOOL_STEPS):
            msg = None
            for attempt in range(2):
                try:
                    msg = client.chat(messages, tools=get_schemas())
                    break
                except Exception as e:
                    log.warning("model error (attempt %s): %s", attempt + 1, e)
            if msg is None:
                reply = "Sorry boss, I could not process that. Try rephrasing, or give me one fact at a time."
                break
            log.info("tool_calls=%s content=%r", msg.tool_calls, msg.content)

            calls = []
            if msg.tool_calls:
                calls = [(c.function.name, dict(c.function.arguments or {})) for c in msg.tool_calls]
            else:
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
                if name == "remember_fact" and not allow_remember:
                    result = "Skipped: remember_fact was not called because the user did not ask to remember, save, or note anything."
                    log.info("BLOCKED remember_fact: no trigger word in user message %r", user_text)
                    messages.append({"role": "tool", "content": result, "tool_name": name})
                    results.append((name, result))
                    continue
                try:
                    result = run_tool(name, args)
                except NeedsConfirmation as need:
                    self.pending = (need.tool_name, need.tool_args)
                    reply = f"Confirm: {need.tool_name} {need.tool_args}? Reply 'yes' or 'no'."
                    finished = True
                    break
                log.info("ran %s %s -> %r", name, args, result[:200])
                messages.append({"role": "tool", "content": result, "tool_name": name})
                results.append((name, result))

            if finished:
                break
            if results and all(n in DIRECT_REPLY_TOOLS for n, _ in results):
                reply = "\n".join(r for _, r in results)
                break

        self._remember_turn_reply(reply)
        return reply

    def _remember_turn_reply(self, reply: str) -> None:
        self.history.append({"role": "assistant", "content": reply})

    def reset(self):
        self.history.clear()
        self.pending = None


agent = Agent()
