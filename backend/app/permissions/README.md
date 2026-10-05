# permissions

## Purpose

Deterministic tool authorization and confirmation decisions.

## Files

- `__init__.py` - Package marker.
- `classify.py` - Fixed permission rules, sensitive-memory blocking, and confirmation gates for protected actions.

## Child folders


## Execution and connections

Called by app.tools.registry after the model proposes a tool call and before execution.

Tool name/arguments -> classify -> ALLOW, CONFIRM, or BLOCK.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
