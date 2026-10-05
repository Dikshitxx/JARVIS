# tests

## Purpose

Backend unit and architecture tests. Device, provider, browser, and network effects are mocked where practical.

## Files

- `__init__.py` - Marks tests as a Python package.
- `test_agent_behavior.py` - Agent tool decisions, result truthfulness, confirmations, and response behavior.
- `test_agent_pipeline.py` - Tool-loop sequencing and response composition.
- `test_agent_request.py` - Legacy request/context metadata and model-driven routing regressions.
- `test_api_auth.py` - API secret fail-closed and configured-secret checks.
- `test_browser_architecture.py` - Browser separation and adapter contracts.
- `test_browser_targets.py` - Site aliases, target parsing, and search operations.
- `test_conversation_context.py` - Context isolation, references, recent actions, and conversation flow.
- `test_llm_provider.py` - Provider normalization, privacy routing, and fallback.
- `test_llm_tool_architecture.py` - Tool schemas, provider response normalization, and tool call execution.
- `test_privacy_routing.py` - Fixed privacy policy and private task context propagation.
- `test_task_engine.py` - Task queue, persistence, cancellation, retries, and status calculation.
- `test_tools.py` - Registry, permissions, and tool contracts.
- `test_vision.py` - Screenshot and vision path behavior.
- `test_web_search.py` - Search and evidence retrieval.

## Execution and connections

Run from repository root: .\backend\.venv\Scripts\python.exe -m pytest backend/tests -q.

Tests exercise API, privacy/permissions, provider adapters, model/tool loop, tools, voice, and task lifecycle.

See the [architecture guide](../../docs/architecture.md) for the end-to-end flow and [folder map](../../docs/folder-map.md) for repository-wide navigation.
