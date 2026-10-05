# api

## Purpose

Server-side API route namespace.

## Files

- No direct implementation files.

## Child folders

- `backend/` - See [backend/README.md](./backend/README.md).

## Execution and connections

Next.js App Router executes child route handlers for same-origin browser requests.

backend/ contains the allow-listed backend proxy; browser code never attaches the backend secret.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
