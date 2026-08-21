# command-block

A small self-hosted admin dashboard for the Minecraft server stack — live status,
a card per player with their avatar, last-seen time, hours played, and the
player-targeted commands right on it
(teleport, give, effect, gamemode, XP, message, summon, clear, kill, kick, ban),
global commands with one-click presets (time, weather, game rules, difficulty),
a browser RCON console, whitelist management, log tail, and a graceful restart
button, across four tabs. FastAPI + vanilla JS, one container, deliberately
**no Docker socket**: the entire admin surface is RCON plus a read-only log mount.

Named for the in-game block whose entire job is executing console commands — and
styled to match: the UI is a Minecraft-GUI theme (dirt background, inventory-gray
beveled panels, stone buttons) using the vendored [Monocraft](https://github.com/IdreesInc/Monocraft)
pixel font (SIL OFL 1.1). Still zero external requests at runtime.

## How it works

- `GET /api/status` is a server-list ping to `minecraft:25565`; every other action is
  a per-request RCON call to `minecraft:25575` over the minecraft stack's Docker network.
- **Restart** = RCON `stop` (saves the world, exits cleanly) + the minecraft container's
  `restart: unless-stopped` policy. No socket, no exec.
- Logs come from a read-only bind mount of the server's `logs/` directory; last-seen
  and hours-played come from a read-only mount of the data dir (usercache + world
  stats/playerdata — updated by the server on save, so online players' hours lag a
  little).
- Player heads are proxied and cached by the backend (`/api/avatar/<name>`, from
  mc-heads.net) so the browser never talks to the internet; set `AVATAR_URL=` empty
  to disable fetching entirely (cards then show a built-in placeholder face).
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
