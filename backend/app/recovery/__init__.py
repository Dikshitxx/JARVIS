"""Bounded, metadata-controlled recovery for safe tool executions."""

import logging

log = logging.getLogger("jarvis.recovery")
MAX_RECOVERY_ATTEMPTS = 1
_RESOURCE_RECOVERERS = {}

_INFRASTRUCTURE_MARKERS = (
    "browser has been closed", "context has been closed", "page has been closed",
    "target page, context or browser has been closed", "target closed", "connection reset",
    "connection refused", "temporarily unavailable", "timed out", "timeout", "not responding",
    "transport is closing", "websocket is closed", "playwright was closed",
)


def register_resource_recoverer(resource: str, recoverer) -> None:
    _RESOURCE_RECOVERERS[resource] = recoverer


def recover_resource(resource: str) -> bool:
    recoverer = _RESOURCE_RECOVERERS.get(resource)
    if recoverer is None:
        log.info("TOOL_RECOVERY_SKIPPED resource=%s reason=no-recoverer", resource or "unmanaged")
        return False
    log.info("TOOL_RECOVERY_STARTED resource=%s", resource)
    try:
        recovered = bool(recoverer())
    except Exception:
        log.exception("TOOL_RECOVERY_FAILED resource=%s", resource)
        return False
    log.info("TOOL_RECOVERY_SUCCEEDED resource=%s recovered=%s", resource, recovered)
    return recovered


def is_infrastructure_failure(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _INFRASTRUCTURE_MARKERS)


def attempt_recovery(tool, args: dict, verify_failed_result: str) -> tuple[str, bool]:
    """Retry one explicitly retry-safe tool once after failed verification."""
    if not getattr(tool, "retry_safe", False):
        return verify_failed_result, False
    result = verify_failed_result
    for attempt in range(1, MAX_RECOVERY_ATTEMPTS + 1):
        log.info("TOOL_RETRY tool=%s attempt=%s", tool.name, attempt)
        try:
            raw_result = tool.func(**(args or {}))
            result = raw_result.message if hasattr(raw_result, "message") else str(raw_result)
        except Exception as exc:
            result = f"Error: tool '{tool.name}' failed during recovery: {exc}"
            continue
        if tool.verify is not None and tool.verify(args or {}, result):
            log.info("TOOL_RECOVERY_SUCCEEDED tool=%s attempt=%s", tool.name, attempt)
            return result, True
        if tool.verify is None:
            return result, True
    log.info("TOOL_RETRY_FAILED tool=%s", tool.name)
    return result, False
