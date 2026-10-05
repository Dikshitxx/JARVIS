# core

## Purpose

Environment-backed configuration and application logging.

## Files

- `__init__.py` - Package marker.
- `config.py` - Pydantic settings, environment aliases, directories, and allowed local apps/commands.
- `logging_setup.py` - Configures the jarvis logger and rotating file output.

## Execution and connections

Imported during app startup and by feature packages.

Settings -> API/provider/tool configuration; setup_logging -> UTF-8 rotating log file and console.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
