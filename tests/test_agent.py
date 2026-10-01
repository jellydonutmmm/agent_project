import logging
import sqlite3
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from src import agent, store
from src.evaluate import Evaluation
from src.search import SearchResult


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = store.connect(":memory:")
    yield connection
    connection.close()


def _item(
    url: str = "https://a.com/1", title: str = "Studio shuts down"
) -> SearchResult:
    return SearchResult(url=url, title=title, source="a.com", content="body")


@pytest.fixture(autouse=True)
def sleep_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Never really sleep in tests; reset the post-spacing state."""
    mock = MagicMock()
    monkeypatch.setattr(agent.time, "sleep", mock)
    monkeypatch.setattr(agent, "_last_post_at", None)
    return mock


@pytest.fixture
def mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    m = {
        "evaluate": MagicMock(return_value=Evaluation(True, "big news")),
        "build_message": MagicMock(return_value="msg"),
        "post": MagicMock(return_value=True),
        "search": MagicMock(),
    }
    monkeypatch.setattr(agent, "evaluate", m["evaluate"])
    monkeypatch.setattr(agent, "build_message", m["build_message"])
    monkeypatch.setattr(agent, "post_to_slack", m["post"])
    monkeypatch.setattr(agent, "search", m["search"])
    return m


def test_relevant_item_is_stored_evaluated_and_notified(
    conn: sqlite3.Connection,
    mocks: dict[str, MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="src.agent")
    agent.process_item(conn, _item())

    stored = store.get_by_url(conn, "https://a.com/1")
    assert stored is not None
    assert stored.evaluated and stored.relevant and stored.notified_at
    mocks["post"].assert_called_once_with("msg")
    stages = [r.message.split(":")[0] for r in caplog.records]
    assert stages == ["found", "evaluated", "decision", "notified"]


def test_irrelevant_item_is_not_notified(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["evaluate"].return_value = Evaluation(False, "noise")
    agent.process_item(conn, _item())

    stored = store.get_by_url(conn, "https://a.com/1")
    assert stored is not None
    assert stored.evaluated and stored.relevant is False
    mocks["post"].assert_not_called()


def test_duplicate_is_skipped(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    agent.process_item(conn, _item())
    agent.process_item(conn, _item())  # same url
    agent.process_item(conn, _item(url="https://b.com/2"))  # same title

    assert mocks["evaluate"].call_count == 1


def test_failed_evaluation_leaves_item_unevaluated(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["evaluate"].return_value = Evaluation(False, "boom", failed=True)
    agent.process_item(conn, _item())

    stored = store.get_by_url(conn, "https://a.com/1")
    assert stored is not None
    assert not stored.evaluated
    mocks["post"].assert_not_called()


def test_failed_slack_post_leaves_item_unnotified(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["post"].return_value = False
    agent.process_item(conn, _item())

    stored = store.get_by_url(conn, "https://a.com/1")
    assert stored is not None
    assert stored.evaluated and stored.notified_at is None


def test_run_processes_every_search_result(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["search"].return_value = [
        _item("https://a.com/1", "First story about layoffs"),
        _item("https://b.com/2", "Completely different acquisition news"),
    ]
    agent.run(conn)

    assert mocks["post"].call_count == 2


def test_posts_are_spaced_apart(
    conn: sqlite3.Connection,
    mocks: dict[str, MagicMock],
    sleep_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent.time, "monotonic", MagicMock(return_value=100.0))
    agent.process_item(conn, _item("https://a.com/1", "First story about layoffs"))
    sleep_mock.assert_not_called()  # first post never waits

    agent.process_item(conn, _item("https://b.com/2", "Completely different news"))
    sleep_mock.assert_called_once_with(agent.MIN_POST_INTERVAL_SECONDS)


def test_run_continues_after_an_item_raises(
    conn: sqlite3.Connection,
    mocks: dict[str, MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocks["evaluate"].side_effect = [
        RuntimeError("bad item"),
        Evaluation(True, "big news"),
    ]
    mocks["search"].return_value = [
        _item("https://a.com/1", "First story about layoffs"),
        _item("https://b.com/2", "Completely different acquisition news"),
    ]
    summary = agent.run(conn)

    assert summary.errored == 1 and summary.notified == 1
    assert mocks["post"].call_count == 1
    assert "error processing item 'https://a.com/1'" in caplog.text


def test_run_summary_counts_each_outcome(
    conn: sqlite3.Connection,
    mocks: dict[str, MagicMock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="src.agent")
    store.insert_item(conn, "https://old.com/1", "Already seen story", "x", "t")
    mocks["search"].return_value = [
        _item("https://old.com/1", "Already seen story"),  # duplicate
        _item("https://a.com/1", "Relevant layoffs story"),  # notified
        _item("https://b.com/2", "Unrelated trivia"),  # not relevant
        _item("https://c.com/3", "Evaluation will fail here"),  # errored
    ]
    mocks["evaluate"].side_effect = [
        Evaluation(True, "big"),
        Evaluation(False, "noise"),
        Evaluation(False, "boom", failed=True),
    ]
    summary = agent.run(conn)

    assert summary == agent.RunSummary(
        searched=4, duplicates=1, found=3, evaluated=2, notified=1, errored=1
    )
    assert "run summary: searched=4 duplicates=1 found=3" in caplog.text
