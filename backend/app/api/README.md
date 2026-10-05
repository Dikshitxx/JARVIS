# api

## Purpose

HTTP endpoints and request authentication.

## Files

- `__init__.py` - Package marker.
- `auth.py` - Checks X-Jarvis-Secret and fails closed when no real secret is configured.
- `routes.py` - Health, LLM, system, activity, voice, chat, task, cancellation, and reset endpoints.

## Execution and connections

Mounted into FastAPI from app.main.

chat -> TaskManager; task routes -> TaskManager; status/activity -> tool, memory, provider, and voice services.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
