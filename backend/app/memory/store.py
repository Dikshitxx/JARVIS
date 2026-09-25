import sqlite3
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
    return conn


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
