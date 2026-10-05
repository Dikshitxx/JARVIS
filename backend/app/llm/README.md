# llm

## Purpose

OpenAI-compatible provider routing and local model client support.

## Files

- `__init__.py` - Package marker.
- `client.py` - Local Ollama chat/vision client and model lock.
- `llm.py` - Provider clients, fallback, private-provider restriction, normalized tool calls, metrics, and provider status.

## Execution and connections

Agent and vision tools use this package.

Non-private calls try Gemini, Groq, then Ollama; private scopes use Ollama only.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
