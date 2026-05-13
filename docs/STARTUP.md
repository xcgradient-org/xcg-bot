# Startup

Run this from the repo root:

```bash
cd /home/sterry/Desktop/xcgradient-org/xcg-bot
uv sync --dev
make web
```

`make web` rebuilds the React app, stops the previous internal server on the configured port, starts a fresh one in the background, and waits for `/health` to report ready. Logs are written to `internal-server.log`.

You can still use `make online` directly if you do not need the extra health check wrapper.

Use a different host or port like this:

```bash
make online HOST=100.72.248.102 PORT=8014
```

Stop it manually:

```bash
make stop
```

Check what is listening on the port:

```bash
make status
```

Share these links with cofounders connected to Tailscale:

- Home: `http://100.72.248.102:8013/`
- Task Creator: `http://100.72.248.102:8013/task-creator`
- OKR Creator: `http://100.72.248.102:8013/okr-creator`
- Meeting Creator: `http://100.72.248.102:8013/meeting-creator`

For `internal.xcgradient.com`, point your internal DNS or reverse proxy at the local server over Tailscale.
