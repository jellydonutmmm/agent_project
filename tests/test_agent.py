import logging
import sqlite3
import time
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
    monkeypatch.setattr(time, "sleep", mock)
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
    monkeypatch.setattr(time, "monotonic", MagicMock(return_value=100.0))
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
    old_id = store.insert_item(
        conn, "https://old.com/1", "Already seen story", "x", "t"
    )
    store.update_evaluation(conn, old_id, False, "old")
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
        searched=4,
        duplicates=1,
        found=3,
        evaluated=2,
        notified=1,
        errored=1,
        evaluation_failures=1,
    )
    assert "run summary: searched=4 duplicates=1 found=3" in caplog.text


def test_failed_evaluation_is_retried_on_the_next_run_from_stored_content(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["search"].return_value = [_item()]
    mocks["evaluate"].return_value = Evaluation(False, "boom", failed=True)
    first = agent.run(conn)

    mocks["search"].return_value = []  # nothing new; only the stored item remains
    mocks["evaluate"].return_value = Evaluation(True, "big news")
    second = agent.run(conn)

    assert first.retried == 0  # not retried in the run that failed it
    assert mocks["evaluate"].call_count == 2
    retried_item = mocks["evaluate"].call_args.args[0]
    assert retried_item.content == "body"  # stored content was kept
    assert second.retried == 1 and second.evaluated == 1 and second.notified == 1
    stored = store.get_by_url(conn, "https://a.com/1")
    assert stored is not None and stored.evaluated and stored.notified_at


def test_retries_stop_after_max_attempts(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["search"].return_value = [_item()]
    mocks["evaluate"].return_value = Evaluation(False, "boom", failed=True)
    agent.run(conn)  # attempt 1
    mocks["search"].return_value = []
    for _ in range(agent.MAX_EVAL_ATTEMPTS + 2):
        agent.run(conn)

    assert mocks["evaluate"].call_count == agent.MAX_EVAL_ATTEMPTS


def test_alert_is_posted_when_every_evaluation_fails(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["search"].return_value = [
        _item("https://a.com/1", "First story about layoffs"),
        _item("https://b.com/2", "Completely different acquisition news"),
    ]
    mocks["evaluate"].return_value = Evaluation(False, "boom", failed=True)

    summary = agent.run(conn)

    assert summary.problem() is not None
    mocks["post"].assert_called_once()
    alert = mocks["post"].call_args.args[0]
    assert "needs attention" in alert and "All 2 evaluations failed" in alert


def test_alert_is_posted_when_search_returns_nothing(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["search"].return_value = []

    summary = agent.run(conn)

    assert summary.problem() is not None
    assert "Search returned no results" in mocks["post"].call_args.args[0]


def test_no_alert_when_some_evaluations_succeed(
    conn: sqlite3.Connection, mocks: dict[str, MagicMock]
) -> None:
    mocks["search"].return_value = [
        _item("https://a.com/1", "First story about layoffs"),
        _item("https://b.com/2", "Completely different acquisition news"),
    ]
    mocks["evaluate"].side_effect = [
        Evaluation(False, "noise"),
        Evaluation(False, "boom", failed=True),
    ]

    summary = agent.run(conn)

    assert summary.problem() is None
    mocks["post"].assert_not_called()


@pytest.mark.parametrize(("broken", "expected_code"), [(True, 1), (False, 0)])
def test_main_exit_code_reflects_run_health(
    monkeypatch: pytest.MonkeyPatch,
    mocks: dict[str, MagicMock],
    broken: bool,
    expected_code: int,
) -> None:
    monkeypatch.setattr(agent, "configure_logging", MagicMock())
    real_connect = store.connect
    monkeypatch.setattr(store, "connect", lambda: real_connect(":memory:"))
    mocks["search"].return_value = [] if broken else [_item()]
    mocks["evaluate"].return_value = Evaluation(False, "noise")

    assert agent.main() == expected_code
