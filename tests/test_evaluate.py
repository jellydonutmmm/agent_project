from types import SimpleNamespace
from unittest.mock import MagicMock

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


def test_evaluate_sends_expected_request_and_parses_reply() -> None:
    item = SearchResult(
        url="https://example.com/a",
        title="Studio A cuts 10% of staff",
        source="example.com",
        content="Studio A announced layoffs affecting 50 employees.",
    )
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="text", text='{"relevant": true, "reason": "Layoffs at Studio A."}'
            )
        ]
    )

    result = evaluate.evaluate(item, client=client)

    assert result == evaluate.Evaluation(True, "Layoffs at Studio A.")
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["system"] == evaluate.SYSTEM_PROMPT
    assert kwargs["output_config"]["format"]["schema"] is evaluate.EVALUATION_SCHEMA
    assert item.title in kwargs["messages"][0]["content"]
    assert item.content in kwargs["messages"][0]["content"]
