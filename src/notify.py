"""Slack webhook notifier."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10


def post_to_slack(text: str, webhook_url: str | None = None) -> bool:
    """POST a plain-text message to the Slack incoming webhook.

    Returns True if Slack accepted it, False otherwise. Never raises.
    """
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        logger.error("SLACK_WEBHOOK_URL is not set; cannot send notification")
        return False

    try:
        response = requests.post(
            url, json={"text": text}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # Deliberately no exc_info: the webhook URL is a secret, and requests
        # exceptions embed it in their message, so a traceback would write it to
        # agent.log. Log the exception type and status code only.
        status = exc.response.status_code if exc.response is not None else None
        logger.error(
            "Slack notification failed: %s (status %s)", type(exc).__name__, status
        )
        return False

    return True
