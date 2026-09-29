"""Duplicate detection against SQLite history."""

from __future__ import annotations

import logging
import sqlite3
from difflib import SequenceMatcher

from src.store import get_all_titles, get_by_url

logger = logging.getLogger(__name__)

# difflib.SequenceMatcher.ratio() threshold above which two titles are
# treated as the same story. Chosen from manual spot-checks against real
# headline pairs pulled from search.py's queries: outlets covering the same
# story tend to reuse most of the same words/order (ratio 0.85-1.0, e.g.
# "Major Studio Announces Layoffs Affecting 200 Employees" vs "...200 Staff"
# lands around 0.9), while genuinely different stories about the same studio
# or topic (e.g. two separate rounds of layoffs) usually fall below 0.7.
# 0.85 leaves headroom against false positives on distinct-but-related news
# while still catching most reworded duplicates. See CLAUDE.md's dedup notes
# for known false-negative cases where this still misses a duplicate.
TITLE_SIMILARITY_THRESHOLD = 0.85


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
    conn: sqlite3.Connection, title: str, threshold: float = TITLE_SIMILARITY_THRESHOLD
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
