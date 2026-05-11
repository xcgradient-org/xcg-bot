# Startup

Run this from the repo root:

```bash
cd /home/sterry/Desktop/xcgradient-org/xcg-bot
make -C internal-htmls online
```

That command builds the React app, stops the previous internal server on the configured port, and starts a fresh one in the background. Logs are written to `internal-htmls/internal-server.log`.

Use a different host or port like this:

```bash
make -C internal-htmls online HOST=100.72.248.102 PORT=8014
```

Stop it manually:

```bash
make -C internal-htmls stop
```

Check what is listening on the port:

```bash
make -C internal-htmls status
```

Share these links with cofounders connected to Tailscale:

- Home: `http://100.72.248.102:8013/`
- Task Creator: `http://100.72.248.102:8013/task-creator`
- OKR Creator: `http://100.72.248.102:8013/okr-creator`
- Meeting Creator: `http://100.72.248.102:8013/meeting-creator`
- Log Creator: `http://100.72.248.102:8013/log-creator`

For `internal.xcgradient.com`, point a Cloudflare Tunnel to the local server:

```bash
cloudflared tunnel --url http://127.0.0.1:8013
```

Then protect `internal.xcgradient.com` with Cloudflare Access.
