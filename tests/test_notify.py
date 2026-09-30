import logging
from unittest.mock import MagicMock

import pytest
import requests

from src import notify

WEBHOOK = "https://hooks.slack.com/services/T000/B000/SECRET"


def _response(status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} for url: {WEBHOOK}", response=response
        )
    return response


def test_post_to_slack_success(monkeypatch: pytest.MonkeyPatch) -> None:
    post = MagicMock(return_value=_response(200))
    monkeypatch.setattr(notify.requests, "post", post)

    assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is True

    post.assert_called_once_with(
        WEBHOOK, json={"text": "hello"}, timeout=notify.REQUEST_TIMEOUT_SECONDS
    )


def test_post_to_slack_reads_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    post = MagicMock(return_value=_response(200))
    monkeypatch.setattr(notify.requests, "post", post)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", WEBHOOK)

    assert notify.post_to_slack("hello") is True
    assert post.call_args.args[0] == WEBHOOK


def test_post_to_slack_missing_url_returns_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    post = MagicMock()
    monkeypatch.setattr(notify.requests, "post", post)

    with caplog.at_level(logging.ERROR, logger="src.notify"):
        assert notify.post_to_slack("hello") is False

    post.assert_not_called()
    assert "SLACK_WEBHOOK_URL" in caplog.text


def test_post_to_slack_http_error_returns_false_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(notify.requests, "post", MagicMock(return_value=_response(500)))

    with caplog.at_level(logging.ERROR, logger="src.notify"):
        assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is False

    assert "HTTPError" in caplog.text
    assert "500" in caplog.text
    assert "SECRET" not in caplog.text


def test_post_to_slack_connection_error_returns_false_without_leaking_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        notify.requests,
        "post",
        MagicMock(side_effect=requests.ConnectionError(f"failed: {WEBHOOK}")),
    )

    with caplog.at_level(logging.ERROR, logger="src.notify"):
        assert notify.post_to_slack("hello", webhook_url=WEBHOOK) is False

    assert "ConnectionError" in caplog.text
    assert "SECRET" not in caplog.text
