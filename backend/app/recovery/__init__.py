"""Bounded retry/recovery logic for failed tool executions."""

import logging

log = logging.getLogger("jarvis.recovery")

MAX_RECOVERY_ATTEMPTS = 2


def attempt_recovery(tool, args: dict, verify_failed_result: str) -> tuple[str, bool]:
	"""
	Called when a tool ran but its verify() step failed.
	Tries up to MAX_RECOVERY_ATTEMPTS bounded retries by calling the tool's
	raw function DIRECTLY (never run_tool) — this must never re-enter the
	permission/verification/recovery pipeline, or it recurses without end.
	Returns (final_result, recovered: bool).
	"""
	result = verify_failed_result
	for attempt in range(1, MAX_RECOVERY_ATTEMPTS + 1):
		log.info("RECOVERY attempt %s/%s for %s", attempt, MAX_RECOVERY_ATTEMPTS, tool.name)
		try:
			result = str(tool.func(**(args or {})))
		except Exception as e:
			result = f"Error: tool '{tool.name}' failed during recovery: {e}"
			continue
		if tool.verify is not None and tool.verify(args or {}, result):
			log.info("RECOVERY: %s succeeded on attempt %s", tool.name, attempt)
			return result, True
		if tool.verify is None:
			return result, True
	log.info("RECOVERY: %s failed after %s attempts, giving up", tool.name, MAX_RECOVERY_ATTEMPTS)
	return result, False
