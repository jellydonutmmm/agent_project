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

- [x] Design the evaluation prompt for video game industry relevance — `SYSTEM_PROMPT` in `evaluate.py`; leans "not relevant" when unsure; revised after the first real run (2026-10-01) to reject index/category/homepage/profile/pricing pages and old news — the item text now includes today's date so the model can judge age. Re-checked on a fresh search: 13 of the 21 earlier "relevant" items flipped to not relevant (index pages, a 2022 acquisition announcement, profile pages), none flipped the other way, and the new relevant items were real events
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

Enforced automatically on every commit by a pre-commit hook (`.pre-commit-config.yaml`; run `pre-commit install` once per clone, and commit with the venv activated).

- [x] `ruff format --check .` — check-only; run `ruff format .` first to apply fixes
- [x] `ruff check .` — clean, or warnings fixed with a comment explaining any suppression
- [x] `mypy .` — strict mode (`mypy.ini`); all functions have type hints
- [x] `pytest` — full suite passes, with coverage of `src/` at or above 90% (`pytest.ini`; currently 97%)
- [x] Secret scan — `detect-secrets` against `.secrets.baseline`; blocks commits containing API keys or webhook URLs
- [x] `pip-audit -r requirements.txt` — flags known-vulnerable dependencies; needs network, so it's a manual hook (`pre-commit run --hook-stage manual pip-audit`), not run on every commit
- [x] Pre-commit hook runs the checks above (except `pip-audit`) on every commit

## 9. Scheduling & deployment

- [x] Decide and document run cadence (every 24 hours — ~510 Tavily queries/month vs. the 1,000/month free-tier limit) and the freshness-vs-API-cost tradeoff
- [x] Set up the scheduler: a GitHub Actions scheduled workflow (`.github/workflows/daily-run.yml`, daily at 13:00 UTC, plus a manual "Run workflow" button) replaces cron, so the agent doesn't depend on a personal machine being on. Free for public repos. Runners are ephemeral, so `agent.db` is restored from / saved to a dedicated `state` branch each run (a single force-pushed commit, so it never grows; public along with the repo, holds only news URLs/titles and reasons)
- [x] Add the three secrets (`TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL`) as GitHub repository secrets (Settings → Secrets and variables → Actions) — requires the credentials from Section 10
- [x] Trigger the workflow manually once and confirm: the run succeeds, the `state` branch appears with `agent.db`, and a second manual run skips items as duplicates — 2026-10-04: first run saved the `state` branch; the next run on the Node 24 action versions restored it and skipped 67 of 81 results as duplicates (searched 81, found 14, evaluated 14, notified 0, errored 0). Tavily returns somewhat different results each call, so a few new items per run is normal
- [ ] Confirm scheduled runs keep firing (GitHub disables scheduled workflows in repos with no activity for 60 days; re-enable from the Actions tab if that happens)

## 10. Manual verification ("done" bar per CLAUDE.md)

- [x] Create and add the three credentials to `.env`; confirm `.env` is gitignored
  - [x] Tavily API key (free tier, no card) → `TAVILY_API_KEY` — verified with one real call
  - [x] Anthropic API key → `ANTHROPIC_API_KEY` — verified with one real call
  - [x] Slack setup, then the webhook URL → `SLACK_WEBHOOK_URL` — test message posted and checked on screen:
    - [x] Create a free Slack workspace and a channel for the agent's posts (e.g. `#game-news`)
    - [x] Create a Slack app for that workspace and turn on Incoming Webhooks
    - [x] Add a webhook to the channel and copy its URL
    - [x] Set the channel's notification preference to "all new messages" on desktop and phone
- [x] Run the full pipeline end-to-end locally against real APIs at least once — 2026-10-01: searched 78, found 76, evaluated 76, notified 21, errored 0, in 4m48s (about 4s per item, mostly the evaluation call)
- [x] Manually verify a real Slack notification renders correctly (not just logged correctly) — checked on screen after the 2026-10-01 local run (real LLM summaries)
- [x] Confirm a simulated failure (e.g. bad search result) doesn't halt the run — 2026-10-04, real Tavily + Claude, throwaway DB, bogus Slack webhook: (A) two malformed results injected among 6 real ones: both logged and counted as errored, the 6 real items still processed; (B) invalid Anthropic key: all 6 evaluations failed (errored=8 with the 2 bad results), run still finished. Not exercised: a failing Slack post on a real relevant item (covered by the mocked tests). Finding: with a dead key the run still exits success and the day's items are never retried — see the follow-up items below

## 11. Documentation cleanup

- [x] Fill in README "Known limitations" section with actual findings (dedup false negatives, evaluation edge cases, etc.)
- [x] Add a demo screenshot or sample decision log to README — sample decision log from a real GitHub Actions run (2026-10-04); no Slack screenshot
- [x] Fill in README run cadence placeholder to match what was implemented — new "Scheduling" section; also fixed the run command (`python -m src.agent`), clone URL, and the `.env` loading step

## 12. Follow-ups from the failure check

- [x] Retry items whose evaluation failed (implemented 2026-10-04: `items` gains `content` and `eval_attempts`, migrated automatically on existing databases; failed items are retried on later runs, up to 3 attempts, from a snapshot taken at the start of the run so an item isn't retried in the run that failed it). Original problem: today a failed item keeps its row (unevaluated), so later runs skip it as a duplicate and an outage (e.g. an expired API key) permanently drops that day's items
- [x] Make a broken run visible (implemented 2026-10-04: `RunSummary.problem()` flags a run where search returned nothing or every evaluation failed; `agent.py` then posts a Slack alert and `main()` exits 1). Original problem: exit non-zero (so the Actions run shows red) and/or post a Slack alert when every evaluation in a run fails, since a dead key currently looks like a quiet news day
- [ ] Retry items whose Slack post failed (same silent loss as failed evaluations, not covered by the items above)
