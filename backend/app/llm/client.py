import ollama
from app.core import config

_client = ollama.Client(host=config.OLLAMA_HOST)


def chat(messages: list[dict]) -> str:
    response = _client.chat(
        model=config.MODEL_NAME,
        messages=messages,
        options={"num_ctx": config.NUM_CTX},
        keep_alive="2m",  # unload the model 2 min after last use to free RAM
    )
    return response["message"]["content"]
