# agent

## Purpose

Agent orchestration and conversational state. Model tool calling selects operations; fixed code enforces privacy and permissions.

## Files

- `__init__.py` - Package marker.
- `agent.py` - Prompt assembly, semantic disambiguation for ambiguous conversation/research requests, completion-gated tool loop, tool result handling, and confirmation state.
- `guardrails.py` - Argument checks only; it does not parse English phrases to decide user intent.
- `model_swap.py` - Coordinates local text and vision Ollama model loading.
- `privacy.py` - Deterministic local-only policy for explicit sensitive markers and structured secrets; no model call.
- `prompts.py` - System instructions and selected context included in model calls.
- `request.py` - Structured request parser used to refine turn classification; its parsed actions do not choose or execute runtime tools.
- `router.py` - High-confidence registered direct routes; broad current-information research stays on the model tool-selection path.
- `runtime_context.py` - Short-term device/browser/task context and recent action tracking.
- `utterance.py` - English turn-state hints for conversation, follow-up, cancellation, and confirmation; not the tool selector.

## Execution and connections

Loaded by API routes and TaskManager. Tool execution calls the registered tool functions in app/tools.

Agent -> LLM provider interface -> proposed tool call -> registry/permission policy -> ToolResult -> grounded response/task status.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
