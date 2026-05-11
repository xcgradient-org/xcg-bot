# Internal Tools

This folder contains the React internal tools and the Python backend that talks to Notion, the LLM parser, and Discord.

Build the frontend:

```bash
cd internal-htmls/app
npm install
npm run build
```

Run the server from the repo root:

```bash
make -C internal-htmls online HOST=127.0.0.1 PORT=8012
```

This builds the React app, kills any previous server on that port, starts a new background server, and writes logs to `internal-htmls/internal-server.log`.

Then open:

- Home: `http://127.0.0.1:8012/`
- Task Creator: `http://127.0.0.1:8012/task-creator`
- OKR Creator: `http://127.0.0.1:8012/okr-creator`
- Meeting Creator: `http://127.0.0.1:8012/meeting-creator`
- Log Creator: `http://127.0.0.1:8012/log-creator`

The old URLs still redirect when the React build exists:

- `/task creator/`
- `/okr creator/`

API routes:

- `GET /api/projects`
- `POST /api/parse`
- `POST /api/preview-ids`
- `POST /api/tasks`
- `POST /api/okr/parse-krs`
- `POST /api/okr/push`
- `POST /api/meetings/parse`
- `POST /api/meetings`
- `GET /api/current-week`
- `GET /api/week`
- `POST /api/week/rollover`
- `POST /api/log/preview`
- `POST /api/log`

Required environment variables are loaded from the repo `.env`:

- `NOTION_TOKEN`
- `NOTION_TASKS_DB_ID` or `NOTION_TASKS_DB`
- `NOTION_TEAM_DB_ID` or `NOTION_TEAM_DB`
- `NOTION_MEETINGS_DB_ID` or `NOTION_MEETINGS_DB`
- `DISCORD_TOKEN`
- `DISCORD_ANNOUNCEMENTS_CHANNEL_ID`

Optional overrides:

- `INTERNAL_HTMLS_HOST`
- `INTERNAL_HTMLS_PORT`
- `NOTION_OBJECTIVES_DB_ID` or `NOTION_OBJECTIVES_DB`
- `NOTION_KRS_DB_ID` or `NOTION_KRS_DB`

For `internal.xcgradient.com`, run the server on `127.0.0.1` and point Cloudflare Tunnel to `http://127.0.0.1:8013`, then protect the hostname with Cloudflare Access.
