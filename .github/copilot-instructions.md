# Agent project instructions

The full project conventions live in [CLAUDE.md](../CLAUDE.md) at the repo root; read it first. It is the single source of truth for code style, logging, error handling, testing, project structure and git workflow. The build order and progress are in [roadmap.md](../roadmap.md).

Summary of the essentials:

- Follow the existing project structure and conventions.
- Keep changes focused on the requested behavior.
- Every module uses `logging.getLogger(__name__)`; `configure_logging()` is called only at the entry point (`agent.py`). Wrap every external call (Tavily, Anthropic, Slack) at its boundary: catch, log, degrade gracefully.
- Every change ships with tests; mock all external services.
- Before committing, run `ruff format .`, `ruff check .`, `mypy .` and `pytest` (all must pass; 90% coverage of `src/` required).
- Never commit `.env`, API keys or the Slack webhook URL.
