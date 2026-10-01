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
