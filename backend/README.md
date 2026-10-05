# backend

## Purpose

Python backend and tests. The ignored .venv and .env are local-only.

## Files

- `.env.example` - Blank credential and model settings template. Copy to .env and set API_SECRET/provider credentials locally.
- `requirements.txt` - Python runtime dependencies for FastAPI, provider clients, browser/desktop tools, voice, and persistence.

## Child folders

- `app/` - See [app/README.md](./app/README.md).
- `tests/` - See [tests/README.md](./tests/README.md).

## Execution and connections

run.py starts uvicorn with this folder as the working directory. Direct API start: .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload. From repository root run tests with .\backend\.venv\Scripts\python.exe -m pytest backend/tests -q.

run.py -> app.main -> API routes -> TaskManager -> privacy scope -> Agent -> permissions/tool registry -> ToolResult/task status.

See the [architecture guide](../docs/architecture.md) for the end-to-end flow and [folder map](../docs/folder-map.md) for repository-wide navigation.
