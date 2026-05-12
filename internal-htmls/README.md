# Internal Tools

This folder is now a compatibility launcher for the internal website. The React app lives in `frontend/` and the Python API lives in `backend/`.

Build the frontend:

```bash
cd frontend
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
- `GET /api/week`
- `GET /api/current-week`
- `GET /health`
- `POST /api/parse`
- `POST /api/tasks/parse`
- `POST /api/preview-ids`
- `POST /api/tasks/preview-ids`
- `POST /api/tasks`
- `POST /api/okr/parse-krs`
- `POST /api/okrs/parse-krs`
- `POST /api/okr/push`
- `POST /api/okrs`
- `POST /api/meetings/parse`
- `POST /api/meetings`
- `POST /api/week/rollover`
- `POST /api/log/preview`
- `POST /api/logs/preview`
- `POST /api/log`
- `POST /api/logs`

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

For `internal.xcgradient.com`, run the server on `127.0.0.1` or the Tailscale IP and point your internal DNS or reverse proxy to that address.
