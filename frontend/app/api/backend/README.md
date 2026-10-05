# backend

## Purpose

Backend proxy route namespace.

## Files

- No direct implementation files.

## Child folders

- `[...path]/` - See [[...path]/README.md](./[...path]/README.md).

## Execution and connections

Handled by the nested catch-all route.ts.

Forwards chat, task, activity, health, status, voice, and LLM status requests to configured FastAPI base URL.

See the [architecture guide](../../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../../docs/folder-map.md) for repository-wide navigation.
