"""Orchestration: search -> dedup -> evaluate -> notify, logging each stage.

This is the only module that chains the individual tools together. Each item
emits one log line per pipeline stage (found, evaluated, decision, notified) as
it moves through, in addition to the row-state audit trail kept in `store.py`.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from src import store
from src.dedup import is_duplicate_title, is_duplicate_url
from src.evaluate import evaluate
from src.logging_config import configure_logging
from src.notify import build_message, post_to_slack
from src.search import SearchResult, search

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def process_item(conn: sqlite3.Connection, item: SearchResult) -> None:
    """Run one search result through dedup, evaluation and notification."""
    if is_duplicate_url(conn, item.url) or is_duplicate_title(conn, item.title):
        logger.info("skipped duplicate: %s (%s)", item.title, item.url)
        return

    item_id = store.insert_item(conn, item.url, item.title, item.source or "", _now())
    logger.info("found: id=%d %s (%s)", item_id, item.title, item.url)

    evaluation = evaluate(item)
    if evaluation.failed:
        # Leave the row unevaluated so it's distinguishable from a real
        # "not relevant" decision.
        logger.warning("evaluation failed: id=%d %s", item_id, evaluation.reason)
        return
    store.update_evaluation(conn, item_id, evaluation.relevant, evaluation.reason)
    logger.info("evaluated: id=%d", item_id)
    logger.info(
        "decision: id=%d relevant=%s reason=%s",
        item_id,
        evaluation.relevant,
        evaluation.reason,
    )
    if not evaluation.relevant:
        return

    if post_to_slack(build_message(item, evaluation.reason)):
        store.mark_notified(conn, item_id, _now())
        logger.info("notified: id=%d", item_id)
    else:
        logger.warning("notification failed: id=%d", item_id)


def run(conn: sqlite3.Connection) -> None:
    """Run the full pipeline once."""
    results = search()
    logger.info("search returned %d results", len(results))
    for item in results:
        process_item(conn, item)


def main() -> None:
    configure_logging()
    conn = store.connect()
    try:
        run(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
