# [...path]

## Purpose

Catch-all Next.js server route for backend API calls.

## Files

- `route.ts` - GET/POST proxy with route allow-list, server-side secret header, no-store responses, and generic backend-unavailable error.

## Execution and connections

Runs for /api/backend/* requests.

Adds server-only JARVIS_API_SECRET and forwards to JARVIS_API_BASE; restricts permitted route roots.

See the [architecture guide](../../../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../../../docs/folder-map.md) for repository-wide navigation.
