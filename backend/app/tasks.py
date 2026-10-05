"""Durable task records and a bounded executor for chat and voice requests."""

from __future__ import annotations

from contextvars import ContextVar
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
import json
import logging
import sqlite3
import threading
import time
import uuid

from app.core import config

log = logging.getLogger("jarvis.tasks")

_task_id: ContextVar[str | None] = ContextVar("jarvis_task_id", default=None)
_cancel_event: ContextVar[threading.Event | None] = ContextVar("jarvis_cancel_event", default=None)
TERMINAL_STATES = {"SUCCEEDED", "FAILED", "BLOCKED", "TIMED_OUT", "CANCELLED", "UNVERIFIED", "INTERRUPTED"}
TASK_STATUS_ALIASES = {
    "PENDING": "QUEUED",
    "QUEUED": "QUEUED",
    "RUNNING": "RUNNING",
    "IN_PROGRESS": "RUNNING",
    "WAITING": "WAITING",
    "WAITING_FOR_USER_INPUT": "WAITING_FOR_USER_INPUT",
    "WAITING_USER_INPUT": "WAITING_FOR_USER_INPUT",
    "WAITING_CONFIRMATION": "WAITING_FOR_USER_INPUT",
    "WAITING_FOR_CONFIRMATION": "WAITING_FOR_USER_INPUT",
    "BLOCKED": "BLOCKED",
    "FAILED": "FAILED",
    "SUCCEEDED": "SUCCEEDED",
    "SUCCESS": "SUCCEEDED",
    "TIMED_OUT": "TIMED_OUT",
    "TIMEOUT": "TIMED_OUT",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELLED",
    "INTERRUPTED": "INTERRUPTED",
    "UNVERIFIED": "UNVERIFIED",
    "RESUMABLE": "WAITING",
}
TASK_FIELDS = {
    "status", "resolved_intent", "selected_capabilities", "target", "current_step",
    "result", "error", "cancellation_requested", "timed_out", "resumable",
    "response_provider", "response_model",
}


def normalize_task_status(value: str | None) -> str:
    key = (value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not key:
        return "QUEUED"
    if key in TASK_STATUS_ALIASES:
        return TASK_STATUS_ALIASES[key]
    return key


def current_task_id() -> str | None:
    return _task_id.get()


def cancellation_requested() -> bool:
    event = _cancel_event.get()
    return bool(event and event.is_set())


class task_scope:
    def __init__(self, task_id: str, cancel_event: threading.Event):
        self.task_id = task_id
        self.cancel_event = cancel_event
        self._id_token = None
        self._cancel_token = None

    def __enter__(self):
        self._id_token = _task_id.set(self.task_id)
        self._cancel_token = _cancel_event.set(self.cancel_event)
        return self

    def __exit__(self, *_exc):
        _task_id.reset(self._id_token)
        _cancel_event.reset(self._cancel_token)


def _connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tasks ("
        "id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL, "
        "resolved_intent TEXT NOT NULL DEFAULT '', selected_capabilities TEXT NOT NULL DEFAULT '[]', "
        "target TEXT NOT NULL DEFAULT '', current_step TEXT NOT NULL DEFAULT '', "
        "result TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', "
        "response_provider TEXT NOT NULL DEFAULT '', response_model TEXT NOT NULL DEFAULT '', "
        "cancellation_requested INTEGER NOT NULL DEFAULT 0, timed_out INTEGER NOT NULL DEFAULT 0, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS task_steps ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, "
        "tool_name TEXT NOT NULL, capability TEXT NOT NULL DEFAULT '', arguments TEXT NOT NULL DEFAULT '{}', "
        "status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '', verification TEXT NOT NULL DEFAULT 'unknown', "
        "started_at TEXT NOT NULL, ended_at TEXT NOT NULL, "
        "FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id, id)")
    if "timed_out" not in {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}:
        conn.execute("ALTER TABLE tasks ADD COLUMN timed_out INTEGER NOT NULL DEFAULT 0")
    if "resumable" not in {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}:
        conn.execute("ALTER TABLE tasks ADD COLUMN resumable INTEGER NOT NULL DEFAULT 0")
    if "response_provider" not in {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}:
        conn.execute("ALTER TABLE tasks ADD COLUMN response_provider TEXT NOT NULL DEFAULT ''")
    if "response_model" not in {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}:
        conn.execute("ALTER TABLE tasks ADD COLUMN response_model TEXT NOT NULL DEFAULT ''")
    if "side_effect" not in {row[1] for row in conn.execute("PRAGMA table_info(task_steps)")}:
        conn.execute("ALTER TABLE task_steps ADD COLUMN side_effect INTEGER NOT NULL DEFAULT 0")
    return conn


def _task_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    value = dict(row)
    value["status"] = normalize_task_status(value.get("status"))
    try:
        value["selected_capabilities"] = json.loads(value["selected_capabilities"])
    except (TypeError, json.JSONDecodeError):
        value["selected_capabilities"] = []
    value["cancellation_requested"] = bool(value["cancellation_requested"])
    value["timed_out"] = bool(value.get("timed_out", False))
    value["resumable"] = bool(value.get("resumable", False))
    return value


def create_task(request: str) -> str:
    task_id = uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO tasks (id, request, status, resumable, created_at, updated_at) VALUES (?, ?, 'QUEUED', 1, ?, ?)",
            (task_id, request.strip()[:4000], now, now),
        )
    return task_id


