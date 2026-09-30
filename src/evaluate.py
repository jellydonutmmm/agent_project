"""Claude evaluation step: decides whether a search result is worth surfacing."""

from __future__ import annotations

import logging

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
