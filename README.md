# command-block

A small self-hosted admin dashboard for the Minecraft server stack — live status,
browser RCON console, quick commands (gamemode, give, tp, time, weather, gamerules,
effects, summon and friends with syntax-aware forms and one-click presets),
player/whitelist management, log tail, and a graceful restart button. FastAPI +
vanilla JS, one container, deliberately **no Docker socket**: the entire admin
surface is RCON plus a read-only log mount.

Named for the in-game block whose entire job is executing console commands.

## How it works

- `GET /api/status` is a server-list ping to `minecraft:25565`; every other action is
  a per-request RCON call to `minecraft:25575` over the minecraft stack's Docker network.
- **Restart** = RCON `stop` (saves the world, exits cleanly) + the minecraft container's
  `restart: unless-stopped` policy. No socket, no exec.
- Logs come from a read-only bind mount of the server's `logs/` directory.
- Optional HTTP Basic auth via `DASH_USER`/`DASH_PASS`; `/healthz` always stays open
  for Uptime Kuma.
- **LAN/Tailscale only. Never add this to a tunnel or reverse proxy.**

## Deploy

Part F of `command-block-build-plan-v1_1.md`: clone into `/opt/stacks/command-block`,
copy `.env.example` to `.env` and fill in the minecraft stack's RCON password
(`chmod 600`), then `docker compose up -d --build`. UI on `:8300`.

## Develop

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest                      # no server needed
RCON_HOST=localhost RCON_PASSWORD=... .venv/bin/uvicorn app.main:app --port 8300
```

No state, no database, no build step. The container can be killed and recreated at will.
