import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx2 as httpx
import pytest

from src import evaluate
from src.search import SearchResult


def test_parse_valid_relevant() -> None:
    result = evaluate.parse_evaluation(
        '{"relevant": true, "reason": "Studio A laid off 50 staff."}'
    )

    assert result == evaluate.Evaluation(True, "Studio A laid off 50 staff.")


def test_parse_valid_not_relevant_strips_reason() -> None:
    result = evaluate.parse_evaluation('{"relevant": false, "reason": "  A review. "}')

    assert result == evaluate.Evaluation(False, "A review.")


@pytest.mark.parametrize(
    "bad",
    [
        "not json at all",
        "[1, 2]",
        '{"reason": "missing relevant"}',
        '{"relevant": "yes", "reason": "string instead of bool"}',
        '{"relevant": true}',
        '{"relevant": true, "reason": "   "}',
        '{"relevant": true, "reason": 5}',
    ],
)
def test_parse_rejects_malformed(bad: str) -> None:
    with pytest.raises(evaluate.MalformedEvaluationError):
        evaluate.parse_evaluation(bad)


ITEM = SearchResult(
    url="https://example.com/a",
    title="Studio A cuts 10% of staff",
    source="example.com",
    content="Studio A announced layoffs affecting 50 employees.",
)


def test_evaluate_sends_expected_request_and_parses_reply() -> None:
    item = ITEM
    client = MagicMock()
    client.messages.create.return_value = _response(
        '{"relevant": true, "reason": "Layoffs at Studio A."}'
    )

    result = evaluate.evaluate(item, client=client)

    assert result == evaluate.Evaluation(True, "Layoffs at Studio A.")
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["system"] == evaluate.SYSTEM_PROMPT
    assert kwargs["output_config"]["format"]["schema"] is evaluate.EVALUATION_SCHEMA
    assert item.title in kwargs["messages"][0]["content"]
    assert item.content in kwargs["messages"][0]["content"]


def _response(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
    )


def _client_returning(*responses: SimpleNamespace) -> MagicMock:
    client = MagicMock()
    client.messages.create.side_effect = list(responses)
    return client


def test_evaluate_retries_once_on_malformed_output() -> None:
    client = _client_returning(
        _response("garbage"),
        _response('{"relevant": true, "reason": "Acquisition."}'),
    )

    result = evaluate.evaluate(ITEM, client=client)

    assert result == evaluate.Evaluation(True, "Acquisition.")
    assert client.messages.create.call_count == 2


def test_evaluate_persistent_malformed_returns_safe_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _client_returning(_response("garbage"), _response("still garbage"))

    with caplog.at_level(logging.WARNING, logger="src.evaluate"):
        result = evaluate.evaluate(ITEM, client=client)

    assert result.relevant is False
    assert result.failed
    assert result.reason.startswith("evaluation failed")
    assert client.messages.create.call_count == evaluate.MAX_ATTEMPTS
    assert "Malformed evaluation" in caplog.text


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_evaluate_treats_bad_stop_reason_as_malformed(stop_reason: str) -> None:
    valid = '{"relevant": true, "reason": "ignored"}'
    client = _client_returning(
        _response(valid, stop_reason), _response(valid, stop_reason)
    )

    result = evaluate.evaluate(ITEM, client=client)

    assert result.failed
    assert stop_reason in result.reason


def test_evaluate_api_failure_returns_safe_default_without_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )

    with caplog.at_level(logging.ERROR, logger="src.evaluate"):
        result = evaluate.evaluate(ITEM, client=client)

    assert result.relevant is False
    assert result.failed
    assert "APIConnectionError" in result.reason
    assert client.messages.create.call_count == 1
    assert "Anthropic call failed" in caplog.text


def test_evaluate_unexpected_exception_returns_safe_default() -> None:
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")

    result = evaluate.evaluate(ITEM, client=client)

    assert result.failed
    assert result.relevant is False


def test_evaluate_client_setup_failure_returns_safe_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> None:
        raise RuntimeError("no key")

    monkeypatch.setattr(evaluate, "_client", boom)

    assert evaluate.evaluate(ITEM).failed


def test_item_text_includes_todays_date_for_staleness_judgment() -> None:
    item = SearchResult(url="https://a.com/1", title="T", source=None, content="C")

    text = evaluate._format_item(item)

    assert f"Today's date: {datetime.now(UTC).date().isoformat()}" in text
