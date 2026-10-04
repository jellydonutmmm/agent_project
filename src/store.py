"""SQLite persistence layer for tracked items."""

from __future__ import annotations

import functools
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def _log_db_errors(func: Callable[P, R]) -> Callable[P, R]:
    """Log sqlite3 errors with context before re-raising.

    Callers (dedup, agent.py) rely on specific exceptions as real signals —
    e.g. `insert_item` raising `IntegrityError` on a duplicate url — so
    errors are logged here for the audit trail, then always re-raised
    rather than swallowed.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except sqlite3.Error:
            logger.exception("SQLite error in %s", func.__name__)
            raise

    return wrapper


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source TEXT,
    found_at TEXT NOT NULL,
    evaluated INTEGER NOT NULL DEFAULT 0,
    relevant INTEGER,
    reason TEXT,
    notified_at TEXT,
    content TEXT NOT NULL DEFAULT '',
    eval_attempts INTEGER NOT NULL DEFAULT 0
)
"""

# Columns added after the first release. Databases created before them (e.g. the
# saved history on the `state` branch) get them added by init_db.
MIGRATIONS = {
    "content": "ALTER TABLE items ADD COLUMN content TEXT NOT NULL DEFAULT ''",
    "eval_attempts": (
        "ALTER TABLE items ADD COLUMN eval_attempts INTEGER NOT NULL DEFAULT 0"
    ),
}


@dataclass
class Item:
    id: int
    url: str
    title: str
    source: str | None
    found_at: str
    evaluated: bool
    relevant: bool | None
    reason: str | None
    notified_at: str | None
    # Kept so an item whose evaluation failed can be retried on a later run.
    content: str = ""
    eval_attempts: int = 0


@_log_db_errors
def connect(db_path: str = "agent.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


@_log_db_errors
def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    for column, statement in MIGRATIONS.items():
        if column not in existing:
            conn.execute(statement)
    conn.commit()


def _row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        url=row["url"],
        title=row["title"],
        source=row["source"],
        found_at=row["found_at"],
        evaluated=bool(row["evaluated"]),
        relevant=None if row["relevant"] is None else bool(row["relevant"]),
        reason=row["reason"],
        notified_at=row["notified_at"],
        content=row["content"],
        eval_attempts=row["eval_attempts"],
    )


@_log_db_errors
def insert_item(
    conn: sqlite3.Connection,
    url: str,
    title: str,
    source: str,
    found_at: str,
    content: str = "",
) -> int:
    """Insert a newly found item. Raises sqlite3.IntegrityError on duplicate url."""
    cursor = conn.execute(
        "INSERT INTO items (url, title, source, found_at, content) "
        "VALUES (?, ?, ?, ?, ?)",
        (url, title, source, found_at, content),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


@_log_db_errors
def get_by_url(conn: sqlite3.Connection, url: str) -> Item | None:
    row = conn.execute("SELECT * FROM items WHERE url = ?", (url,)).fetchone()
    return _row_to_item(row) if row else None


@_log_db_errors
def get_all_titles(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """Return (id, title) for every known item, for similarity-based dedup."""
    rows = conn.execute("SELECT id, title FROM items").fetchall()
    return [(row["id"], row["title"]) for row in rows]


@_log_db_errors
def get_item(conn: sqlite3.Connection, item_id: int) -> Item | None:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_item(row) if row else None


@_log_db_errors
def update_evaluation(
    conn: sqlite3.Connection, item_id: int, relevant: bool, reason: str
) -> None:
    conn.execute(
        "UPDATE items SET evaluated = 1, relevant = ?, reason = ? WHERE id = ?",
        (int(relevant), reason, item_id),
    )
    conn.commit()


@_log_db_errors
def mark_notified(conn: sqlite3.Connection, item_id: int, notified_at: str) -> None:
    conn.execute(
        "UPDATE items SET notified_at = ? WHERE id = ?",
        (notified_at, item_id),
    )
    conn.commit()


@_log_db_errors
def record_failed_evaluation(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute(
        "UPDATE items SET eval_attempts = eval_attempts + 1 WHERE id = ?", (item_id,)
    )
    conn.commit()


@_log_db_errors
def get_unevaluated(conn: sqlite3.Connection, max_attempts: int) -> list[Item]:
    """Items whose evaluation failed and has been tried fewer than `max_attempts` times."""
    rows = conn.execute(
        "SELECT * FROM items WHERE evaluated = 0 AND eval_attempts < ? ORDER BY id",
        (max_attempts,),
    ).fetchall()
    return [_row_to_item(row) for row in rows]
