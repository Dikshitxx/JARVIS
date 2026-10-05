# ChatPanel

## Purpose

Chat interface and task progress controls.

## Files

- `ChatPanel.tsx` - Chat UI, background task polling, cancellation, reset, status and reply display.

## Execution and connections

Rendered by frontend/app/page.tsx.

Submits work, polls task state, supports cancellation/reset, and reports replies to avatar state.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
