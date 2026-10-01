"""Orchestration: search -> dedup -> evaluate -> notify, logging each stage.

This is the only module that chains the individual tools together. Each item
emits one log line per pipeline stage (found, evaluated, decision, notified) as
it moves through, in addition to the row-state audit trail kept in `store.py`.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from src import store
from src.dedup import is_duplicate_title, is_duplicate_url
from src.evaluate import evaluate
from src.logging_config import configure_logging
from src.notify import build_message, post_to_slack
from src.search import SearchResult, search

logger = logging.getLogger(__name__)

# Slack allows ~1 message/second per webhook (see notify.py); space posts apart
# so several notifications in one run don't trigger 429s.
MIN_POST_INTERVAL_SECONDS = 1.0
_last_post_at: float | None = None


def _wait_for_post_slot() -> None:
    """Sleep as needed so posts are at least MIN_POST_INTERVAL_SECONDS apart."""
    global _last_post_at
    if _last_post_at is not None:
        remaining = MIN_POST_INTERVAL_SECONDS - (time.monotonic() - _last_post_at)
        if remaining > 0:
            time.sleep(remaining)
    _last_post_at = time.monotonic()


@dataclass
class RunSummary:
    """Counts for one run. `errored` covers failed evaluations, failed Slack
    posts and items that raised unexpectedly."""

    searched: int = 0
    duplicates: int = 0
    found: int = 0
    evaluated: int = 0
    notified: int = 0
    errored: int = 0


def _now() -> str:
    return datetime.now(UTC).isoformat()


def process_item(
    conn: sqlite3.Connection, item: SearchResult, summary: RunSummary | None = None
) -> None:
    """Run one search result through dedup, evaluation and notification.

    Outcomes are tallied into `summary` if given.
    """
    summary = summary or RunSummary()
    if is_duplicate_url(conn, item.url) or is_duplicate_title(conn, item.title):
        summary.duplicates += 1
        logger.info("skipped duplicate: %s (%s)", item.title, item.url)
        return

    item_id = store.insert_item(conn, item.url, item.title, item.source or "", _now())
    summary.found += 1
    logger.info("found: id=%d %s (%s)", item_id, item.title, item.url)

    evaluation = evaluate(item)
    if evaluation.failed:
        # Leave the row unevaluated so it's distinguishable from a real
        # "not relevant" decision.
        summary.errored += 1
        logger.warning("evaluation failed: id=%d %s", item_id, evaluation.reason)
        return
    store.update_evaluation(conn, item_id, evaluation.relevant, evaluation.reason)
    summary.evaluated += 1
    logger.info("evaluated: id=%d", item_id)
    logger.info(
        "decision: id=%d relevant=%s reason=%s",
        item_id,
        evaluation.relevant,
        evaluation.reason,
    )
    if not evaluation.relevant:
        return

    message = build_message(item, evaluation.reason)
    _wait_for_post_slot()
    if post_to_slack(message):
        store.mark_notified(conn, item_id, _now())
        summary.notified += 1
        logger.info("notified: id=%d", item_id)
    else:
        summary.errored += 1
        logger.warning("notification failed: id=%d", item_id)


def run(conn: sqlite3.Connection) -> RunSummary:
    """Run the full pipeline once and return (and log) a summary of it."""
    summary = RunSummary()
    results = search()
    summary.searched = len(results)
    logger.info("search returned %d results", len(results))
    for item in results:
        try:
            process_item(conn, item, summary)
        except Exception:
            # The tools handle their own external-call failures; this catches
            # anything left (e.g. a SQLite error, a malformed result) so one bad
            # item can't halt the rest of the run.
            summary.errored += 1
            logger.exception("error processing item %r", item.url)
    logger.info(
        "run summary: searched=%d duplicates=%d found=%d evaluated=%d "
        "notified=%d errored=%d",
        summary.searched,
        summary.duplicates,
        summary.found,
        summary.evaluated,
        summary.notified,
        summary.errored,
    )
    return summary


def main() -> None:
    configure_logging()
    conn = store.connect()
    try:
        run(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
