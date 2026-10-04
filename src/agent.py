"""Orchestration: search -> dedup -> evaluate -> notify, logging each stage.

This is the only module that chains the individual tools together. Each item
emits one log line per pipeline stage (found, evaluated, decision, notified) as
it moves through, in addition to the row-state audit trail kept in `store.py`.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from src import store
from src.dedup import is_duplicate_title, is_duplicate_url
from src.evaluate import evaluate
from src.logging_config import configure_logging
from src.notify import build_message, format_alert, post_to_slack
from src.search import SearchResult, search

logger = logging.getLogger(__name__)

# Slack allows ~1 message/second per webhook (see notify.py); space posts apart
# so several notifications in one run don't trigger 429s.
MIN_POST_INTERVAL_SECONDS = 1.0
_last_post_at: float | None = None

# An item whose evaluation failed (e.g. during an API outage) is retried on later
# runs, up to this many evaluation attempts in total, so a persistently failing
# item can't cost a call on every run forever.
MAX_EVAL_ATTEMPTS = 3


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
    posts and items that raised unexpectedly. `retried` counts items from earlier
    runs whose evaluation failed and was attempted again."""

    searched: int = 0
    duplicates: int = 0
    found: int = 0
    retried: int = 0
    evaluated: int = 0
    notified: int = 0
    errored: int = 0
    evaluation_failures: int = 0

    def problem(self) -> str | None:
        """Describe why this run looks broken as a whole, or None if it doesn't.

        Individual item failures are expected and tolerated; these are the cases
        where the run as a whole accomplished nothing, which otherwise looks like
        a quiet news day.
        """
        if self.searched == 0:
            return (
                "Search returned no results at all. Check TAVILY_API_KEY and "
                "Tavily's status."
            )
        if self.evaluation_failures > 0 and self.evaluated == 0:
            return (
                f"All {self.evaluation_failures} evaluations failed. Check "
                "ANTHROPIC_API_KEY, API credit and Anthropic's status. The items "
                f"are kept and retried on later runs (up to {MAX_EVAL_ATTEMPTS} "
                "attempts each)."
            )
        return None


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

    item_id = store.insert_item(
        conn, item.url, item.title, item.source or "", _now(), item.content
    )
    summary.found += 1
    logger.info("found: id=%d %s (%s)", item_id, item.title, item.url)
    _evaluate_and_notify(conn, item_id, item, summary)


def retry_unevaluated(
    conn: sqlite3.Connection, pending: list[store.Item], summary: RunSummary
) -> None:
    """Evaluate again items whose evaluation failed in an earlier run."""
    for row in pending:
        item = SearchResult(
            url=row.url,
            title=row.title,
            source=row.source or None,
            content=row.content,
        )
        summary.retried += 1
        logger.info(
            "retrying evaluation: id=%d attempt %d/%d %s",
            row.id,
            row.eval_attempts + 1,
            MAX_EVAL_ATTEMPTS,
            row.title,
        )
        try:
            _evaluate_and_notify(conn, row.id, item, summary)
        except Exception:
            summary.errored += 1
            logger.exception("error retrying item %r", row.url)


def _evaluate_and_notify(
    conn: sqlite3.Connection, item_id: int, item: SearchResult, summary: RunSummary
) -> None:
    evaluation = evaluate(item)
    if evaluation.failed:
        # Leave the row unevaluated so it's distinguishable from a real
        # "not relevant" decision, and count the attempt so it gets retried
        # later but not forever.
        store.record_failed_evaluation(conn, item_id)
        summary.errored += 1
        summary.evaluation_failures += 1
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
    # Snapshot before this run adds or fails anything, so an item that fails
    # today isn't also retried (and its attempts used up) in the same run.
    try:
        pending = store.get_unevaluated(conn, MAX_EVAL_ATTEMPTS)
    except sqlite3.Error:
        # store.py has already logged it; carry on with the new items.
        pending = []
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
    retry_unevaluated(conn, pending, summary)
    logger.info(
        "run summary: searched=%d duplicates=%d found=%d retried=%d evaluated=%d "
        "notified=%d errored=%d",
        summary.searched,
        summary.duplicates,
        summary.found,
        summary.retried,
        summary.evaluated,
        summary.notified,
        summary.errored,
    )
    problem = summary.problem()
    if problem:
        logger.error("run problem: %s", problem)
        _wait_for_post_slot()
        post_to_slack(format_alert(problem))
    return summary


def main() -> int:
    """Run once. Returns a non-zero exit code if the run as a whole looks broken,
    so a scheduler (e.g. GitHub Actions) shows it as failed."""
    configure_logging()
    conn = store.connect()
    try:
        summary = run(conn)
    finally:
        conn.close()
    return 1 if summary.problem() else 0


if __name__ == "__main__":
    sys.exit(main())
