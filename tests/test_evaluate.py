import pytest

from src import evaluate


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
