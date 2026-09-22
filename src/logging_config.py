"""Shared logging setup so every module logs in a consistent format.

Call `configure_logging()` once, at the application entry point (`agent.py`,
or a test's setup). Individual modules should not call this themselves —
they just do `logger = logging.getLogger(__name__)` and log normally, the
same pattern already used in `search.py`.

Exception details are persisted to a log file (not just stderr) so they
survive past the console. Errored items themselves stay log-only rather than
getting a row/flag in SQLite: `items` (store.py) models items that were
found and are moving through evaluation/notification, and an item that
errored before a result was fetched (e.g. a failed search query) was never
found in the first place, so there's nothing to key a row on. The traceback
in the log file is the audit trail for that case.
"""

from __future__ import annotations

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_FILE = "agent.log"


def configure_logging(level: int = logging.INFO, log_file: str = LOG_FILE) -> None:
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file)],
    )
