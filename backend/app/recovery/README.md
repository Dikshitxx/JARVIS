# recovery

## Purpose

Bounded retries for declared retry-safe tools after infrastructure failures.

## Files

- `__init__.py` - Resource recoverer registration, infrastructure failure markers, and retry-safe recovery.

## Child folders


## Execution and connections

Imported by the tool registry.

Registry detects failure -> recovery uses resource callback and tool verification -> at most one configured retry.

See the [architecture guide](../../../docs/architecture.md) for the end-to-end flow and [folder map](../../../docs/folder-map.md) for repository-wide navigation.
