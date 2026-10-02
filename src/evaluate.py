"""Claude evaluation step: decides whether a search result is worth surfacing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anthropic

from src.search import SearchResult

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5-5"
# Room for adaptive thinking plus the short JSON answer.
MAX_TOKENS = 2048
# Attempts per item: one retry on malformed output.
MAX_ATTEMPTS = 2

SYSTEM_PROMPT = """\
You screen news items for a monitor of video game development industry trends.

An item is RELEVANT only if it reports a substantive, concrete development in one of:
- studio hiring surges or layoffs
- game engine or platform shifts (Unreal, Unity, Godot, Steam, Epic Games Store, consoles)
- funding rounds, acquisitions, mergers, or studio closures
- major publisher or studio announcements that change the industry landscape
- independent studio launches, closures, or funding

An item is NOT relevant if it is:
- gameplay coverage: reviews, previews, guides, patch notes, release-date news, esports
- opinion or speculation with no new fact behind it
- an old story re-surfaced, a listicle, or marketing/promotional content
- about the games industry only in passing
- a page that is not a report of one specific event, even when its topic fits: a
  homepage, category/topic/tag index, news feed or aggregator page, company profile
  or directory entry, product/pricing/documentation page, Wikipedia-style overview,
  or evergreen explainer. Such pages describe a topic or a site, not a development.
  Judge the page itself, not what its links or sidebar headlines might lead to.
- old news: the item's own event happened well before today's date (given with the
  item), e.g. an announcement from several years ago. Judge the date of the event,
  not the date the page was last crawled; if no date can be established and the
  item reads as a standing page or old announcement, treat it as old.

Judge from the title and content given. When unsure, lean not relevant: a missed
minor item costs less than a noisy notification.

Give a one or two sentence reason that names the specific development (or why there
is none), so the decision can be audited later."""

# JSON schema for the structured response: exactly these two fields, never free text.
EVALUATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["relevant", "reason"],
    "additionalProperties": False,
}


@dataclass
class Evaluation:
    relevant: bool
    reason: str
    # True when no valid decision was obtained and this is the safe default.
    failed: bool = False


class MalformedEvaluationError(Exception):
    """Model output was not a valid {relevant: bool, reason: str} object."""


def parse_evaluation(text: str) -> Evaluation:
    """Parse model output into an Evaluation; raises MalformedEvaluationError."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MalformedEvaluationError(f"not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MalformedEvaluationError("expected a JSON object")
    relevant = data.get("relevant")
    reason = data.get("reason")
    if not isinstance(relevant, bool):
        raise MalformedEvaluationError("'relevant' missing or not a bool")
    if not isinstance(reason, str) or not reason.strip():
        raise MalformedEvaluationError("'reason' missing or empty")
    return Evaluation(relevant=relevant, reason=reason.strip())


def _client() -> anthropic.Anthropic:
    # Reads ANTHROPIC_API_KEY from the environment.
    return anthropic.Anthropic()


def _format_item(item: SearchResult) -> str:
    return (
        f"Today's date: {datetime.now(UTC).date().isoformat()}\n"
        f"Title: {item.title}\n"
        f"Source: {item.source or 'unknown'}\n"
        f"URL: {item.url}\n"
        f"Content: {item.content}"
    )


def _request_evaluation(claude: anthropic.Anthropic, item: SearchResult) -> Evaluation:
    response = claude.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _format_item(item)}],
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": EVALUATION_SCHEMA},
        },
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise MalformedEvaluationError(f"stop_reason={response.stop_reason}")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return parse_evaluation(text)


def evaluate(
    item: SearchResult, client: anthropic.Anthropic | None = None
) -> Evaluation:
    """Ask Claude whether one search result is relevant. Never raises.

    Malformed output (including refusals and truncation) is retried once. If no
    valid answer is obtained, or the API call fails, returns a not-relevant
    Evaluation with ``failed=True`` so the caller can tell it from a real decision.
    """
    try:
        claude = client or _client()
    except Exception:
        logger.exception("Could not create Anthropic client")
        return Evaluation(False, "evaluation failed: client setup error", failed=True)

    last_error = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _request_evaluation(claude, item)
        except MalformedEvaluationError as exc:
            last_error = str(exc)
            logger.warning(
                "Malformed evaluation for %s (attempt %d/%d): %s",
                item.url,
                attempt,
                MAX_ATTEMPTS,
                last_error,
            )
        except anthropic.APIError as exc:
            # The SDK has already retried transient errors (429, 5xx, connection).
            logger.exception("Anthropic call failed for %s", item.url)
            return Evaluation(
                False, f"evaluation failed: {type(exc).__name__}", failed=True
            )
        except Exception:
            logger.exception("Unexpected error evaluating %s", item.url)
            return Evaluation(False, "evaluation failed: unexpected error", failed=True)

    return Evaluation(False, f"evaluation failed: {last_error}", failed=True)
