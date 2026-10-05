# tools

## Purpose

Registered operations for information, browser, desktop, file, memory, vision, and messaging work.

## Files

- `__init__.py` - Imports tool modules for registration.
- `apps.py` - Launches and inspects allow-listed Windows applications and environment state.
- `basic.py` - Time, weather, calculations, and basic system information.
- `browser.py` - Browser navigation, search, page interaction, and page inspection operations.
- `browser_adapters.py` - Target-specific browser behavior behind generic adapter interfaces.
- `browser_session.py` - Managed Playwright browser lifecycle and session access.
- `browser_targets.py` - Site aliases, URL normalization, and safe target metadata.
- `clipboard.py` - Clipboard reading, writing, and transfer operations.
- `desktop_input.py` - Keyboard and mouse actions scoped to desktop windows.
- `files.py` - Restricted local file and folder operations within allowed data roots.
- `media.py` - Media playback and system media controls.
- `memory_tools.py` - Remember/list/forget fact operations.
- `people_tools.py` - Remember and look up people records.
- `projects.py` - Project discovery and lifecycle tools.
- `registry.py` - Tool metadata, schemas, risk/capability checks, execution, retries, redaction, and task-step recording.
- `screen.py` - Screenshot capture used by vision operations.
- `terminal.py` - Allow-listed local command execution.
- `vision.py` - Screenshot capture and visual question answering.
- `web_search.py` - Web search and page retrieval with evidence results.
- `whatsapp.py` - WhatsApp messaging workflow and policy-aware actions.
- `whatsapp_adapter.py` - WhatsApp browser adapter.

## Execution and connections

Imported by Agent so definitions are registered before schemas are requested.

Tool module -> registry metadata/schema -> model tool call -> permission gate -> function -> ToolResult/task step.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
