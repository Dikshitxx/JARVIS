# agent

## Purpose

Agent orchestration and conversational state. Model tool calling selects operations; fixed code enforces privacy and permissions.

## Files

- `__init__.py` - Package marker.
- `agent.py` - Task-profile construction, prompt assembly, completion-gated tool loop, tool result handling, and confirmation state.
- `guardrails.py` - Argument checks only; it does not parse English phrases to decide user intent.
- `model_swap.py` - Coordinates local text and vision Ollama model loading.
- `privacy.py` - Deterministic local-only policy for explicit sensitive markers and structured secrets; no model call.
- `prompts.py` - System instructions and selected context included in model calls.
- `request.py` - Structured request parser used to refine turn classification; its parsed actions do not choose or execute runtime tools.
- `router.py` - High-confidence registered direct routes; broad current-information research stays on the model tool-selection path.
- `runtime_context.py` - Short-term device/browser/task context and recent action tracking.
- `task_profile.py` - Provider-independent capability profile built from request, privacy, context, tool, and risk metadata. An optional in-process classifier may refine it; no model asset or preprocessing pipeline is bundled.
- `utterance.py` - English turn-state hints for conversation, follow-up, cancellation, and confirmation; not the tool selector.

## Execution and connections

Loaded by API routes and TaskManager. Tool execution calls the registered tool functions in app/tools.

Agent -> task profile -> capable/ranked LLM provider -> proposed tool call -> registry/permission policy -> ToolResult -> verified response/task status.

The deterministic profile marks explicit private work as local-only, identifies current-information and structured tool requirements, and carries multi-step and verification signals. The provider layer filters by declared capabilities, then ranks candidates using optional normalized `LLM_PROVIDER_QUALITY` and `LLM_PROVIDER_COST` JSON mappings plus observed health and latency. If a provider returns prose instead of required tool work, the agent excludes it for the remainder of that turn and retries another eligible provider; completed tool calls are not replayed.

No ONNX task classifier is currently enabled. A semantic classifier can be injected through the `SemanticProfileClassifier` interface only after its model and preprocessing assets have been validated. Until then, the profile uses existing structured signals and records non-established reasoning complexity as unknown rather than inferring it from prompt length or a keyword list.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
