# Game Industry Trends Monitor — Autonomous Research Agent

## What this is

An autonomous agent that monitors the video game development industry for substantive developments — studio layoffs and hiring waves, notable shifts in engine/platform adoption, funding and closures, relevant industry news — and notifies me via Slack when it finds something worth reading. Unlike a simple RSS/keyword alert, the agent evaluates each candidate item and decides whether it's actually new and relevant before surfacing it, rather than forwarding everything that matches a search query.

## Why this project

Built partly as a practical tool for tracking my own field (game development), and partly to demonstrate the harder engineering problems in agentic systems: making a judgment call under uncertainty, avoiding duplicate/noisy notifications, and handling failures in a multi-step pipeline gracefully.

## Key engineering decisions

- **Tool design:** the agent has three narrowly-scoped tools — web search, a relevance-evaluation step (LLM call with structured output), and a Slack webhook notifier — kept separate so each is independently testable
- **Dedup:** every processed item is checked against a local SQLite store (by URL and title similarity) before it reaches the LLM evaluation step, to avoid wasting calls on repeats
- **Judgment step:** the LLM outputs a structured decision (relevant: true/false + a one-line reason) for each new item, rather than a free-text response — this keeps the decision auditable and easy to log
- **Error handling:** a failure on one item (bad search result, malformed content) is caught and logged without halting the run; Slack webhook calls retry with backoff on transient failures
- **Observability:** every item processed — found, evaluated, decision, reasoning, timestamp — is persisted to SQLite, giving a full audit trail of what the agent has seen and decided

## Architecture

```
Scheduled run (cron)
  → Search step: Tavily API queries video game industry topics
  → Dedup: check against SQLite history
  → Evaluation step: Claude judges relevance, returns structured decision + reason
  → Notify: relevant items summarized and posted to Slack via webhook
  → Log: every item's outcome persisted to SQLite
```

## Tech stack

- Backend: Python
- Search: Tavily API (`tavily-python`) — free tier, 1,000 queries/month, no card required
- LLM: Claude (Sonnet) via the `anthropic` Python SDK — used for relevance evaluation and summarization
- Storage: SQLite
- Notification: Slack incoming webhook

## Running it locally

```bash
git clone [repo-url]
cd [repo-name]
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# add TAVILY_API_KEY, ANTHROPIC_API_KEY, and SLACK_WEBHOOK_URL to .env
python agent.py
```

## Search topics

Queries cover video game development industry signals: studio layoffs/closures, hiring surges, engine and platform trends (Unreal, Unity, Godot), funding/acquisitions, and major publisher/studio announcements. The exact query list lives in `search.py`.

## Known limitations

[Fill in as you build — e.g. "relevance judgment is a single LLM call with no human-in-the-loop override yet" or "dedup is title-similarity based and may miss reworded duplicates."]

## Demo

[Screenshot of a Slack notification, or a sample log of a run's decisions]
