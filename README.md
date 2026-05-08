# 🤖 XCGradient Bot (XCG-Bot)

The main operational bot for XC Gradient, managing Discord logging, tasks, and meetings with Notion integration.

## 🚀 Features

- **Logging:** `/log` logs updates to Notion.
- **Tasks:** `/tasks add` adds tasks to Notion, with an AI fallback (Gemini CLI) for parsing complex requests.
- **Meetings:** `/meeting` for real-time syncs and summaries.
- **Reflection:** Daily/weekly reflection tools.
- **Streaks:** Tracking operational momentum.

## 📥 Installation

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

## 🛠️ Usage

Run the bot:
```bash
python main.py
```

## 🕸️ Code Graph

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

## 📂 Core Modules

- `main.py`: Discord client and command registration.
- `notion.py`: Notion API wrapper and data management.
- `task_command.py`: Logic for task creation and AI parsing.
- `meeting_command.py`: Management of operational syncs.

## 👨‍💻 Development

To add new commands, implement them within the appropriate `*_command.py` module and register the new slash command in `main.py`.

## 🐳 Docker & CI/CD

The bot is fully containerized for reliable deployment.

### Run in Docker
```bash
docker build -t xcg-bot .
docker run --rm --env-file .env xcg-bot
```

### GitHub Actions
Every push to `main` triggers:
- **Test:** Runs all Python tests via `pytest`.
- **Lint:** Checks code quality with `flake8`.
- **Build & Push:** Automatically pushes the latest image to `ghcr.io/xcgradient-org/xcg-bot:latest`.

## ⚖️ License

All rights reserved. © 2026 XC Gradient.
