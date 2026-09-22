import logging
from unittest.mock import MagicMock

import pytest

from src import search


def _response(results: list[dict]) -> dict:
    return {"results": results}


def test_search_normalizes_results() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [
            {
                "url": "https://example.com/a",
                "title": "Studio A layoffs",
                "source": "example.com",
                "content": "Studio A cut 10% of staff.",
            }
        ]
    )

    results = search.search(queries=["studio layoffs"], client=client)

    assert len(results) == 1
    assert results[0] == search.SearchResult(
        url="https://example.com/a",
        title="Studio A layoffs",
        source="example.com",
        content="Studio A cut 10% of staff.",
    )


def test_search_fills_missing_optional_fields() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [{"url": "https://example.com/a", "title": "Studio A layoffs"}]
    )

    results = search.search(queries=["studio layoffs"], client=client)

    assert results[0].source is None
    assert results[0].content == ""


def test_search_dedupes_by_url_across_queries() -> None:
    client = MagicMock()
    client.search.return_value = _response(
        [{"url": "https://example.com/a", "title": "Studio A layoffs"}]
    )

    results = search.search(queries=["studio layoffs", "game studio news"], client=client)

    assert len(results) == 1
    assert client.search.call_count == 2


def test_search_calls_each_query() -> None:
    client = MagicMock()
    client.search.return_value = _response([])

    search.search(queries=["query one", "query two"], client=client, max_results=3)

    client.search.assert_any_call("query one", max_results=3)
    client.search.assert_any_call("query two", max_results=3)


def test_search_skips_failing_query_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = MagicMock()
    client.search.side_effect = [
        RuntimeError("Tavily is down"),
        _response([{"url": "https://example.com/b", "title": "Studio B funding"}]),
    ]

    with caplog.at_level(logging.WARNING):
        results = search.search(queries=["failing query", "ok query"], client=client)

    assert len(results) == 1
    assert results[0].url == "https://example.com/b"
    assert "failing query" in caplog.text


def test_search_returns_empty_list_when_all_queries_fail() -> None:
    client = MagicMock()
    client.search.side_effect = RuntimeError("Tavily is down")

    results = search.search(queries=["a", "b"], client=client)

    assert results == []
