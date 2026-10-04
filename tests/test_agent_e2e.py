"""End-to-end run with only the external services faked.

Everything inside the project (search, dedup, evaluate, notify, store, agent) is
real; Tavily, Anthropic and the Slack webhook are replaced at their client
boundaries.
"""

import json
import logging
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from src import agent, evaluate, notify, search, store

WEBHOOK = "https://hooks.slack.com/services/T000/B000/SECRET"

RESULTS = {
    "good query": [
        {"url": "https://a.com/1", "title": "Studio X lays off 200", "content": "c"},
        {"url": "https://b.com/2", "title": "Review: Game Y is fun", "content": "c"},
        {
            "url": "https://c.com/3",
            "title": "Publisher Z buys Studio W",
            "content": "c",
        },
    ],
    "second query": [
        # Same URL as an earlier result: dropped by search's per-run URL dedup.
        {"url": "https://a.com/1", "title": "Studio X lays off 200", "content": "c"},
    ],
}


def _message(text: str) -> SimpleNamespace:
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block], stop_reason="end_turn")


def _fake_claude_create(**kwargs: Any) -> SimpleNamespace:
    prompt = kwargs["messages"][0]["content"]
    if kwargs["system"] == notify.SUMMARY_PROMPT:
        return _message("A short summary.")
    if "Publisher Z" in prompt:
        raise RuntimeError("Anthropic exploded")  # the one failing item
    relevant = "Review" not in prompt
    return _message(json.dumps({"relevant": relevant, "reason": "because"}))


@pytest.fixture
def conn() -> Iterator[Any]:
    connection = store.connect(":memory:")
    yield connection
    connection.close()


def test_full_run_completes_despite_one_failing_item(
    conn: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    # Tavily: one query succeeds, one fails outright.
    def tavily_search(query: str, **_: Any) -> dict[str, Any]:
        if query not in RESULTS:
            raise ConnectionError("tavily down")
        return {"results": RESULTS[query]}

    tavily = MagicMock()
    tavily.search.side_effect = tavily_search
    monkeypatch.setattr(search, "_client", lambda: tavily)
    monkeypatch.setattr(
        search, "SEARCH_QUERIES", ["good query", "failing query", "second query"]
    )

    claude = MagicMock()
    claude.messages.create.side_effect = _fake_claude_create
    monkeypatch.setattr(evaluate, "_client", lambda: claude)
    monkeypatch.setattr(notify, "_client", lambda: claude)

    post = MagicMock()
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", WEBHOOK)

    monkeypatch.setattr(time, "sleep", MagicMock())
    monkeypatch.setattr(agent, "_last_post_at", None)

    summary = agent.run(conn)

    assert summary == agent.RunSummary(
        searched=3,
        duplicates=0,
        found=3,
        evaluated=2,
        notified=1,
        errored=1,
        evaluation_failures=1,
    )
    # Exactly the relevant item reached Slack, with the LLM summary in it.
    post.assert_called_once()
    assert "Studio X lays off 200" in post.call_args.kwargs["json"]["text"]
    assert "A short summary." in post.call_args.kwargs["json"]["text"]

    # Row state: relevant+notified, not relevant, and failed (left unevaluated).
    relevant = store.get_by_url(conn, "https://a.com/1")
    irrelevant = store.get_by_url(conn, "https://b.com/2")
    failed = store.get_by_url(conn, "https://c.com/3")
    assert relevant and relevant.relevant and relevant.notified_at
    assert irrelevant and irrelevant.evaluated and irrelevant.relevant is False
    assert failed and not failed.evaluated

    assert "Tavily search failed for query 'failing query'" in caplog.text
    assert "run summary:" in caplog.text
