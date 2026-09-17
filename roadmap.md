# Roadmap

Build order for the Game Industry Trends Monitor agent, derived from README.md and CLAUDE.md.

## 0. Project setup

- [ ] Initialize Python venv and `.gitignore` (exclude `.env`, `venv/`, `__pycache__/`, `*.db`)
- [ ] Create `/src` and `/tests` directories
- [ ] Install core deps: `requests`, `tavily-python`, `anthropic`, `pytest`, `ruff`, `mypy`
- [ ] Run `pip freeze > requirements.txt` and commit
- [ ] Add `.env.example` documenting `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`
- [ ] Confirm `.gitignore` covers `.env` and any secrets before first commit

## 1. `store.py` — SQLite persistence layer

- [ ] Define schema: items table (url, title, source, found_at, evaluated, relevant, reason, notified_at)
- [ ] Implement init/connect helper
- [ ] Implement insert/query functions (by URL, by title) used by dedup
- [ ] Implement logging function for full audit trail (found → evaluated → decision → notified)
- [ ] Write tests for schema creation and CRUD against a temp/in-memory SQLite DB

## 2. `search.py` — Tavily search tool

- [ ] Define initial query list for video game industry topics (studio hiring/layoffs, engine/platform shifts, funding/acquisitions/closures, publisher/studio news)
- [ ] Implement a clearly-scoped `search()` function (input: query list, output: normalized result items)
- [ ] Keep Tavily-specific logic contained to this file
- [ ] Handle API errors/timeouts without crashing the caller
- [ ] Write tests mocking `tavily-python` responses, including a failure case

## 3. `dedup.py` — duplicate detection

- [ ] Implement URL-based exact match check against SQLite history
- [ ] Implement title similarity threshold matching
- [ ] Choose and document the similarity threshold value and rationale
- [ ] Document known false-negative cases (e.g. same story, differently worded headline)
- [ ] Write tests covering: exact duplicate, near-duplicate title, genuinely new item, edge cases near the threshold

## 4. `evaluate.py` — Claude relevance evaluation

- [ ] Design the evaluation prompt for video game industry relevance
- [ ] Implement structured output parsing: `relevant: bool`, `reason: str` (never free text)
- [ ] Implement the Claude Sonnet call via `anthropic` SDK
- [ ] Handle malformed/unexpected LLM output gracefully (retry or safe default + log)
- [ ] Write tests mocking the Anthropic client: valid structured output, malformed output, API failure

## 5. `notify.py` — Slack webhook notifier

- [ ] Implement Slack webhook POST function
- [ ] Add LLM-generated summary text formatting for the notification message
- [ ] Implement retry with backoff on transient failures
- [ ] Document any Slack rate limits encountered
- [ ] Write tests mocking `requests` calls: success, transient failure + retry, permanent failure

## 6. `agent.py` — orchestration

- [ ] Chain search → dedup → evaluate → notify → log as the only place these tools are combined
- [ ] Ensure a single item's failure (bad search result, malformed content) is caught/logged without halting the run
- [ ] Add run-level logging/summary (items found, evaluated, notified, errored)
- [ ] Write an end-to-end test with all external calls mocked, asserting the full run completes despite one failing item

## 7. Quality gate (run before every commit / before marking any task done)

- [ ] `ruff format .`
- [ ] `ruff check .` — clean, or warnings fixed with a comment explaining any suppression
- [ ] `mypy .` — all new functions have type hints
- [ ] `pytest` — full suite passes

## 8. Scheduling & deployment

- [ ] Decide and document run cadence (e.g. every 6 hours) and the freshness-vs-API-cost tradeoff
- [ ] Set up cron (or equivalent scheduler) to invoke `agent.py`
- [ ] Verify `.env` secrets are available in the scheduled environment (not committed)

## 9. Manual verification ("done" bar per CLAUDE.md)

- [ ] Run the full pipeline end-to-end locally against real APIs at least once
- [ ] Manually verify a real Slack notification renders correctly (not just logged correctly)
- [ ] Confirm a simulated failure (e.g. bad search result) doesn't halt the run

## 10. Documentation cleanup

- [ ] Fill in README "Known limitations" section with actual findings (dedup false negatives, evaluation edge cases, etc.)
- [ ] Add a demo screenshot or sample decision log to README
- [ ] Fill in README run cadence placeholder to match what was implemented
