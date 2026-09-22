"""Tavily search tool: queries defined video game industry topics."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from tavily import TavilyClient

logger = logging.getLogger(__name__)

# Initial query list, grouped by the topic categories from README.md.
# Extend by adding queries to the relevant category below.
SEARCH_QUERIES: list[str] = [
    # Studio hiring/layoffs
    "video game studio layoffs",
    "game studio hiring surge",
    "game developer layoffs announcement",
    # Engine and platform shifts
    "Unreal Engine adoption game studios",
    "Unity engine changes game developers",
    "Godot engine game studio adoption",
    "Steam Epic Games Store platform changes",
    "console platform shift game developers",
    # Funding, acquisitions, closures
    "video game studio funding round",
    "game studio acquisition",
    "game studio merger",
    "game studio closure shutdown",
    # Publisher/studio news
    "major game publisher announcement",
    "game studio news industry",
    # Independent studios
    "indie game studio news",
    "independent game developer funding",
    "indie game studio launch",
]


@dataclass
class SearchResult:
    url: str
    title: str
    source: str | None
    content: str


def _client() -> TavilyClient:
    return TavilyClient(api_key=os.environ["TAVILY_API_KEY"])


def search(
    queries: list[str] | None = None,
    client: TavilyClient | None = None,
    max_results: int = 5,
) -> list[SearchResult]:
    """Run each query against Tavily and return normalized, deduped-by-url results."""
    tavily = client or _client()
    seen_urls: set[str] = set()
    results: list[SearchResult] = []

    for query in queries if queries is not None else SEARCH_QUERIES:
        try:
            response = tavily.search(query, max_results=max_results)
        except Exception:
            # Tavily's client raises several unrelated exception types (bad key,
            # rate limit, timeout, ...) with no shared base beyond Exception, and
            # network failures can also surface as lower-level httpx errors. One
            # query failing shouldn't stop the rest from being searched.
            logger.warning("Tavily search failed for query %r", query, exc_info=True)
            continue

        for raw in response["results"]:
            url = raw["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                SearchResult(
                    url=url,
                    title=raw["title"],
                    source=raw.get("source"),
                    content=raw.get("content", ""),
                )
            )

    return results
