"""Duplicate detection against SQLite history."""

from __future__ import annotations

import logging
import sqlite3
from difflib import SequenceMatcher

from src.store import get_all_titles, get_by_url

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


def is_duplicate_title(
    conn: sqlite3.Connection, title: str, threshold: float = 0.85
) -> bool:
    """Return True if `title` is similar enough to a known item's title.

    Uses difflib's SequenceMatcher ratio (0-1) against every stored title.
    """
    try:
        known_titles = get_all_titles(conn)
    except sqlite3.Error:
        logger.warning(
            "Title dedup check failed for %r; treating as not a duplicate", title
        )
        return False

    return any(
        SequenceMatcher(None, title, known_title).ratio() >= threshold
        for _, known_title in known_titles
    )
