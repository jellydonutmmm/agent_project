import logging
import sqlite3

import pytest

from src import store


@pytest.fixture
def conn() -> sqlite3.Connection:
    return store.connect(":memory:")


def test_init_creates_schema(conn: sqlite3.Connection) -> None:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'items'"
    ).fetchall()
    assert len(tables) == 1


def test_insert_and_get_by_url(conn: sqlite3.Connection) -> None:
    item_id = store.insert_item(
        conn,
        url="https://example.com/a",
        title="Studio A layoffs",
        source="tavily",
        found_at="2026-01-01T00:00:00Z",
    )
    item = store.get_by_url(conn, "https://example.com/a")

    assert item is not None
    assert item.id == item_id
    assert item.title == "Studio A layoffs"
    assert item.evaluated is False
    assert item.relevant is None
    assert item.notified_at is None


def test_get_by_url_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert store.get_by_url(conn, "https://example.com/missing") is None


def test_duplicate_url_raises_integrity_error(conn: sqlite3.Connection) -> None:
    store.insert_item(
        conn,
        url="https://example.com/a",
        title="First",
        source="tavily",
        found_at="2026-01-01T00:00:00Z",
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.insert_item(
            conn,
            url="https://example.com/a",
            title="Duplicate",
            source="tavily",
            found_at="2026-01-02T00:00:00Z",
        )


def test_get_all_titles(conn: sqlite3.Connection) -> None:
    store.insert_item(
        conn,
        url="https://example.com/a",
        title="Title A",
        source="tavily",
        found_at="2026-01-01T00:00:00Z",
    )
    store.insert_item(
        conn,
        url="https://example.com/b",
        title="Title B",
        source="tavily",
        found_at="2026-01-01T00:00:00Z",
    )

    titles = store.get_all_titles(conn)

    assert {title for _, title in titles} == {"Title A", "Title B"}


def test_update_evaluation(conn: sqlite3.Connection) -> None:
    item_id = store.insert_item(
        conn,
        url="https://example.com/a",
        title="Title A",
        source="tavily",
        found_at="2026-01-01T00:00:00Z",
    )

    store.update_evaluation(
        conn, item_id, relevant=True, reason="Major layoffs at a top-10 studio"
    )

    item = store.get_item(conn, item_id)
    assert item is not None
    assert item.evaluated is True
    assert item.relevant is True
    assert item.reason == "Major layoffs at a top-10 studio"


def test_mark_notified(conn: sqlite3.Connection) -> None:
    item_id = store.insert_item(
        conn,
        url="https://example.com/a",
        title="Title A",
        source="tavily",
        found_at="2026-01-01T00:00:00Z",
    )

    store.mark_notified(conn, item_id, notified_at="2026-01-01T01:00:00Z")

    item = store.get_item(conn, item_id)
    assert item is not None
    assert item.notified_at == "2026-01-01T01:00:00Z"


def test_get_item_missing_returns_none(conn: sqlite3.Connection) -> None:
    assert store.get_item(conn, 999) is None


def test_read_db_error_is_logged_and_reraised(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    conn.close()

    with caplog.at_level(logging.ERROR), pytest.raises(sqlite3.ProgrammingError):
        store.get_by_url(conn, "https://example.com/a")

    assert "SQLite error in get_by_url" in caplog.text


def test_write_db_error_is_logged_and_reraised(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    conn.close()

    with caplog.at_level(logging.ERROR), pytest.raises(sqlite3.ProgrammingError):
        store.insert_item(
            conn,
            url="https://example.com/a",
            title="Title A",
            source="tavily",
            found_at="2026-01-01T00:00:00Z",
        )

    assert "SQLite error in insert_item" in caplog.text
