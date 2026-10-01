import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx2 as httpx
import pytest
import requests

from src import notify
from src.search import SearchResult

WEBHOOK = "https://hooks.slack.com/services/T000/B000/SECRET"


@pytest.fixture(autouse=True)
def sleep_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Never really sleep in tests; lets tests assert on the backoff delays."""
    mock = MagicMock()
    monkeypatch.setattr(time, "sleep", mock)
    return mock


def _response(
    status_code: int = 200, headers: dict[str, str] | None = None
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} for url: {WEBHOOK}", response=response
        )
    return response


def test_post_to_slack_success(monkeypatch: pytest.MonkeyPatch) -> None:
    post = MagicMock(return_value=_response(200))
    monkeypatch.setattr(requests, "post", post)

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is True

    post.assert_called_once_with(
        WEBHOOK, json={"text": "hello"}, timeout=notify.REQUEST_TIMEOUT_SECONDS
    )


def test_post_to_slack_reads_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    post = MagicMock(return_value=_response(200))
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", WEBHOOK)

    assert notify.post_to_slack("hello") is True
    assert post.call_args.args[0] == WEBHOOK


def test_post_to_slack_missing_url_returns_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    post = MagicMock()
    monkeypatch.setattr(requests, "post", post)

    with caplog.at_level(logging.ERROR, logger="src.notify"):
        assert notify.post_to_slack("hello") is False

    post.assert_not_called()
    assert "SLACK_WEBHOOK_URL" in caplog.text


def test_post_to_slack_http_error_returns_false_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(requests, "post", MagicMock(return_value=_response(500)))

    with caplog.at_level(logging.ERROR, logger="src.notify"):
        assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is False

    assert "HTTPError" in caplog.text
    assert "500" in caplog.text
    assert "SECRET" not in caplog.text


def test_post_to_slack_connection_error_returns_false_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        requests,
        "post",
        MagicMock(side_effect=requests.ConnectionError(f"failed: {WEBHOOK}")),
    )

    with caplog.at_level(logging.ERROR, logger="src.notify"):
        assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is False

    assert "ConnectionError" in caplog.text
    assert "SECRET" not in caplog.text


ITEM = SearchResult(
    url="https://example.com/a",
    title="Studio A cuts 10% of staff",
    source="example.com",
    content="Studio A announced layoffs affecting 50 employees.",
)


def _claude_reply(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


def test_summarize_item_returns_model_text_and_sends_item() -> None:
    client = MagicMock()
    client.messages.create.return_value = _claude_reply("  Studio A laid off 50.  ")

    summary = notify.summarize_item(ITEM, "fallback reason", client=client)

    assert summary == "Studio A laid off 50."
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["system"] == notify.SUMMARY_PROMPT
    assert ITEM.title in kwargs["messages"][0]["content"]
    assert ITEM.content in kwargs["messages"][0]["content"]


def test_summarize_item_api_failure_falls_back_to_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )

    with caplog.at_level(logging.ERROR, logger="src.notify"):
        summary = notify.summarize_item(ITEM, "fallback reason", client=client)

    assert summary == "fallback reason"
    assert "Summary generation failed" in caplog.text


@pytest.mark.parametrize(
    "reply",
    [_claude_reply(""), _claude_reply("   "), _claude_reply("text", "refusal")],
)
def test_summarize_item_unusable_reply_falls_back_to_reason(
    reply: SimpleNamespace,
) -> None:
    client = MagicMock()
    client.messages.create.return_value = reply

    assert notify.summarize_item(ITEM, "fallback reason", client=client) == (
        "fallback reason"
    )


def test_summarize_item_client_setup_failure_falls_back_to_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> None:
        raise RuntimeError("no key")

    monkeypatch.setattr(notify, "_client", boom)

    assert notify.summarize_item(ITEM, "fallback reason") == "fallback reason"


def test_format_message_layout() -> None:
    message = notify.format_message(ITEM, "Studio A laid off 50.")

    assert message == (
        "*Studio A cuts 10% of staff*\n"
        "Studio A laid off 50.\n"
        "<https://example.com/a|example.com>"
    )


def test_format_message_escapes_slack_control_characters() -> None:
    item = SearchResult(
        url="https://example.com/a",
        title="<!channel> A & B",
        source=None,
        content="",
    )

    message = notify.format_message(item, "x > y")

    assert "<!channel>" not in message
    assert "&lt;!channel&gt; A &amp; B" in message
    assert "x &gt; y" in message
    assert message.endswith("<https://example.com/a|link>")


def test_build_message_combines_summary_and_format() -> None:
    client = MagicMock()
    client.messages.create.return_value = _claude_reply("Studio A laid off 50.")

    message = notify.build_message(ITEM, "fallback reason", client=client)

    assert message == notify.format_message(ITEM, "Studio A laid off 50.")


def _post_sequence(monkeypatch: pytest.MonkeyPatch, *outcomes: object) -> MagicMock:
    """Mock requests.post to return/raise each outcome in turn."""
    post = MagicMock(side_effect=list(outcomes))
    monkeypatch.setattr(requests, "post", post)
    return post


@pytest.mark.parametrize("status", [500, 502, 503])
def test_post_to_slack_retries_5xx_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, sleep_mock: MagicMock, status: int
) -> None:
    post = _post_sequence(monkeypatch, _response(status), _response(200))

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is True

    assert post.call_count == 2
    sleep_mock.assert_called_once_with(notify.BACKOFF_BASE_SECONDS)


@pytest.mark.parametrize(
    "error", [requests.ConnectionError("down"), requests.Timeout("slow")]
)
def test_post_to_slack_retries_network_errors_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, error: requests.RequestException
) -> None:
    post = _post_sequence(monkeypatch, error, _response(200))

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is True
    assert post.call_count == 2


def test_post_to_slack_backoff_grows_exponentially(
    monkeypatch: pytest.MonkeyPatch, sleep_mock: MagicMock
) -> None:
    post = _post_sequence(monkeypatch, _response(503), _response(503), _response(503))

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is False

    assert post.call_count == notify.MAX_ATTEMPTS == 3
    # No sleep after the final attempt.
    assert [c.args[0] for c in sleep_mock.call_args_list] == [1.0, 2.0]


def test_post_to_slack_exhausted_retries_logs_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _post_sequence(monkeypatch, *[_response(503)] * notify.MAX_ATTEMPTS)

    with caplog.at_level(logging.WARNING, logger="src.notify"):
        assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is False

    assert "failed after 3 attempts" in caplog.text
    assert "SECRET" not in caplog.text


def test_post_to_slack_honors_retry_after_on_429(
    monkeypatch: pytest.MonkeyPatch, sleep_mock: MagicMock
) -> None:
    _post_sequence(monkeypatch, _response(429, {"Retry-After": "7"}), _response(200))

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is True

    sleep_mock.assert_called_once_with(7.0)


def test_post_to_slack_caps_retry_after(
    monkeypatch: pytest.MonkeyPatch, sleep_mock: MagicMock
) -> None:
    _post_sequence(monkeypatch, _response(429, {"Retry-After": "3600"}), _response(200))

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is True

    sleep_mock.assert_called_once_with(notify.MAX_RETRY_AFTER_SECONDS)


def test_post_to_slack_429_without_usable_retry_after_uses_backoff(
    monkeypatch: pytest.MonkeyPatch, sleep_mock: MagicMock
) -> None:
    _post_sequence(
        monkeypatch,
        _response(429),
        _response(429, {"Retry-After": "soon"}),
        _response(200),
    )

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is True

    assert [c.args[0] for c in sleep_mock.call_args_list] == [1.0, 2.0]


@pytest.mark.parametrize("status", [400, 403, 404])
def test_post_to_slack_does_not_retry_permanent_http_errors(
    monkeypatch: pytest.MonkeyPatch, sleep_mock: MagicMock, status: int
) -> None:
    post = _post_sequence(monkeypatch, _response(status))

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is False

    assert post.call_count == 1
    sleep_mock.assert_not_called()


def test_post_to_slack_does_not_retry_invalid_url(
    monkeypatch: pytest.MonkeyPatch, sleep_mock: MagicMock
) -> None:
    post = _post_sequence(monkeypatch, requests.exceptions.InvalidURL("bad"))

    assert notify.post_to_slack("hello", webhook_url="not-a-url") is False

    assert post.call_count == 1
    sleep_mock.assert_not_called()
