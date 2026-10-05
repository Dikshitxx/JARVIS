# components

## Purpose

Reusable visual and interaction components used by app/page.tsx.

## Files

- `ActivityFeed.tsx` - Polls and renders recent tool activity.
- `SystemStatus.tsx` - Displays backend telemetry and voice-listener status.

## Child folders

- `ChatPanel/` - See [ChatPanel/README.md](./ChatPanel/README.md).
- `JarvisAvatar/` - See [JarvisAvatar/README.md](./JarvisAvatar/README.md).

## Execution and connections

Rendered by the Next.js dashboard page.

ChatPanel uses lib/api; ActivityFeed uses lib/activity; SystemStatus uses lib/api; avatar uses three.js and state hooks.

See the [architecture guide](../../docs/architecture.md) for the end-to-end flow and [folder map](../../docs/folder-map.md) for repository-wide navigation.
