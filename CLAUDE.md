# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

An internal web app for XC Gradient (founders only, served over Tailscale at `100.72.248.102:8013`). The website is the primary surface; a Discord bot is a thin adapter that reuses the same backend services. Notion is the system of record for tasks, daily logs, meetings, OKRs, projects, and team identity.

Stack: FastAPI + React 19 (Vite) frontend + `discord.py` bot, all in Python 3.11+ managed by `uv`.

## Common commands

```bash
uv sync --dev                                       # install deps (pyproject.toml + uv.lock)

# Website (primary)
make web                                            # build frontend, restart server, wait for /health
make online HOST=0.0.0.0 PORT=8014                  # same without health-check wrapper
make stop                                           # kill the backgrounded server
make status                                         # show what's on PORT

# Discord bot adapter
make bot                                            # = python -m bot.main
make run                                            # alias of make bot

# Frontend only
make build-frontend                                 # cd frontend && npm install && npm run build
cd frontend && npm run dev                          # Vite dev server on :5173

# Tests
make test                                           # python -m unittest -q backend.tests.test_xcg_bot
.venv/bin/pytest backend/tests/test_xcg_bot.py      # same files run fine under pytest
.venv/bin/pytest backend/tests/test_xcg_bot.py::TestClass::test_method   # single test
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics       # matches CI lint
```

`make web` runs `backend.app` as a backgrounded process; PID lives in `.internal-server.pid` and stdout/stderr in `internal-server.log`. If the server seems wedged, `make stop && make web` is the recovery path — don't `kill -9` blindly because the Makefile cleans up the PID file.

## Architecture

### Composition root

`backend/services/container.py` is the DI seam. `build_services()` constructs a single `InternalRuntime` (Notion client + LLM client + Discord credentials) from env vars, then injects it into every service (`TasksService`, `OKRsService`, `MeetingsService`, `LogsService`, `WeekService`, `StreaksService`, `DailyLogDedupeService`, `ProjectsService`, `TeamUsageService`). `backend/app.py` builds the app once at import time and exposes the container at `app.state.services`.

The Discord bot (`bot/main.py`) does **not** go through this container — it instantiates `NotionService` and `ReflectionService` directly with the same `Settings`. The bot is now **messenger-only**: it runs meeting announcement/reminder pollers and the daily streak reset. There are no slash commands. New product logic belongs in `backend/services/`.

### Notion integration (`backend/integrations/notion.py`)

One ~1.6k-line module wrapping `notion_client.Client`. Two things matter when editing it:

1. **`PROPERTY_ALIASES`** — every field lookup goes through aliases so renames in Notion don't break code. If you add a new property reference, extend this map; don't hardcode the literal name.
2. **Founder fields are relations to the Team DB**, not plain text. `Founder` on Daily Logs, `Owner` on Tasks, `Attendees` on Meetings, etc. all resolve via Team page IDs. The old separate Streaks DB is gone — `Current Streak`/`Best Streak`/`Last Log` are properties on Team rows now, and streak code is gated by `notion.streaks_available()`.

See `docs/NOTION_DATABASES.md` for the authoritative schema of all 8 Notion databases and known code/schema drift.

### Time and week semantics (`backend/domain/dates.py`)

Everything is Europe/Madrid. The "logical day" cutoff is 05:00: a log created between 00:00–04:59 Madrid still belongs to the previous business day. Week codes are `YY-WNN` (e.g. `26-W19` for ISO week 19 of 2026). Week rollover state comes from the Notion Settings DB if `NOTION_SETTINGS_DB_ID` is set; otherwise from the `Is Current Week` flag on tasks. If neither exists, `/api/current-week` and rollover fail loudly rather than silently falling back to the calendar week.

### LLM client (`backend/integrations/reflection.py`)

Only `LLM_API_STYLE=openai` is supported. Multiple keys can be configured via `LLM_API_KEY`, `LLM_API_KEY_{1,2,3}`, `LLM_API_KEYS` (comma-separated), or the `GROQ_*` aliases — they're tried in order on failure. Default base URL is Groq.

### Frontend

React 19 + Vite, served as static assets from FastAPI. The SPA fallback in `backend/app.py` routes any non-`/api/*` path to `index.html`, with explicit routes (`/task-creator`, `/okr-creator`, `/meeting-creator`, `/claude-usage`) declared so they can carry `Cache-Control: no-store`. Routes are also listed in `frontend/src/lib/routes.js` for the home page card grid — keep these in sync when adding pages.

### API surface

All HTTP endpoints live in `backend/api/routes.py` under `/api`. `_service_call()` is the only error-translation layer: `ValueError → 400`, `RuntimeError → 500`. The `/reports/week-pwp*` endpoints additionally require a Bearer token if `INTERNAL_API_TOKEN` is set.

## Conventions and gotchas

- **Don't add new Notion property lookups without going through `PROPERTY_ALIASES`** — bare string property names break the first time someone renames a column in the UI.
- **People are always relation IDs**, never names or text. Resolve through `notion.list_team_members()` / `FOUNDER_BY_ID`.
- **The Discord bot is messenger-only.** `bot/commands/` contains only `meetings.py` (meeting announcement and reminder pollers). Do not add new Discord commands. New product logic belongs in `backend/services/`.
- **The `.github/workflows/` CI path filter is stale** (it expects `automation/xcg-bot/**`), so CI may not run on PRs against this repo's current layout. Verify the workflow before relying on it.
- **Don't commit `.env`, `internal-server.log`, or `.internal-server.pid`** — they're git-ignored for a reason; the `.env` here contains real credentials.
- Tests live in `backend/tests/`. The main suite (`test_xcg_bot.py`) is ~2k lines and runs under both `unittest` and `pytest`.
