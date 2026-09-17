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

## Testing expectations

- Test framework: pytest
- New functionality needs a corresponding test — don't mark a task complete without one
- Prioritize testing: dedup logic, the evaluation step's structured-output parsing, and error handling paths (what happens when search or Slack fails)
- Mock external calls (Tavily, Claude, Slack webhook) in tests — don't hit real APIs in the test suite
- Run the full test suite before considering any change done

## Before finishing any task, run:

```bash
ruff check .
mypy .
pytest
```

Fix any failures before reporting the task as complete.

## Project structure

```
/src
  search.py       — web search tool: queries Tavily for defined topics
  dedup.py        — checks new items against SQLite history
  evaluate.py      — Claude evaluation step: structured relevance decision + reason
  notify.py        — Slack webhook notifier
  store.py         — SQLite persistence layer
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
- **Dedup approach:** title similarity threshold-based matching against SQLite history — document the threshold chosen and known false-negative cases (e.g. same story, very differently worded headline)
- **Evaluation prompt:** the Claude call in `evaluate.py` should always return structured output (relevant: bool, reason: str) — never free text, since the reason field is what gets logged and used for debugging judgment quality
- **LLM:** Claude (Sonnet) via the `anthropic` Python SDK, used for both the relevance-evaluation step and the Slack summary text
- **Slack webhook:** set up via a Slack app's Incoming Webhooks feature — no OAuth flow needed, just a POST URL. Document any rate limits encountered.
- **Run cadence:** [document the interval chosen once decided, e.g. every 6 hours via cron] and why that interval balances freshness against API cost

## What "done" looks like for this project

A feature is done when: it passes lint, type checks, and tests; a full run completes end-to-end without crashing even if one item fails partway through; and the Slack notification has been manually verified to look right, not just logged correctly.
