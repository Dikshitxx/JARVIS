# Runtime architecture

This document describes the runtime architecture implemented in the repository today.

## Request lifecycle

1. **Input and API.** The browser sends chat requests to the Next.js server proxy. The proxy forwards approved routes to FastAPI and adds the server-side `JARVIS_API_SECRET`. Voice input enters through `VoiceService` and calls the same agent/task path.
2. **Task context.** `/chat` submits work to `TaskManager`. Its bounded worker pool owns task IDs, cooperative cancellation, timeout flags, and the request's execution context.
3. **Privacy policy.** `privacy.should_keep_local` applies fixed rules before the agent calls a model. Explicit `private=True` and private pending actions also stay local. A private request scope is a `ContextVar`, so privacy travels with the worker while `Agent.respond` keeps a plain-text input boundary.
4. **Semantic planning.** `Agent` sends the user's message and registered tool schemas to the configured model. The model's tool call is the intent/argument plan. The request parser remains contextual metadata; it does not select or execute runtime tools.
5. **Permission and validation.** `run_tool_result` checks the tool name, validates arguments, applies `classify`, and returns a confirmation request for protected actions. The model cannot approve a protected action by itself; the pending call must match and the user must confirm.
6. **Execution and verification.** A registered tool runs and returns `ToolResult`. Its status records the execution outcome; verification records evidence of the effect. Retries are bounded and limited to tools marked safe to retry.
7. **Task completion.** Tool attempts are appended to the task record with sensitive values redacted. Task status is calculated from the latest attempt for each repeated call, failure state, cancellation/timeout state, and verification. The model's natural-language wording does not make a failed tool succeed.
8. **Response and UI.** The agent returns the direct result or a response grounded in tool observations. The UI polls task status and activity through the Next.js proxy.

## Component map

| Component | Responsibility | Main connection |
| --- | --- | --- |
| `backend/app/api/routes.py` | Health, chat, task, activity, status, and voice endpoints | Calls `TaskManager`, `Agent`, memory, and voice service |
| `backend/app/tasks.py` | Queue, persistence, cancellation, timeout, lifecycle | Calls `Agent.respond` in task and privacy contexts |
| `backend/app/agent/agent.py` | Conversation context, tool schemas, model calls, tool loop, result composition | Calls provider interface, permissions, registry, and runtime context |
| `backend/app/agent/request.py` | Structured intent and context metadata | Refines turn classification; model tool calls own runtime dispatch |
| `backend/app/agent/utterance.py` | Lightweight English turn-state hints, especially cancellation/confirmation | Used by API/context code; it does not choose the registered tool |
| `backend/app/agent/privacy.py` | Fixed local-only classification | Runs before model selection in background tasks |
| `backend/app/permissions/classify.py` | Allow, confirm, or block for a proposed tool call | Invoked inside the registry before tool execution |
| `backend/app/tools/registry.py` | Tool metadata, schemas, policy gate, retries, task-step recording | Imports tool definitions and calls individual tool functions |
| `backend/app/llm/llm.py` | Provider order, fallback, private-provider restriction, response normalization | Called by the agent and vision tools |
| `backend/app/memory/store.py` | SQLite persistence | Stores conversations, actions, tasks, and memory records |
| `frontend/app/api/backend/[...path]/route.ts` | Same-origin allow-listed HTTP proxy | Keeps the backend secret on the Next.js server |
| `frontend/components/ChatPanel/ChatPanel.tsx` | Chat input, task polling, cancellation, progress display | Uses `frontend/lib/api.ts` |

## Model selection versus policy

The model decides what the user means and which available tool best fits the request. The model does not decide privacy, authorization, confirmation, whether a tool actually succeeded, or whether a result is verified. Those decisions stay in Python code and tool results.

The old `router.py` exports no-op compatibility helpers. They never run a tool. `Agent` exposes all non-blocked tool schemas for ordinary turns so its configured model can choose from their descriptions and JSON schemas. A plain-text response is semantically checked when there is no tool call; if the check is invalid or indicates an unverified action claim, the agent fails closed. After a tool runs, a proposed summary is also checked against the recorded tool observations. If that check is unavailable or flags an unsupported claim, JARVIS returns the actual tool result instead of the model's summary.

This is model-based natural-language routing, not a guarantee that every provider understands every language equally well. Provider tool-call support and model quality set the practical language boundary. A model/provider failure should produce a blocked/unavailable response, not simulated execution.

## Providers and privacy

The provider chain is Gemini, Groq, then local Ollama for non-private calls. Private calls skip cloud providers and use the local provider only. Current defaults are configured in `backend/app/core/config.py` and can be overridden in `backend/.env`:

- Gemini: `gemini-3.8-flash`.
- Groq: `openai/gpt-oss-120b`.
- Ollama: `llama3.2:3b`.

The app can report provider availability at `/llm/status`. A provider model ID being valid does not prove the current key, account, quota, endpoint, or local Ollama service works. Provider status must be checked in the running environment.

The privacy classifier is deterministic and intentionally small. It detects common sensitive labels and structured values; it does not infer arbitrary sensitive meaning in every language. Requests with the explicit private flag always remain local. For environments requiring a stronger guarantee, configure the provider policy to local-only until a reviewed privacy policy is available.

## Tool lifecycle terms

- **Tool schema:** The model-visible name, description, and JSON argument shape for a registered operation.
- **Permission decision:** `ALLOW`, `CONFIRM`, or `BLOCK`, computed after the model proposes a call.
- **Execution status:** `success`, `failure`, `authentication_required`, `confirmation_required`, `clarification_required`, or `invalid_action`.
- **Verification status:** `verified`, `failed`, or `unknown`. A successful command without evidence is not automatically a verified outcome.
- **Task status:** A user-visible lifecycle state such as `QUEUED`, `RUNNING`, `WAITING_CONFIRMATION`, `SUCCEEDED`, `FAILED`, `BLOCKED`, `UNVERIFIED`, `CANCELLED`, or `TIMED_OUT`.
- **Recovery:** One retry after an infrastructure failure only when tool metadata explicitly marks the operation retry-safe.
- **Private request scope:** Worker-local state that prevents the provider chain from reaching cloud models.

## Implemented boundaries and unfinished packages

Verification comes from each tool's result and optional `Tool.verify` callback. `backend/app/recovery/` handles bounded retries for tools marked safe to retry.