def update_task(task_id: str, **updates) -> dict | None:
    values = {key: value for key, value in updates.items() if key in TASK_FIELDS}
    if not values:
        return get_task(task_id)
    if "status" in values:
        values["status"] = normalize_task_status(values["status"])
    if "selected_capabilities" in values:
        values["selected_capabilities"] = json.dumps(sorted(set(values["selected_capabilities"])))
    if "cancellation_requested" in values:
        values["cancellation_requested"] = int(bool(values["cancellation_requested"]))
    if "resumable" in values:
        values["resumable"] = int(bool(values["resumable"]))
    values["updated_at"] = datetime.now().isoformat(timespec="seconds")
    assignments = ", ".join(f"{key} = ?" for key in values)
    with _connect() as conn:
        conn.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", (*values.values(), task_id))
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _task_dict(row)


def get_task(task_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _task_dict(row)


def list_tasks(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
    return [_task_dict(row) for row in rows]


def append_step(
    task_id: str, *, tool_name: str, capability: str, arguments: dict,
    status: str, result: str, verification: str, started_at: str | None = None,
    side_effect: bool = False,
) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    safe_arguments = {}
    for key, value in (arguments or {}).items():
        if any(token in key.lower() for token in ("password", "secret", "token", "cookie", "authorization")):
            safe_arguments[key] = "[redacted]"
        elif key.lower() in {"message", "text", "content"}:
            safe_arguments[key] = f"[redacted; {len(str(value))} characters]"
        else:
            safe_arguments[key] = str(value)[:300]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO task_steps (task_id, tool_name, capability, arguments, status, result, verification, started_at, ended_at, side_effect) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, tool_name, capability, json.dumps(safe_arguments, ensure_ascii=False), status,
             result[:1000], verification, started_at or now, now, int(side_effect)),
        )


def task_steps(task_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT tool_name, capability, arguments, status, result, verification, started_at, ended_at, side_effect "
            "FROM task_steps WHERE task_id = ? ORDER BY id", (task_id,),
        ).fetchall()
    values = []
    for row in rows:
        item = dict(row)
        try:
            item["arguments"] = json.loads(item["arguments"])
        except (TypeError, json.JSONDecodeError):
            item["arguments"] = {}
        values.append(item)
    return values


class TaskCapacityError(RuntimeError):
    pass


