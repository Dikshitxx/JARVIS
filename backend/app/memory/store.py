import sqlite3
import json
from copy import deepcopy
from datetime import datetime

from app.core import config


def _conn() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS facts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS people ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL, "
        "relationship TEXT, "
        "notes TEXT, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS projects ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name TEXT NOT NULL UNIQUE, "
        "description TEXT, "
        "status TEXT, "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_executions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "tool_name TEXT NOT NULL, "
        "args TEXT, "
        "result TEXT, "
        "confirmed INTEGER NOT NULL DEFAULT 0, "
        "success INTEGER NOT NULL DEFAULT 1, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS runtime_context ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "payload TEXT NOT NULL, "
        "updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS task_episodes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "goal TEXT NOT NULL, "
        "summary TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "role TEXT NOT NULL, "
        "content TEXT NOT NULL, "
        "created_at TEXT NOT NULL)"
    )
    return conn


_RUNTIME_DEFAULTS = {
    "recent_turns": [],
    "previous_intent": "",
    "current_application": "",
    "current_window": "",
    "current_browser": "",
    "browser_target": "",
    "page_url": "",
    "current_target": "",
    "active_service": "",
    "active_pages": [],
    "current_task": "",
    "current_task_id": "",
    "current_task_step": "",
    "task_episode_saved": False,
    "task_actions": [],
    "pending_operation": {},
    "failed_operation": {},
    "last_action": {},
    "last_tool_result": "",
    "active_media": "",
    "current_media": "",
    "media_state": "",
    "recent_entities": [],
    "clipboard_context": "",
    "last_query": "",
    "last_search_query": "",
    "last_site": "",
    "last_text": "",
    "environment_state": {},
    "environment_observed_at": "",
    "active_request_id": "",
}


def get_runtime_context() -> dict:
    with _conn() as conn:
        row = conn.execute("SELECT payload FROM runtime_context WHERE id = 1").fetchone()
    if not row:
        return deepcopy(_RUNTIME_DEFAULTS)
    try:
        saved = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        saved = {}
    return {**deepcopy(_RUNTIME_DEFAULTS), **saved}


def update_runtime_context(**updates) -> dict:
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload FROM runtime_context WHERE id = 1").fetchone()
        try:
            saved = json.loads(row[0]) if row else {}
        except (TypeError, json.JSONDecodeError):
            saved = {}
        current = {**deepcopy(_RUNTIME_DEFAULTS), **saved}
        current.update({key: value for key, value in updates.items() if key in _RUNTIME_DEFAULTS})
        conn.execute(
            "INSERT INTO runtime_context (id, payload, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (json.dumps(current, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )
    return current


def append_runtime_turn(user_text: str, assistant_text: str, intent: str) -> list[dict]:
    """Persist a bounded short-term transcript, separate from long-term facts."""
    context = get_runtime_context()
    turns = list(context.get("recent_turns") or [])
    turns.append({
        "user": user_text.strip()[:1000],
        "assistant": assistant_text.strip()[:1500],
        "intent": intent,
        "at": datetime.now().isoformat(timespec="seconds"),
    })
    return update_runtime_context(recent_turns=turns[-8:])["recent_turns"]


def clear_runtime_context() -> None:
    update_runtime_context(**deepcopy(_RUNTIME_DEFAULTS))


def add_message(role: str, content: str) -> int:
    """Persist one chat message for bounded history on the next agent startup."""
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def recent_messages(limit: int) -> list[dict[str, str]]:
    """Return the newest chat messages in chronological order."""
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (bounded_limit,),
        ).fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]


def clear_messages() -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM messages")


