"""Duplicate detection against SQLite history."""

from __future__ import annotations

import logging
import sqlite3

from src.store import get_by_url

logger = logging.getLogger(__name__)


def is_duplicate_url(conn: sqlite3.Connection, url: str) -> bool:
    """Return True if `url` exactly matches an item already in history."""
    try:
        return get_by_url(conn, url) is not None
    except sqlite3.Error:
        # store.py already logs the underlying error; a lookup failure isn't
        # grounds to crash the caller — treat as "not a known duplicate" so
        # the item proceeds rather than being silently dropped.
        logger.warning(
            "URL dedup check failed for %r; treating as not a duplicate", url
        )
        return False
