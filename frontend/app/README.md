# app

## Purpose

Next.js App Router entry points, layout, global styles, and API proxy routes.

## Files

- `favicon.ico` - Browser tab icon.
- `globals.css` - Global colors, layout foundations, and component styling.
- `layout.tsx` - HTML shell, local fonts, metadata, and shared body styles.
- `page.tsx` - Dashboard page and top-level avatar/chat/status/activity composition.

## Child folders

- `api/` - See [api/README.md](./api/README.md).
- `fonts/` - See [fonts/README.md](./fonts/README.md).

## Execution and connections

Next.js loads page.tsx and layout.tsx; route handlers execute on the server.

Page renders components; catch-all proxy forwards only allow-listed API paths to FastAPI.

See the [architecture guide](../../docs/architecture.md) for the end-to-end flow and [folder map](../../docs/folder-map.md) for repository-wide navigation.
