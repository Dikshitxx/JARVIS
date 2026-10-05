# JARVIS implementation and verification log

## Implemented

- Added the `uv run jarvish` backend launch command; uv manages the project environment and uses the existing backend dependencies.
- Natural-language requests go to the configured model with registered tool schemas. The old regex fast router is disabled; the parser remains contextual metadata only.
- Tool execution, privacy routing, confirmation policy, result status, and task status are enforced in Python. A model cannot approve protected actions or mark a failed operation successful.
- Plain-text responses are checked semantically for a missing required tool call. After a tool runs, the final response is checked against tool evidence; if that check fails, JARVIS returns the recorded result instead of trusting an unsupported summary.
- Private requests use a worker-local scope and Ollama only. Deterministic privacy rules cover explicit private requests, common sensitive labels, and structured secrets; they are not a complete classifier for every language or sensitive context.
- The Next.js server proxy forwards allow-listed routes and injects the backend secret without exposing it in the browser bundle.
- Parallel web-search results are deduplicated in configured provider order, and logs record query length instead of raw search text.
- Root and per-folder guides describe the maintained source layout, module responsibilities, execution flow, and task/tool status terms.

## Validation run

- Backend: `backend\\.venv\\Scripts\\python.exe -m pytest backend/tests -q` from the repository root — **192 passed**.
- Frontend: `npm run build` from `frontend` — **passed**; production build includes `/api/backend/[...path]`.
- Provider status at the final check: Groq configured and reachable (`openai/gpt-oss-120b`); Gemini key unset; local Ollama configured but unreachable at `http://localhost:11434`.
- Live language/tool smoke: Groq received a Spanish arithmetic request and selected `calculate`; the proposed call was inspected and not executed.
- Test suite mocks model, network, browser, and device actions. No live desktop/browser action was performed as part of this verification.

## Boundaries

- Language understanding depends on the configured model and its tool-call support; broad language support is intended, not guaranteed for every language or phrasing.
- Privacy detection uses a small deterministic ruleset. Use explicit private mode for content that must stay local.
- No MCP integration is implemented. Tool verification comes from `ToolResult` and optional `Tool.verify` callbacks.
- A successful tool result can still have verification status `unknown`; task status and user wording preserve that distinction.

## Regression follow-up � 2026-10-05

This follow-up supersedes the earlier note that the fast router is disabled.

- Root cause found for provider-dependent deterministic actions: `UserRequest` was built but not used for dispatch, and the legacy fast router always returned no route. Clear system-status, browser, media, search, and typing requests therefore entered model tool selection. Registry-declared direct routes now execute those requests through the existing permission and verification path; unclear requests still use the model.
- Provider logs show inference failures despite Groq model-list health: Groq returned TPM 429 errors for `openai/gpt-oss-120b`; Ollama connection attempts failed; Gemini is unconfigured. `/llm/status` reports Groq reachable because its check lists models, which does not establish that inference is available.
- Browser causes: ChatGPT navigation verification did not accept its supported host redirects; typing targeted only mapped pages and common input elements, and did not verify the actual composer value. Target aliases, matching-page selection, contenteditable/composer selectors, exact field-state verification, duplicate-tab clarification, and send-after-confirmation verification now cover these cases.
- Search queries now drop leading politeness and produce deterministic search requests. Capability replies are built from registry metadata for offline/directly executable tools and avoid listing terminal access.
- The reported historical system-status HTTP 500 was not reproducible from available logs: no associated traceback or 500 record was present. The current typoed requests were sent synchronously through the running frontend proxy and both returned HTTP 200 with `SUCCEEDED`; backend regression tests also assert HTTP 200. The original 500's exact historical source remains unverified.

### Current verification

- Backend: `backend\\.venv\\Scripts\\python.exe -m pytest backend\\tests -q --tb=short` � **208 passed**.
- Frontend production build: `npm run build` � **passed**, including Next.js lint and type validation.
- Frontend lint: `npm --prefix frontend run lint` � **passed**, no warnings or errors.
- Live read-only checks: `/health`, `/status`, `/llm/status` each returned HTTP 200. The two typoed system-status chat requests through `/api/backend/chat` each returned HTTP 200 and `SUCCEEDED`.
- Browser interaction tests use mocked Playwright pages. No live navigation or text entry was performed in the existing browser profile/session.
- Provider health at final check: Gemini unconfigured; Groq configured and model-list check reachable; Ollama configured and unreachable. No credentials were read or changed.
