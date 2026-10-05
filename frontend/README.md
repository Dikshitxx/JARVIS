# frontend

## Purpose

Next.js 14 browser interface and server-side API proxy.

## Files

- `.env.example` - Blank template for server-only `JARVIS_API_BASE` and `JARVIS_API_SECRET` proxy settings.
- `.eslintrc.json` - Frontend lint settings.
- `.gitignore` - Frontend generated output exclusions.
- `next-env.d.ts` - Next.js TypeScript declarations.
- `next.config.mjs` - Next.js build/runtime configuration.
- `package-lock.json` - Pinned npm dependency graph.
- `package.json` - Next.js scripts and React/Three.js dependencies.
- `postcss.config.mjs` - PostCSS/Tailwind processing.
- `tailwind.config.ts` - Tailwind content and theme configuration.
- `tsconfig.json` - TypeScript compiler configuration.

## Child folders

- `app/` - See [app/README.md](./app/README.md).
- `components/` - See [components/README.md](./components/README.md).
- `lib/` - See [lib/README.md](./lib/README.md).
- `public/` - See [public/README.md](./public/README.md).

## Execution and connections

Install with npm install; start with npm run dev; build with npm run build.

App Router page -> components -> typed clients in lib -> same-origin API proxy -> FastAPI.

See the [architecture guide](../docs/architecture.md) for the end-to-end flow and [folder map](../docs/folder-map.md) for repository-wide navigation.
