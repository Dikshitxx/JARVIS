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
