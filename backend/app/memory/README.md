# memory

## Purpose

SQLite persistence for runtime context, messages, facts, task history, and tool executions.

## Files

- `store.py` - SQLite schema and persistence helpers for chat, tasks, tools, runtime context, facts, and people.

## Execution and connections

Called by Agent, task manager, and tool registry.

Agent/context -> store; tool registry -> sanitized execution records; API -> recent activity.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
