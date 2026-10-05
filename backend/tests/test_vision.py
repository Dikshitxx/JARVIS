import app.tools  # noqa: F401 - importing the package registers its tools.
from app.agent import model_swap
from app.agent.guardrails import validate_call
from app.core import config
from app.llm import client
from app.tools import vision
from app.tools.registry import REGISTRY


def test_look_at_screen_is_registered_as_safe_tool():
    tool = REGISTRY["look_at_screen"]

    assert tool.func is vision.look_at_screen
    assert tool.risk == "safe"
    assert tool.capabilities == frozenset({"windows"})


def test_vision_chat_uses_ollama_image_message_and_configured_model(monkeypatch, tmp_path):
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"test image")
    calls = []

    class Response:
        def __getitem__(self, key):
            if key == "message":
                return {"content": "A settings window is open."}
            raise KeyError(key)

    def fake_chat(**kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr(client._vision_client, "chat", fake_chat)

    answer = client.vision_chat(str(image_path), "What window is visible?")

    assert answer == "A settings window is open."
    assert len(calls) == 1
    assert calls[0]["model"] == config.VISION_MODEL
    assert calls[0]["keep_alive"] == "5m"
    assert calls[0]["messages"] == [{
        "role": "user",
        "content": (
            "Inspect this screenshot and answer using only details you can see. "
            "Start with the foreground window or app and its clearly readable text. "
            "Do not invent other windows, objects, or text; say when a detail is unclear.\n\n"
            "Question: What window is visible?"
        ),
        "images": [str(image_path)],
    }]


def test_screen_tool_swaps_models_around_failed_inference(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "", raising=False)
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"test image")
    events = []

    def fake_generate(**kwargs):
        operation = "unload" if kwargs["keep_alive"] == 0 else "load"
        events.append((operation, kwargs["model"]))

    def fake_vision_chat(**kwargs):
        events.append(("infer", kwargs["model"]))
        raise TimeoutError("synthetic inference timeout")

    monkeypatch.setattr(model_swap._swap_client, "generate", fake_generate)
    monkeypatch.setattr(client._vision_client, "chat", fake_vision_chat)
    monkeypatch.setattr(
        vision,
        "take_screenshot",
        lambda: f"Screenshot saved: {image_path} (640x480)",
    )

    answer = vision.look_at_screen("What is showing on my screen?")

    assert answer.startswith("Error: vision request timed out")
    assert events == [
        ("unload", config.MODEL_NAME),
        ("load", config.VISION_MODEL),
        ("infer", config.VISION_MODEL),
        ("unload", config.VISION_MODEL),
        ("load", config.MODEL_NAME),
    ]


def test_tool_validation_does_not_use_english_phrases_to_gate_visual_intent():
    assert validate_call("look_at_screen", {}, "¿Qué aparece en mi pantalla?") is None


def test_short_non_english_vision_question_is_preserved():
    question = "¿Qué es esto?"

    assert vision.look_at_screen.__name__ == "look_at_screen"
    from app.agent.guardrails import prepare_call

    assert prepare_call("look_at_screen", {"question": question}) == {"question": question}


def test_main_model_load_is_attempted_when_vision_unload_fails(monkeypatch):
    calls = []

    def fake_generate(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] == config.VISION_MODEL and kwargs["keep_alive"] == 0:
            raise RuntimeError("vision model is not installed")

    monkeypatch.setattr(model_swap._swap_client, "generate", fake_generate)

    model_swap.ensure_main_model_reloaded()

    assert [call["model"] for call in calls] == [config.VISION_MODEL, config.MODEL_NAME]
    assert calls[-1]["keep_alive"] == config.OLLAMA_KEEP_ALIVE


def test_visual_screen_request_routes_to_windows_capability():
    from app.agent.request import build_user_request
    from app.agent.utterance import analyze_utterance

    for text in ("What does this screen show?", "What does this error dialog say?", "Is this page broken?"):
        request = build_user_request(text)

        assert analyze_utterance(text).kind in {"action", "mixed"}
        assert "windows" in request.capabilities
