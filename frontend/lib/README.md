# lib

## Purpose

Typed browser-side API wrappers.

## Files

- `activity.ts` - Recent activity fetch wrapper.
- `api.ts` - Chat/task/voice/status/reset wrappers and task/result types.

## Execution and connections

Imported by ChatPanel, ActivityFeed, and SystemStatus.

All requests target /api/backend so the server-side proxy can attach backend authentication.

See the [architecture guide](../../docs/architecture.md) for the end-to-end flow and [folder map](../../docs/folder-map.md) for repository-wide navigation.
