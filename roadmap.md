# Roadmap

Build order for the Game Industry Trends Monitor agent, derived from README.md and CLAUDE.md.

## 0. Project setup

- [x] Initialize Python venv and `.gitignore` (exclude `.env`, `venv/`, `__pycache__/`, `*.db`)
- [x] Create `/src` and `/tests` directories
- [x] Install core deps: `requests`, `tavily-python`, `anthropic`, `pytest`, `ruff`, `mypy`
- [x] Run `pip freeze > requirements.txt` and commit
- [x] Add `.env.example` documenting `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`
- [x] Confirm `.gitignore` covers `.env` and any secrets before first commit

## 1. Logging & error-handling foundation

Establish this before any tool module is built, so every module (starting with `store.py`) follows the same shape from the start instead of having it bolted on afterward.

- [x] Add shared `logging_config.py` with a consistent format for all modules; `configure_logging()` is called once, at the application entry point (`agent.py`)
- [x] Persist exception details, not just stderr: have `configure_logging()` attach a `FileHandler` (e.g. `agent.log`) so tracebacks from any module survive past the console; decide whether errored items also get a row/flag in SQLite for the audit trail, or stay log-only — decided log-only (see `logging_config.py` docstring)
- [x] Document the convention in CLAUDE.md: every module gets `logger = logging.getLogger(__name__)`; every external/risky call is wrapped at its boundary, caught, logged via the module's logger (`exc_info=True`), and degrades gracefully (skip/return a safe default) rather than crashing the caller

## 2. `store.py` — SQLite persistence layer

- [x] Define schema: items table (id, url, title, source, found_at, evaluated, relevant, reason, notified_at) — added `id` as a surrogate primary key, `url` UNIQUE-constrained at the DB level
- [x] Implement init/connect helper
- [x] Implement insert/query functions (by URL, by title) used by dedup
- [x] Implement logging function for full audit trail (found → evaluated → decision → notified) — implemented as row-state on `items` (via `get_item`, `update_evaluation`, `mark_notified`), not a separate log; actual event-stream logging is added under Step 7
- [x] Write tests for schema creation and CRUD against a temp/in-memory SQLite DB
- [x] Retrofit per Section 1's convention: module logger, and catch/log SQLite errors (e.g. locked db, unexpected constraint violations) at each function boundary instead of letting them propagate uncaught
- [x] Add/update tests covering the retrofitted error handling

## 3. `search.py` — Tavily search tool

- [x] Define initial query list for video game industry topics (studio hiring/layoffs, engine/platform shifts, funding/acquisitions/closures, publisher/studio news, independent studios)
- [x] Implement a clearly-scoped `search()` function (input: query list, output: normalized result items)
- [x] Keep Tavily-specific logic contained to this file
- [x] Handle API errors/timeouts without crashing the caller
- [x] Write tests mocking `tavily-python` responses, including a failure case

## 4. `dedup.py` — duplicate detection

- [ ] Implement URL-based exact match check against SQLite history
- [ ] Implement title similarity threshold matching
- [ ] Choose and document the similarity threshold value and rationale
- [ ] Document known false-negative cases (e.g. same story, differently worded headline)
- [ ] Write tests covering: exact duplicate, near-duplicate title, genuinely new item, edge cases near the threshold

## 5. `evaluate.py` — Claude relevance evaluation

- [ ] Design the evaluation prompt for video game industry relevance
- [ ] Implement structured output parsing: `relevant: bool`, `reason: str` (never free text)
- [ ] Implement the Claude Sonnet call via `anthropic` SDK
- [ ] Handle malformed/unexpected LLM output gracefully (retry or safe default + log)
- [ ] Write tests mocking the Anthropic client: valid structured output, malformed output, API failure

## 6. `notify.py` — Slack webhook notifier

- [ ] Implement Slack webhook POST function
- [ ] Add LLM-generated summary text formatting for the notification message
- [ ] Implement retry with backoff on transient failures
- [ ] Document any Slack rate limits encountered
- [ ] Write tests mocking `requests` calls: success, transient failure + retry, permanent failure

## 7. `agent.py` — orchestration

- [ ] Add event-stream logging via Python's `logging` module: emit a log line at each pipeline stage (found, evaluated, decision, notified) as items move through, in addition to the row-state audit trail in `store.py`
- [ ] Chain search → dedup → evaluate → notify → log as the only place these tools are combined
- [ ] Ensure a single item's failure (bad search result, malformed content) is caught/logged without halting the run
- [ ] Add run-level logging/summary (items found, evaluated, notified, errored)
- [ ] Write an end-to-end test with all external calls mocked, asserting the full run completes despite one failing item

## 8. Quality gate (run before every commit / before marking any task done)

- [ ] `ruff format .`
- [ ] `ruff check .` — clean, or warnings fixed with a comment explaining any suppression
- [ ] `mypy .` — all new functions have type hints
- [ ] `pytest` — full suite passes

## 9. Scheduling & deployment

- [x] Decide and document run cadence (every 24 hours — ~510 Tavily queries/month vs. the 1,000/month free-tier limit) and the freshness-vs-API-cost tradeoff
- [ ] Set up cron (or equivalent scheduler) to invoke `agent.py`
- [ ] Verify `.env` secrets are available in the scheduled environment (not committed)

## 10. Manual verification ("done" bar per CLAUDE.md)

- [ ] Run the full pipeline end-to-end locally against real APIs at least once
- [ ] Manually verify a real Slack notification renders correctly (not just logged correctly)
- [ ] Confirm a simulated failure (e.g. bad search result) doesn't halt the run

## 11. Documentation cleanup

- [ ] Fill in README "Known limitations" section with actual findings (dedup false negatives, evaluation edge cases, etc.)
- [ ] Add a demo screenshot or sample decision log to README
- [ ] Fill in README run cadence placeholder to match what was implemented
