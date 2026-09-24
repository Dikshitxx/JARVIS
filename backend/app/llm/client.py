import ollama
from app.core import config

_client = ollama.Client(host=config.OLLAMA_HOST)


def chat(messages: list, tools: list | None = None):
    """Returns the assistant message object (has .content and .tool_calls)."""
    response = _client.chat(
        model=config.MODEL_NAME,
        messages=messages,
        tools=tools,
        options={"num_ctx": config.NUM_CTX},
        keep_alive="2m",
    )
    return response["message"]
