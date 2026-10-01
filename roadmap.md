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
- [x] Handle API errors/timeouts without crashing the caller — also skips malformed results (missing/empty `url` or `title`) and malformed responses with a logged warning, so one bad result can't abort `search()`
- [x] Write tests mocking `tavily-python` responses, including a failure case

## 4. `dedup.py` — duplicate detection

- [x] Implement URL-based exact match check against SQLite history
- [x] Implement title similarity threshold matching
- [x] Choose and document the similarity threshold value and rationale
- [x] Document known false-negative cases (e.g. same story, differently worded headline)
- [x] Write tests covering: exact duplicate, near-duplicate title, genuinely new item, edge cases near the threshold

## 5. `evaluate.py` — Claude relevance evaluation

- [x] Design the evaluation prompt for video game industry relevance — `SYSTEM_PROMPT` in `evaluate.py`; leans "not relevant" when unsure
- [x] Implement structured output parsing: `relevant: bool`, `reason: str` (never free text) — `EVALUATION_SCHEMA` (for constraining the response) plus `parse_evaluation()`, which raises `MalformedEvaluationError` on invalid output
- [x] Implement the Claude Sonnet call via `anthropic` SDK — `evaluate()` calls `claude-sonnet-5-5` (effort `low`) with `EVALUATION_SCHEMA` and parses the reply; API errors and malformed output still propagate until the next item adds the boundary handling
- [x] Handle malformed/unexpected LLM output gracefully (retry or safe default + log) — `evaluate()` now never raises: one retry on malformed output/refusal/`max_tokens`, then a safe default `Evaluation(relevant=False, failed=True)`; API errors are caught and logged at the boundary. The `failed` flag lets `agent.py` (Step 7) tell a failed evaluation from a real "not relevant" so failed items aren't marked evaluated
- [x] Write tests mocking the Anthropic client: valid structured output, malformed output, API failure — written alongside items 2–4 in `tests/test_evaluate.py`

## 6. `notify.py` — Slack webhook notifier

- [x] Implement Slack webhook POST function — `post_to_slack()` in `notify.py`; returns True/False and never raises. Logs the exception type and status code only (no `exc_info`), because `requests` exceptions embed the secret webhook URL
- [x] Add LLM-generated summary text formatting for the notification message — `build_message()` in `notify.py` = `summarize_item()` (Sonnet, one or two plain sentences; falls back to the evaluation `reason` if the call fails) + `format_message()` (Slack mrkdwn: bold title, summary, source link; escapes `&`, `<`, `>`)
- [x] Implement retry with backoff on transient failures — `post_to_slack()` makes up to 3 attempts on timeouts, connection errors, 429 and 5xx (1s, 2s backoff; honors Slack's `Retry-After` on a 429, capped at 30s); other 4xx and invalid-URL errors are not retried
- [x] Document any Slack rate limits encountered — published limit (~1 message/second per webhook, 429 + `Retry-After`) documented in the `notify.py` module docstring; no real limit observed yet, so add any actual 429s there after the Section 10 manual run
- [x] Write tests mocking `requests` calls: success, transient failure + retry, permanent failure — written alongside items 1–3 in `tests/test_notify.py`

## 7. `agent.py` — orchestration

- [x] Add event-stream logging via Python's `logging` module: emit a log line at each pipeline stage (found, evaluated, decision, notified) as items move through, in addition to the row-state audit trail in `store.py` — `process_item()` in `agent.py` logs `found:`, `evaluated:`, `decision:`, `notified:` (plus `skipped duplicate:` and failure warnings)
- [x] Chain search → dedup → evaluate → notify → log as the only place these tools are combined — `run()` / `process_item()` in `agent.py`; items are inserted on find, a failed evaluation leaves the row unevaluated, a failed Slack post leaves `notified_at` unset; tests in `tests/test_agent.py`
- [x] Space out Slack posts within a run (at least ~1 second apart, per Slack's webhook limit documented in `notify.py`) so several notifications in one run don't trigger 429s — `_wait_for_post_slot()` in `agent.py` sleeps up to `MIN_POST_INTERVAL_SECONDS` before each post after the first
- [x] Ensure a single item's failure (bad search result, malformed content) is caught/logged without halting the run — `run()` wraps each `process_item()` call, logging the traceback and moving on to the next item
- [x] Add run-level logging/summary (items found, evaluated, notified, errored) — `run()` returns a `RunSummary` (also searched and duplicates; `errored` = failed evaluations + failed Slack posts + unexpected exceptions) and logs it as one `run summary:` line
- [x] Write an end-to-end test with all external calls mocked, asserting the full run completes despite one failing item — `tests/test_agent_e2e.py` fakes only the Tavily, Anthropic and Slack (`requests.post`) boundaries; covers a failed search query, a failing evaluation, and the resulting row state and summary

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

- [ ] Create and add the three credentials to `.env`; confirm `.env` is gitignored
  - [ ] Tavily API key (free tier, no card) → `TAVILY_API_KEY`
  - [ ] Anthropic API key → `ANTHROPIC_API_KEY`
  - [ ] Slack setup, then the webhook URL → `SLACK_WEBHOOK_URL`:
    - [ ] Create a free Slack workspace and a channel for the agent's posts (e.g. `#game-news`)
    - [ ] Create a Slack app for that workspace and turn on Incoming Webhooks
    - [ ] Add a webhook to the channel and copy its URL
    - [ ] Set the channel's notification preference to "all new messages" on desktop and phone
- [ ] Run the full pipeline end-to-end locally against real APIs at least once
- [ ] Manually verify a real Slack notification renders correctly (not just logged correctly)
- [ ] Confirm a simulated failure (e.g. bad search result) doesn't halt the run

## 11. Documentation cleanup

- [ ] Fill in README "Known limitations" section with actual findings (dedup false negatives, evaluation edge cases, etc.)
- [ ] Add a demo screenshot or sample decision log to README
- [ ] Fill in README run cadence placeholder to match what was implemented
