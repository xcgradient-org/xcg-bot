# Internal HTML Tools

This folder contains the Notion-backed internal versions of the two root HTML mockups:

- `task creator/index.html`
- `okr creator/index.html`

Run the local server from the repo root:

```bash
python internal-htmls/server.py
```

Then open:

- `http://127.0.0.1:8012/task%20creator/`
- `http://127.0.0.1:8012/okr%20creator/`

The server keeps `NOTION_TOKEN` server-side and exposes only the small API surface the HTMLs already call:

- `GET /api/projects`
- `POST /api/parse`
- `POST /api/preview-ids`
- `POST /api/tasks`
- `POST /api/okr/parse-krs`
- `POST /api/okr/push`

Required environment variables are loaded from the repo `.env`:

- `NOTION_TOKEN`
- `NOTION_TASKS_DB_ID` or `NOTION_TASKS_DB`
- `NOTION_TEAM_DB_ID` or `NOTION_TEAM_DB`

Optional overrides:

- `INTERNAL_HTMLS_HOST`
- `NOTION_OBJECTIVES_DB_ID` or `NOTION_OBJECTIVES_DB`
- `NOTION_KRS_DB_ID` or `NOTION_KRS_DB`
- `INTERNAL_HTMLS_PORT`

If the OKR database IDs are not set, the server uses the IDs documented in `NOTION_DATABASES.md`.

To expose the tools to colleagues over Tailscale, bind to this machine's Tailscale IP:

```bash
INTERNAL_HTMLS_HOST=100.72.248.102 INTERNAL_HTMLS_PORT=8013 python internal-htmls/server.py
```
