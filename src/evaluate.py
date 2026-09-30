"""Claude evaluation step: decides whether a search result is worth surfacing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

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
