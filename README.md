# XC Gradient Internal

This repo now centers on the internal website for XC Gradient. The Discord bot remains available as a thin adapter while the web app becomes the primary interface.

## Features

- Internal website for tasks, OKRs, meetings, and week rollover
- FastAPI backend with shared Notion and LLM integrations
- Optional Discord command adapter over the same backend-facing logic
- Automatic daily logs, reflection generation, and streak tracking

## Installation

1. Clone the repo and install dependencies (Python 3.10+):
   ```bash
   git clone <repo-url>
   cd xcg-bot
   uv venv
   uv sync --dev
   ```
2. Configure environment variables in `.env`:
   ```env
   DISCORD_TOKEN=...
   NOTION_TOKEN=...
   NOTION_DATABASE_ID=...
   LLM_API_KEY=...
   # optional failover:
   LLM_API_KEY_2=...
   LLM_API_KEY_3=...
   ```

## Usage

Start the internal website:
```bash
make online
```

Start the Discord adapter:
```bash
make bot
```

## Repo Shape

- `frontend/`: React app
- `backend/`: FastAPI app and internal services
- `bot/`: Discord adapter entrypoint

## Docs

- [Docs index](./docs/README.md)
- [Startup](./docs/STARTUP.md)
- [Notion databases](./docs/NOTION_DATABASES.md)

## Development

The website is the primary product surface. New product logic should live behind the backend service layer and be reused by both the web API and any remaining Discord commands.

## License

All rights reserved. © 2026 XC Gradient.