def commit_runtime_context_if_active(task_id: str, context: dict) -> bool:
    """Commit a request-local context only if it is still the latest request."""
    with _conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload FROM runtime_context WHERE id = 1").fetchone()
        try:
            saved = json.loads(row[0]) if row else {}
        except (TypeError, json.JSONDecodeError):
            saved = {}
        if saved.get("active_request_id") != task_id:
            return False
        current = {**deepcopy(_RUNTIME_DEFAULTS), **saved}
        current.update({key: value for key, value in context.items() if key in _RUNTIME_DEFAULTS})
        current["active_request_id"] = task_id
        conn.execute(
            "INSERT INTO runtime_context (id, payload, updated_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (json.dumps(current, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
        )
        return True


def add_task_episode(goal: str, summary: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO task_episodes (goal, summary, created_at) VALUES (?, ?, ?)",
            (goal.strip()[:500], summary.strip()[:1000], datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def list_task_episodes(limit: int = 10) -> list[tuple[int, str, str, str]]:
    with _conn() as conn:
        return conn.execute(
            "SELECT id, goal, summary, created_at FROM task_episodes ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 50)),),
        ).fetchall()


def add_fact(content: str) -> int:
    content = content.strip()
    with _conn() as conn:
        existing = conn.execute(
            "SELECT id FROM facts WHERE lower(content) = lower(?)", (content,)
        ).fetchone()
        if existing:
            return existing[0]
        cur = conn.execute(
            "INSERT INTO facts (content, created_at) VALUES (?, ?)",
            (content, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def list_facts(limit: int | None = None) -> list[tuple[int, str]]:
    query = "SELECT id, content FROM facts ORDER BY id DESC"
    params: tuple = ()
    if limit:
        query += " LIMIT ?"
        params = (limit,)
    with _conn() as conn:
        return conn.execute(query, params).fetchall()


def delete_matching(keyword: str) -> list[str]:
    keyword = keyword.strip()
    if not keyword:
        return []
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, content FROM facts WHERE lower(content) LIKE ?",
            (f"%{keyword.lower()}%",),
        ).fetchall()
        for row_id, _ in rows:
            conn.execute("DELETE FROM facts WHERE id = ?", (row_id,))
        return [content for _, content in rows]


# --- People ---

def add_person(name: str, relationship: str = "", notes: str = "") -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO people (name, relationship, notes, created_at) VALUES (?, ?, ?, ?)",
            (name.strip(), relationship.strip(), notes.strip(), datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def list_people() -> list[tuple]:
    with _conn() as conn:
        return conn.execute("SELECT id, name, relationship, notes FROM people ORDER BY id DESC").fetchall()


def find_person(name: str) -> tuple | None:
    with _conn() as conn:
        return conn.execute(
            "SELECT id, name, relationship, notes FROM people WHERE lower(name) LIKE ?",
            (f"%{name.strip().lower()}%",),
        ).fetchone()


# --- Projects ---

def upsert_project(name: str, description: str = "", status: str = "active") -> int:
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        existing = conn.execute("SELECT id FROM projects WHERE lower(name) = lower(?)", (name.strip(),)).fetchone()
        if existing:
            conn.execute(
                "UPDATE projects SET description = ?, status = ?, updated_at = ? WHERE id = ?",
                (description.strip(), status.strip(), now, existing[0]),
            )
            return existing[0]
        cur = conn.execute(
            "INSERT INTO projects (name, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name.strip(), description.strip(), status.strip(), now, now),
        )
        return cur.lastrowid


def list_projects() -> list[tuple]:
    with _conn() as conn:
        return conn.execute("SELECT id, name, description, status FROM projects ORDER BY updated_at DESC").fetchall()


# --- Tool executions (audit log) ---

def log_tool_execution(tool_name: str, args: dict, result: str, confirmed: bool, success: bool) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO tool_executions (tool_name, args, result, confirmed, success, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tool_name, str(args), result[:500], int(confirmed), int(success), datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def recent_tool_executions(limit: int = 20) -> list[tuple]:
    with _conn() as conn:
        return conn.execute(
            "SELECT tool_name, args, result, confirmed, success, created_at "
            "FROM tool_executions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
