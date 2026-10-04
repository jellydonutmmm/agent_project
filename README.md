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
Scheduled run (GitHub Actions, daily)
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
git clone https://github.com/jellydonutmmm/agent_project.git
cd agent_project
python -m venv venv && source venv/bin/activate   # Windows (PowerShell): venv\Scripts\Activate.ps1
pip install -r requirements.txt
# add TAVILY_API_KEY, ANTHROPIC_API_KEY, and SLACK_WEBHOOK_URL to .env (see Credentials)
set -a && source .env && set +a                   # the agent reads real environment variables, not .env itself
python -m src.agent
```

A run writes its history to `agent.db` and its log to `agent.log` in the current directory (both gitignored).

## Scheduling

The agent runs once a day on a GitHub Actions schedule (`.github/workflows/daily-run.yml`, 13:00 UTC), which is free for public repos and doesn't depend on any personal machine being on. It can also be started by hand from the Actions tab. Daily keeps it at about 510 Tavily queries a month (17 queries x 30 days), under the free tier's 1,000; a 6-hour cadence would need about 2,040. Daily freshness is enough for industry-trend news.

GitHub's runners start empty each time, so the SQLite history is saved to a `state` branch after each run and restored before the next. Because the repo is public, that branch is public too: it holds only news URLs, titles and the model's relevance reasons, never secrets.

## Credentials

Keys go in `.env` locally (gitignored) and in GitHub repository secrets for the scheduled run. Never paste them into code, chat or commits.

### Anthropic
Purpose: relevance evaluation and Slack summaries (Claude Sonnet).
Env var: `ANTHROPIC_API_KEY`
Limits / cost: pay-as-you-go, roughly pennies per day at one evaluation per new item plus a short summary per relevant one. The monthly spend cap below bounds the worst case.
1. Go to https://console.anthropic.com and sign in (separate from a claude.ai chat subscription).
2. Under Settings → Billing, add a card and a small amount of credit (e.g. $5), then set a monthly spend limit (e.g. $5-10).
3. Under Settings → API keys, create a key named `game-news-agent`, with a 90-day expiry if offered.
4. Copy it once (it starts with `sk-ant-`) and add `ANTHROPIC_API_KEY=<value>` to `.env`.
5. Verify with one small real call before a full run.
6. For the scheduled run, add the same value as a repository secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions).

Rotate / revoke: on the same API keys page, create a new key, update `.env` and the GitHub secret, then delete the old key. Do this before the 90-day expiry (set a calendar reminder about a week ahead): an expired key makes every evaluation fail and the run posts nothing to Slack, which looks like a quiet news day.

## Search topics

Queries cover video game development industry signals: studio layoffs/closures, hiring surges, engine and platform trends (Unreal, Unity, Godot), funding/acquisitions, and major publisher/studio announcements. The exact query list lives in `src/search.py`.

## Known limitations

Findings from building and from the first real run (76 items):

**Dedup**
- Duplicate detection is URL-exact plus title similarity (`difflib`, threshold 0.85). The same article under a different URL is not caught by the URL check: tracking parameters such as `?ref=...` or `&vl=en` make it look new. 8 of the 76 first-run URLs had query strings.
- Title similarity misses the same story with differently structured headlines, reordered wording, and short titles. See `CLAUDE.md` for the full list.

**Evaluation**
- Each item is judged by a single LLM call from the search snippet, not the full page, with no human override. Decisions can vary between runs.
- The first prompt let through index pages, homepages, profile pages and old announcements (about 13 of 21 "relevant" items on the first run). The prompt now rejects those and judges age against today's date, which also drops some borderline recent items, such as a survey report from eight months earlier.
- The prompt leans "not relevant" when unsure, so it prefers missing a minor item to sending a noisy one.
- Search results include non-news (YouTube, Wikipedia, vendor pages), which costs evaluation calls even when they're rejected.

**Pipeline**
- An item whose evaluation fails is kept (with its content) and retried on later runs, up to 3 attempts in total, so a short outage doesn't lose items. After 3 failed attempts it's given up on, so an outage longer than about three daily runs still drops that day's items.
- An item whose Slack post fails is recorded as evaluated and is not retried, so it is never posted.
- If a run as a whole looks broken (search returns nothing, or every evaluation fails), the agent posts a warning to the Slack channel and exits non-zero, so the GitHub Actions run shows red. A partial failure, such as a few bad items, does not trigger this.
- Tavily returned no `source` for any of the 76 results, so Slack links are labeled "link" instead of the outlet name.
- The first run has no history, so it posts a large batch at once (21 notifications). Later runs should be much quieter.
- Slack posts are spaced about a second apart to stay under its webhook rate limit. A long batch therefore takes a while.
- Scheduled GitHub Actions runs can start a few minutes late, and GitHub pauses scheduled workflows in repos with no activity for 60 days.

## Demo

An excerpt from a real scheduled-style run on GitHub Actions (2026-10-04), lightly trimmed: timestamps shortened to the time, some reasons cut with "…", and uninteresting lines left out. Each item moves through `found` → `evaluated` → `decision` → `notified`, and the run ends with a summary line.

```
20:57:14 search returned 80 results
20:57:14 skipped duplicate: Layoffs | GamesIndustry.biz (https://www.gamesindustry.biz/topics/layoffs)
20:57:14 found: id=76 Inside the latest round of mass layoffs at Xbox (https://www.gamedeveloper.com/production/-good-work-is-not-going-to-save-your-job-at-this-company-laid-off-xbox-devs-condemn-microsoft)
20:57:16 evaluated: id=76
20:57:16 decision: id=76 relevant=True reason=Reports on mass layoffs at Xbox studios (id Software, Bethesda, ZeniMax Online) confirmed by Xbox CEO Asha Sharma, with laid-off staff describing impacts on id Tech and Doom support teams. The layoffs date from July 6 and the story is a recent follow-up, so it is still a concrete, substantive layoff development.
20:57:19 notified: id=76
20:57:19 found: id=77 What Is Happening With Games Industry Layoffs? - Kai's Game Dev Blog (https://kaiwueest.com/insights/layoffs)
20:57:21 decision: id=77 relevant=False reason=This is an evergreen blog explainer on the history of games industry layoffs (2021 expansion, pandemic funding), not a report of one specific new event, so it describes a topic rather than a current development.
...
20:57:31 decision: id=82 relevant=False reason=The item is a Unity press release from GDC 2025 about planned Unity 6 updates, which is roughly 18 months before today's date of 2026-10-04, so it is old news. It is also largely promotional product-roadmap content.
...
20:58:17 run summary: searched=80 duplicates=52 found=28 evaluated=28 notified=1 errored=0
```

Of the 80 results, 52 were already in the history and skipped without an LLM call, and 28 were new. The agent judged 27 of those not relevant (index pages, evergreen explainers, vendor marketing, old announcements) and posted the one concrete, recent development to Slack.
