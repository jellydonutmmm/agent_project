# CLAUDE.md

## Project overview

An autonomous agent that monitors video game development industry trends (studio hiring/layoffs, engine and platform shifts, funding and closures, industry news), evaluates whether new findings are substantive (not noise or duplicates), and notifies via Slack when something is worth surfacing.

## Tech stack

- Language: Python 3.x
- Key libraries: `requests` (Slack webhook calls), `tavily-python` (search), `anthropic` (LLM evaluation/summarization)
- Storage: SQLite (stdlib `sqlite3`, or `sqlalchemy` if the schema grows)
- Package manager: pip + venv

## Code style

- Formatter: ruff format — run before every commit
- Linter: ruff check — code should lint clean; fix warnings, don't suppress without a comment explaining why
- Type checking: mypy — all new functions should have type hints
- Naming: snake_case for functions/variables; keep tool functions (search, evaluate, notify) clearly separated, not interleaved
- Logging: every module gets `logger = logging.getLogger(__name__)` and logs errors/warnings through it instead of printing; format/handler setup lives only in `logging_config.py`, configured once at the entry point
- Error handling: every external call (Tavily, Anthropic, Slack) is wrapped at its boundary — catch there, log via the module's logger (`exc_info=True`), and degrade gracefully (skip the item/query, return a safe default) rather than letting the exception propagate and crash the caller. Set this shape up as part of writing the module, not bolted on afterward.

## Testing expectations

- Test framework: pytest
- New functionality needs a corresponding test — don't mark a task complete without one
- Prioritize testing: dedup logic, the evaluation step's structured-output parsing, and error handling paths (what happens when search or Slack fails)
- Mock external calls (Tavily, Claude, Slack webhook) in tests — don't hit real APIs in the test suite
- Run the full test suite before considering any change done

## Before finishing any task, run:

```bash
ruff format .
ruff check .
mypy .
pytest
```

mypy runs in strict mode (`mypy.ini`), and `pytest` enforces 90% coverage of `src/` (`pytest.ini`). Periodically, and before deploying, also run `pip-audit -r requirements.txt` (manual hook; needs network). The same checks plus a `detect-secrets` scan run automatically as a pre-commit hook (`.pre-commit-config.yaml`; one-time setup `pre-commit install`; commit with the venv active). If a secret scan flags a false positive, add `# pragma: allowlist secret` on the line rather than editing the baseline by hand.

Fix any failures before reporting the task as complete.

## Project structure

```
/src
  search.py       — web search tool: queries Tavily for defined topics
  dedup.py        — checks new items against SQLite history
  evaluate.py      — Claude evaluation step: structured relevance decision + reason
  notify.py        — Slack webhook notifier
  store.py         — SQLite persistence layer
  logging_config.py — shared logging setup (consistent format across all modules); call `configure_logging()` once at the entry point (`agent.py`), never inside library modules
  agent.py         — orchestrates the full run: search → dedup → evaluate → notify → log
/tests
```

- Keep each tool (search, evaluate, notify) as an independently callable function with clear inputs/outputs — the orchestration logic in `agent.py` should be the only place that chains them together
- Don't put Slack-specific or Tavily-specific logic anywhere outside `notify.py` / `search.py` respectively

## Git conventions

- Commit messages: imperative mood — "Add relevance evaluation step" not "Added"
- Never commit `.env`, API keys, or the Slack webhook URL — confirm `.gitignore` covers this
- Commit incrementally — working states, not one giant commit at the end
- Whenever a new package is installed, run `pip freeze > requirements.txt` and commit the updated file in the same commit as the code that needs it

## Domain-specific notes

- **Search topics:** queries cover video game development industry trends — studio hiring/layoffs, engine and platform shifts (Unreal, Unity, Godot), funding/acquisitions/closures, and major publisher/studio news — the exact query list lives in `search.py` and should be easy to extend
- **Search API:** Tavily (`tavily-python`), free tier — 1,000 queries/month, no card required. Results come back pre-cleaned (no raw HTML parsing needed).
- **Dedup approach:** URL exact match plus title similarity threshold matching against SQLite history, both in `dedup.py`. Title similarity uses stdlib `difflib.SequenceMatcher.ratio()` against every stored title, threshold `0.85` (see `TITLE_SIMILARITY_THRESHOLD` and its rationale comment in `dedup.py`). Known false-negative cases, where a real duplicate slips through as "new":
  - Same event covered by two outlets with largely different headline structure/wording (e.g. "Ubisoft Cuts 200 Jobs" vs "Layoffs Hit Major Publisher as Ubisoft Restructures") — low word/character overlap despite being the same story, since `SequenceMatcher` scores on shared substrings, not semantic meaning.
  - Reordered wording — `SequenceMatcher` is sensitive to sequence, so two headlines using the same words in a different order can score noticeably lower than their semantic similarity would suggest.
  - A developing story where a followup headline updates a detail (e.g. employee count revised from "200" to "250 layoffs") — close enough to be the same story, but the changed substring can push the ratio either side of the threshold depending on where it falls in the string.
  - Short titles are more sensitive to this than long ones: a few differing words make up a proportionally larger share of a short headline's character length, so the ratio drops faster for short titles than for long ones with the same absolute wording difference.
- **Evaluation prompt:** the Claude call in `evaluate.py` should always return structured output (relevant: bool, reason: str) — never free text, since the reason field is what gets logged and used for debugging judgment quality
- **LLM:** Claude (Sonnet) via the `anthropic` Python SDK, used for both the relevance-evaluation step and the Slack summary text
- **Slack webhook:** set up via a Slack app's Incoming Webhooks feature — no OAuth flow needed, just a POST URL. Document any rate limits encountered.
- **Run cadence:** every 24 hours via a GitHub Actions scheduled workflow (`.github/workflows/daily-run.yml`; free for public repos, no personal machine needed). The SQLite history persists between runs on a `state` branch (restored before, saved after each run; public, holds no secrets). Secrets are GitHub repository secrets, never committed. With the current 17-query `SEARCH_QUERIES` list, that's ~510 Tavily queries/month, comfortably under the 1,000/month free-tier limit (a 6-hour cadence would run ~2,040/month and exceed it). Daily freshness is an acceptable tradeoff for industry-trend news, which doesn't need same-hour surfacing.

## What "done" looks like for this project

A feature is done when: it passes lint, type checks, and tests; a full run completes end-to-end without crashing even if one item fails partway through; and the Slack notification has been manually verified to look right, not just logged correctly.
