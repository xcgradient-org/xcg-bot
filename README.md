# 🤖 XCGradient Bot (XCG-Bot)

The main operational bot for XC Gradient, managing Discord logging, tasks, and meetings with Notion integration.

## 🚀 Features

- **Logging:** `/log` logs updates to Notion.
- **Tasks:** `/tasks add` adds tasks to Notion, with an AI fallback (Gemini CLI) for parsing complex requests.
- **Meetings:** `/meeting` for real-time syncs and summaries.
- **Reflection:** Daily/weekly reflection tools.
- **Streaks:** Tracking operational momentum.

## ⚙️ Installation

1. Install dependencies (Python 3.10+):
   ```bash
   pip install -r requirements.txt
   ```
2. Configure environment variables in `.env`:
   ```env
   DISCORD_TOKEN=...
   NOTION_TOKEN=...
   NOTION_DATABASE_ID=...
   GEMINI_API_KEY=...
   ```
3. Run the bot:
   ```bash
   python main.py
   ```

## 📂 Core Modules

- `main.py`: Discord client and command registration.
- `notion.py`: Notion API wrapper and data management.
- `task_command.py`: Logic for task creation and AI parsing.
- `meeting_command.py`: Management of operational syncs.

## ⚖️ License

All rights reserved. © 2026 XC Gradient.