class TaskManager:
    """Runs independent requests concurrently, with a fixed worker and queue bound."""

    def __init__(self, workers: int = 3, queued: int = 6, timeout_seconds: float = 600):
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="jarvis-task")
        self._capacity = workers + queued
        self._timeout_seconds = max(1, timeout_seconds)
        self._lock = threading.RLock()
        self._futures: dict[str, Future] = {}
        self._events: dict[str, threading.Event] = {}

    def submit(self, request: str, private: bool = False) -> str:
        task_id = create_task(request)
        with self._lock:
            active_ids = [key for key, future in self._futures.items() if not future.done()]
            if len(active_ids) >= self._capacity:
                update_task(task_id, status="BLOCKED", error="JARVIS is at its active task limit.", result="Too many requests are already active.")
                raise TaskCapacityError("JARVIS is at its active task limit. Try again when a task finishes.")
            from app.agent import runtime_context

            initial_context = runtime_context.activate_request(task_id)
            cancel_event = threading.Event()
            self._events[task_id] = cancel_event
            future = self._executor.submit(self._run, task_id, request, cancel_event, initial_context, private)
            self._futures[task_id] = future
            future.add_done_callback(lambda _future, key=task_id: self._discard_runtime_state(key))
            completed = [key for key, item in self._futures.items() if item.done()]
            while len(completed) > 100:
                self._futures.pop(completed.pop(0), None)
        return task_id

    def _run(
        self, task_id: str, request: str, cancel_event: threading.Event,
        initial_context: dict, private: bool = False,
    ) -> str:
        from app.agent.agent import agent
        from app.agent import privacy
        from app.agent import runtime_context
        from app.llm import llm
        private = private or agent.has_private_pending()
        if not private:
            private = privacy.should_keep_local(request)

        def mark_timeout():
            cancel_event.set()
            update_task(
                task_id, timed_out=True, cancellation_requested=True,
                current_step="Time limit reached; waiting for the current operation to finish",
                error=f"Task exceeded its {int(self._timeout_seconds)} second time limit.",
                status="TIMED_OUT",
            )

        timer: threading.Timer | None = None
        with (
            task_scope(task_id, cancel_event),
            runtime_context.request_context_scope(task_id, initial_context, commit=not private),
            llm.private_request_scope(private),
        ):
            update_task(task_id, status="RUNNING", current_step="Understanding request", resumable=False)
            timer = threading.Timer(self._timeout_seconds, mark_timeout)
            timer.daemon = True
            timer.start()
            started = time.monotonic()
            try:
                reply = agent.respond(request)
            except Exception as exc:
                log.exception("Task %s failed", task_id)
                update_task(task_id, status="FAILED", error=str(exc)[:1000], result="I couldn't complete that request.")
                return "I couldn't complete that request."
            finally:
                timer.cancel()

            current = get_task(task_id) or {}
            status = normalize_task_status(current.get("status"))
            if status in {"WAITING_FOR_USER_INPUT", "WAITING"}:
                return reply
            if status in {"BLOCKED", "FAILED", "CANCELLED", "TIMED_OUT", "UNVERIFIED", "INTERRUPTED"}:
                if not current.get("result"):
                    update_task(task_id, result=reply)
                return reply
            steps = task_steps(task_id)
            latest_attempts = []
            for step in steps:
                signature = (
                    step["tool_name"],
                    json.dumps(step["arguments"], sort_keys=True, separators=(",", ":"), default=str),
                )
                if latest_attempts and latest_attempts[-1][0] == signature:
                    latest_attempts[-1] = (signature, step)
                else:
                    latest_attempts.append((signature, step))
            steps = [step for _signature, step in latest_attempts]
            failures = [step for step in steps if step["status"] not in {"success", "waiting_confirmation"}]
            blocked = [step for step in failures if step["status"] in {"clarification_required", "authentication_required", "invalid_action"}]
            unverified = [step for step in steps if step["side_effect"] and step["verification"] == "unknown"]
            if current.get("timed_out") or time.monotonic() - started >= self._timeout_seconds:
                status = "TIMED_OUT"
                result = reply or "The time limit was reached while the current operation was finishing."
            elif cancel_event.is_set():
                status = "CANCELLED"
                result = reply or "Stopped after the current operation completed."
            elif failures:
                status = "BLOCKED" if blocked else "FAILED"
                result = reply
            elif unverified:
                status = "UNVERIFIED"
                result = reply
            else:
                status = "SUCCEEDED"
                result = reply
            update_task(task_id, status=status, result=result, current_step="Complete", resumable=status in {"WAITING", "WAITING_FOR_USER_INPUT", "BLOCKED"})
            return reply

    def _discard_runtime_state(self, task_id: str) -> None:
        with self._lock:
            self._events.pop(task_id, None)

    def run_sync(self, request: str, private: bool = False) -> tuple[str, str]:
        task_id = self.submit(request, private=private)
        with self._lock:
            future = self._futures.get(task_id)
        if future is None:
            return task_id, "I couldn't start that request."
        try:
            return task_id, future.result()
        except Exception:
            return task_id, "I couldn't complete that request."

    def cancel(self, task_id: str) -> dict | None:
        with self._lock:
            record = get_task(task_id)
            if record is None:
                return None
            if record["status"] in TERMINAL_STATES:
                return record
            if record["status"] in {"WAITING_CONFIRMATION", "WAITING_FOR_USER_INPUT"}:
                try:
                    from app.agent.agent import agent
                    from app.agent import runtime_context

                    with agent._lock:
                        agent.pending = None
                        agent.pending_task_id = None
                        agent.pending_continuation = None
                    runtime_context.update_context(pending_operation={})
                except Exception:
                    log.exception("Could not clear the pending confirmation for task %s", task_id)
                return update_task(task_id, status="CANCELLED", cancellation_requested=True,
                                   current_step="Cancelled while waiting for confirmation", result="Cancelled.")
            future = self._futures.get(task_id)
            event = self._events.get(task_id)
            if future is not None and future.cancel():
                return update_task(task_id, status="CANCELLED", current_step="Cancelled before execution", cancellation_requested=True)
            if event is not None:
                event.set()
            return update_task(task_id, cancellation_requested=True, current_step="Cancellation requested; finishing the current operation")

    def cancel_all(self) -> None:
        with self._lock:
            task_ids = list(self._futures)
        for task_id in task_ids:
            self.cancel(task_id)

    def cancel_latest(self) -> dict | None:
        """Cancel the newest active request, including one waiting for approval."""
        records = {record["id"]: record for record in list_tasks(100)}
        with self._lock:
            candidates = [
                records.get(key) or get_task(key)
                for key, future in self._futures.items()
                if not future.done()
                and (records.get(key) or get_task(key) or {}).get("status") in {"QUEUED", "PENDING", "RUNNING"}
            ]
        candidates.extend(
            record for record in records.values()
            if record.get("status") in {"WAITING_CONFIRMATION", "WAITING_FOR_USER_INPUT"}
        )
        candidates = [record for record in candidates if record is not None]
        if not candidates:
            return None
        task_id = max(candidates, key=lambda record: record.get("updated_at", ""))["id"]
        return self.cancel(task_id)

    def task(self, task_id: str) -> dict | None:
        record = get_task(task_id)
        if record is not None:
            record["steps"] = task_steps(task_id)
        return record

    def list_recent(self, limit: int = 20) -> list[dict]:
        return [
            {**record, "steps": task_steps(record["id"])}
            for record in list_tasks(limit)
        ]

    def complete_confirmation(
        self, task_id: str | None, status: str, result: str, *, tool_name: str = "",
        arguments: dict | None = None, verification: str = "unknown",
    ) -> None:
        if task_id and get_task(task_id):
            if tool_name:
                from app.tools.registry import REGISTRY, _safe_result

                tool = REGISTRY.get(tool_name)
                append_step(
                    task_id, tool_name=tool_name,
                    capability=",".join(sorted(tool.capabilities)) if tool else "",
                    arguments=arguments or {},
                    status="success" if status in {"SUCCEEDED", "UNVERIFIED"} else "failure",
                    result=_safe_result(tool_name, result),
                    verification=verification, side_effect=bool(tool and tool.side_effect),
                )
            update_task(task_id, status=status, result=result, current_step="Complete" if status in TERMINAL_STATES else "Waiting for confirmation")


task_manager = TaskManager()
