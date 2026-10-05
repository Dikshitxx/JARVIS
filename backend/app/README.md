# app

## Purpose

FastAPI runtime package. Subpackages hold agent, API, providers, policy, tools, and persistence.

## Files

- `main.py` - Creates FastAPI app, mounts routes, starts/stops voice, drains tasks, and closes browser state.
- `tasks.py` - Bounded worker queue, cancellation, timeout, task persistence, and result-derived status.
- `voice.py` - Local wake-word/VAD/STT/TTS loop; sends transcribed input through TaskManager.

## Child folders

- `agent/` - See [agent/README.md](./agent/README.md).
- `api/` - See [api/README.md](./api/README.md).
- `core/` - See [core/README.md](./core/README.md).
- `llm/` - See [llm/README.md](./llm/README.md).
- `memory/` - See [memory/README.md](./memory/README.md).
- `permissions/` - See [permissions/README.md](./permissions/README.md).
- `recovery/` - See [recovery/README.md](./recovery/README.md).
- `tools/` - See [tools/README.md](./tools/README.md).

## Execution and connections

Started by run.py or uvicorn app.main:app from backend/.

main.py owns lifespan and app wiring; tasks.py owns background work; voice.py calls TaskManager; feature packages are imported by routes and tool registration.

See the [architecture guide](../../docs/architecture.md) for the end-to-end flow and [folder map](../../docs/folder-map.md) for repository-wide navigation.
