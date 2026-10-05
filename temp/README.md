# temp

## Purpose

Local review scripts kept outside production packages.

## Files

- `review_matrix.py` - One-off review helper that prints legacy structured-request examples.

## Execution and connections

review_matrix.py requires the backend import path and is not part of application startup or tests.

The script probes the legacy request metadata builder; runtime execution uses model tool calling.

See the [architecture guide](../docs/architecture.md) for the end-to-end flow and [folder map](../docs/folder-map.md) for repository-wide navigation.
