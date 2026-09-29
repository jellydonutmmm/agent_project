import logging
import sqlite3

import pytest

from src import dedup, store


@pytest.fixture
def conn() -> sqlite3.Connection:
    return store.connect(":memory:")


def test_is_duplicate_url_true_for_known_url(conn: sqlite3.Connection) -> None:
    store.insert_item(
        conn,
        url="https://example.com/a",
        title="Studio A layoffs",
        source="tavily",
        found_at="2026-01-01T00:00:00Z",
    )

    assert dedup.is_duplicate_url(conn, "https://example.com/a") is True


def test_is_duplicate_url_false_for_new_url(conn: sqlite3.Connection) -> None:
    assert dedup.is_duplicate_url(conn, "https://example.com/new") is False


def test_is_duplicate_url_degrades_gracefully_on_db_error(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    conn.close()

    with caplog.at_level(logging.WARNING):
        result = dedup.is_duplicate_url(conn, "https://example.com/a")

    assert result is False
    assert "URL dedup check failed" in caplog.text
