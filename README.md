# XC Gradient Internal

This repo now centers on the internal website for XC Gradient. The Discord bot remains available as a thin adapter while the web app becomes the primary interface.

## Features

- Internal website for tasks, OKRs, meetings, logs, and week rollover
- FastAPI backend with shared Notion and LLM integrations
- Optional Discord command adapter over the same backend-facing logic
- Reflection and streak tracking

## Installation

1. Clone the repo and install dependencies (Python 3.10+):
   ```bash
   git clone <repo-url>
   cd xcg-bot
   pip install -r requirements.txt
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
make web
```

Start the Discord adapter:
```bash
make bot
```

## Repo Shape

- `frontend/`: React app
- `backend/`: FastAPI app and internal services
- `bot/`: Discord adapter entrypoint
- `internal-htmls/`: compatibility launcher and operational helpers

## Code Graph

The repo also includes a local `graphify` workflow that builds a dependency graph for the whole bot codebase and exports it to Obsidian.

From inside `xcg-bot/`:

```bash
make graph
```

What this does:

- extracts the code graph from the local repo
- regenerates `graphify-out/graph.json`, `graphify-out/graph.html`, `graphify-out/wiki/`, and `graphify-out/GRAPH_REPORT.md`
- exports Obsidian notes to `~/vault/graphify/xcg-bot`
- opens that Obsidian vault

If you want a rebuild without launching Obsidian:

```bash
make graph-no-obsidian
```

If you just want to validate the graph inputs:

```bash
make validate-graph
```

When the code changes, rerun `make graph`. There is no seed file in this repo: the graph is rebuilt directly from the source code each time.

## Development

The website is the primary product surface. New product logic should live behind the backend service layer and be reused by both the web API and any remaining Discord commands.

## Docker & CI/CD

The bot is fully containerized for reliable deployment.

### Run in Docker
```bash
docker build -t xcg-bot .
docker run --rm --env-file .env xcg-bot
```

## License

All rights reserved. © 2026 XC Gradient.
