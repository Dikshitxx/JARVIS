from app.agent.prompts import build_system_prompt
from app.core import config
from app.llm import client


class Agent:
    def __init__(self):
        self.history: list[dict] = []

    def respond(self, user_text: str) -> str:
        self.history.append({"role": "user", "content": user_text})
        self.history = self.history[-config.MAX_HISTORY_MESSAGES:]

        messages = [{"role": "system", "content": build_system_prompt()}] + self.history
        reply = client.chat(messages)

        self.history.append({"role": "assistant", "content": reply})
        return reply

    def reset(self):
        self.history.clear()


agent = Agent()  # single session for now
