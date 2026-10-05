# Source folder and file map

Generated environments, caches, test outputs, browser profiles, and local data are excluded. Each maintained source folder has a nearby `README.md` with execution and connection details.

## Repository root

- `README.md` — install, run, test, architecture summary, and project layout.
- `run.py` — starts the FastAPI backend using `backend/.venv`.
- `package.json` — root shortcuts for Next.js development, production start, and build.
- `pyproject.toml` — placeholder project metadata; Python dependencies currently live in `backend/requirements.txt`.
- `.gitignore` — excludes virtual environments, runtime data, generated test output, and local environment files.
- `.github/` — contributor instructions.
- `docs/` — system architecture and folder map.
- `backend/` — Python API, agent, tools, persistence, and tests.
- `frontend/` — Next.js UI and server-side backend proxy.
- `temp/` — local review helper; not part of production execution.

## Backend

### `backend/app/`

- `main.py` — FastAPI application creation, lifecycle, CORS, voice startup/shutdown, task cancellation, and browser cleanup.
- `tasks.py` — bounded task queue, cancellation, timeout, SQLite task lifecycle, and status calculation.
- `voice.py` — local wake-word, VAD, Whisper transcription, agent call, and TTS orchestration.
- `agent/` — model tool calling, request/context support, prompts, private routing, and conversation state.
- `api/` — HTTP route handlers and API secret validation.
- `core/` — environment settings and logging setup.
- `llm/` — OpenAI-compatible provider clients, fallback, and result normalization.
- `memory/` — SQLite conversation, runtime state, task episode, fact, and tool history storage.
- `permissions/` — deterministic tool allow/confirmation/block policy.
- `recovery/` — bounded retry support for tools declared retry-safe.
- `tools/` — tool registry and browser, desktop, filesystem, memory, search, vision, and messaging operations.

### `backend/tests/`

- `test_agent_behavior.py`, `test_agent_pipeline.py`, `test_agent_request.py`, `test_conversation_context.py` — request, tool loop, context, and result behavior.
- `test_api_auth.py`, `test_privacy_routing.py` — fail-closed API auth and deterministic privacy policy.
- `test_task_engine.py` — queue, cancellation, status, persistence, retries, and UI contract.
- `test_llm_provider.py`, `test_llm_tool_architecture.py` — provider fallback and model/tool interface.
- `test_browser_architecture.py`, `test_browser_targets.py` — browser adapters and target behavior.
- `test_tools.py`, `test_vision.py`, `test_web_search.py` — tool and evidence behavior.
- `__init__.py` — marks the test package.

Run from the repository root with `\.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q`.

## Frontend

### `frontend/app/`

- `page.tsx` — dashboard composition and conversation/avatar state.
- `layout.tsx` — document shell, fonts, metadata.
- `globals.css` — application-wide visual tokens and styles.
- `api/backend/[...path]/route.ts` — allow-listed same-origin proxy; adds the server-only backend secret.
- `fonts/` — bundled Geist font files loaded by `layout.tsx`.

### `frontend/components/`

- `ChatPanel/ChatPanel.tsx` — submits background requests, polls task state, cancels work, and displays progress.
- `ActivityFeed.tsx` — polls recent tool activity.
- `SystemStatus.tsx` — polls backend and voice status.
- `JarvisAvatar/` — Three.js avatar, facial morph targets, HUD rings, and UI state hooks.

### `frontend/lib/`

- `api.ts` — typed chat, task, reset, status, and voice clients; requests use the same-origin proxy.
- `activity.ts` — activity API client.

### `frontend/public/`

- `models/vitruvian_head.glb` — avatar model loaded by the `JarvisAvatar` component.

Start the UI from `frontend` with `npm run dev`; build it with `npm run build`.

## Other maintained folders

- `.github/` — `copilot-instructions.md` defines contributor rules; these instructions do not execute at runtime.
- `temp/` — `review_matrix.py` is a one-off helper for inspecting request-parser examples; do not use it as runtime routing.
- `docs/` — `architecture.md` explains call flow, policy boundaries, and status terms; `folder-map.md` is this file.

## Excluded local/generated folders

- `backend/.venv/`, `frontend/node_modules/`, and `frontend/.next/` — installed dependencies and build output.
- `.pytest-tmp*/`, `.pytest_cache/`, and `__pycache__/` — test/interpreter output.
- `data/` — SQLite state, logs, screenshots, and local assistant data.
- `backend/.env` and `frontend/.env.local` are ignored local configuration. The tracked `.env.example` files are templates with blank credential values.
