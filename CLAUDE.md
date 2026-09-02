# CLAUDE.md

command-block is a sidecar admin dashboard for the minecraft Dockge stack: live status,
browser RCON console, players/whitelist, log tail, graceful restart. It is a **spectator,
not a dependency** — the Minecraft stack must run identically with this container stopped.
Built per `command-block-build-plan-v1_1.md` (copy in `~/notes/guides/`), which is the
authoritative spec; deployment is that plan's Part F.

<!-- BEGIN:baseline-conventions (synced by scripts/sync-baseline.py — edit blocks there, then re-run) -->
## Baseline conventions

- **Always recommend when asking.** With `AskUserQuestion` or options in prose, name the option you'd pick, whether the lean is **strong** or **weak**, and a one-line why — no neutral menus.
- **Build in milestones and pause** so the user can run each slice before you go deeper; don't start a major new phase without a go-ahead.
- **Keep this file current** — folding session gotchas, non-obvious behavior, and decisions back into `CLAUDE.md` is a pre-commit step, not an afterthought.
- **Verify behavior, not just types** — run the build/tests before committing and actually exercise user-facing changes before claiming they work. Small, reviewable commits; run the test suite on every change to tested code.
- Never commit secrets or `.env`. Keep answers concise and direct.
<!-- END:baseline-conventions -->

## The one invariant that governs everything

**No Docker socket, ever.** The entire admin surface is RCON (`minecraft:25575` over the
stack's Docker network) plus a read-only bind mount of the log directory. Restart is the
RCON `stop` command + the minecraft container's `restart: unless-stopped` policy — anything
that would need the socket (container start, resource graphs, config editing) is a
**non-goal**, handled by Dockge/Beszel/code-server. And the UI is LAN/Tailscale only:
never add it to a tunnel, Caddy, or any reverse proxy.

## Setup & commands

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest                    # backend: 62 tests, no network, no MC server
node --test                                   # frontend builders + stat/detail/forge transforms: 50 tests (bare, not `node --test tests/`)
RCON_HOST=... RCON_PASSWORD=... .venv/bin/uvicorn app.main:app --port 8300
docker compose up -d --build                  # the real deployment (needs .env)
```

Config is env-only: `RCON_HOST/PORT/PASSWORD`, `DASH_PORT`, optional `DASH_USER`/`DASH_PASS`
(both set = HTTP Basic auth on everything except `/healthz`). `LOG_FILE` overrides the log
path (`/mc-logs/latest.log` in-container) and `MC_DATA` the data-dir mount (`/mc-data`) —
both used by tests and local runs only. `AVATAR_URL` overrides the player-head source
template (set empty to disable avatar fetching).

## Gotchas & conventions

- **Developed on the K12, deployed on webnode.** This repo lives on `teamgreenserver`
  (the K12, 10.0.0.60 — the Claude Code host), but the Minecraft server lives on
  **`webnode` (10.0.0.64)** since the 2026-07 migration, and that's where this stack
  deploys (build plan Part F). There is deliberately **no K12→webnode SSH trust**
  (lateral-movement containment) — deployment is manual, over SSH from the user's own
  devices.
- ⚠️ The K12 still holds a **stale soak-period copy** of the minecraft stack at
  `/opt/stacks/minecraft` — never start it (divergent worlds), and never point a local
  run of command-block at it. E2E-test against a throwaway server instead (see below).
- `compose.yaml` joins the **external** network `minecraft_default` — compose errors at
  `up` if the minecraft stack has never been started on the host.
- After a manual `docker compose stop` of the minecraft stack (on webnode), the restart
  button can't bring the server back (Docker's manual-stop flag persists) — that needs
  `cd /opt/stacks/minecraft && docker compose up -d` once.
- RCON responses carry `§` color codes — `strip_colors()` before parsing; `/api/tps`
  falls back to the raw string rather than erroring when Paper changes the format.
- Whitelist add/remove returns the **raw** RCON response on purpose: exact-case
  mismatches ("That player does not exist") must stay visible.
- Player names are validated (`^[A-Za-z0-9_]{1,16}$`) before being spliced into RCON
  commands — keep that gate on any new endpoint that takes a name.
- The RCON password lives in two `.env` files (minecraft's and this one's) — one
  Vaultwarden entry covers both.
- Frontend is deliberately framework-free with zero external requests: the favicon,
  dirt-texture background and fallback avatar are data URIs, and the Minecraft-style pixel
  font is **vendored** (`app/static/monocraft.ttf`, Monocraft, SIL OFL 1.1 — license
  alongside). Keep it that way. It's ES modules (`app.js` imports `quick-commands.js`) —
  keep new frontend logic that builds strings DOM-free in `quick-commands.js` so
  `node --test` can cover it.
- **`GET /api/avatar/{name}` is the project's one backend-outbound internet call**: it
  proxies mc-heads.net renders (by name; `?full=1` = full-body via `AVATAR_BODY_URL`,
  else the face) with an in-memory cache (6h, failures 10min) so the browser stays
  LAN-only. `AVATAR_URL=` (empty) disables ALL avatar fetching; on 404 the frontend swaps
  in a built-in pixel-body placeholder. Don't add other outbound calls without the same
  cache + kill-switch treatment.
- **World-state files on Paper 26.2** (this generation gutted `level.dat` to ~600 bytes):
  weather is NBT at `world/dimensions/minecraft/overworld/data/minecraft/weather.dat`
  (`raining`/`thundering` bytes), and the cumulative day counter is `total_ticks` in the
  **overworld's** `data/minecraft/world_clocks.dat` — the world-level copy of that file
  exists but stays at 0 (decoy). Both update only on save, so `/api/clock`'s weather can
  lag ~5 min (the UI compensates by showing just-sent weather commands optimistically).
  There is **no RCON weather query**; live time-of-day is the new timeline syntax
  `time query day` → "Timeline minecraft:day is at N tick(s)" (wraps at 24000, 0=06:00;
  the old `time query daytime` is gone). `session.lock` mtime = world-load time (uptime).
  `/api/serverinfo` adds RCON `mspt`/`seed`/`difficulty`/`banlist` + server.properties
  + a 5-min-cached world-size walk.
- `GET /api/playerstats` (cards' "Last seen"/"Played") reads the **read-only data-dir
  mount** (`/mc-data`): `usercache.json` for name→UUID, the world's per-player stats
  JSON play-time counter (72000 ticks = 1h; legacy `play_one_minute` key also handled),
  and the player .dat mtime as last-seen. ⚠️ **This MC generation moved the files**:
  `world/players/{stats,data}/` — the classic `world/{stats,playerdata}/` is also
  supported, and the world folder name is auto-detected. These files only update on
  save/logout/autosave, so a currently online player's hours lag a few minutes — the UI
  shows "now" for their last-seen. Name→UUID mapping merges `usercache.json` (expires
  ~30 days after last join) with `whitelist.json` (permanent), so whitelisted players
  keep lifetime stats no matter how long they've been away.
- `/api/playerstats` computes **every** card stat (deaths, life/sleep timers, kills,
  damage, distances, mining, crafting, husbandry, plus XP/health/food read from the
  playerdata .dat NBT — classic names `XpLevel`/`Health`/`foodLevel` survive in 26.2).
  Which rows actually render is chosen on the **Settings tab**: the registry + formatters
  live in `app/static/stats.js` (DOM-free, node-tested), the selection persists via
  GET/POST `/api/settings` → `settings.json` in `cb_data` (backend is dumb storage;
  `card_stats: null` = frontend defaults).
- **Dashboard state lives in the `cb_data` volume**: `waypoints.json` and
  `settings.json`. Waypoints details: `waypoints.json` in the `cb_data`
  named volume (`CB_DATA` overrides the dir for tests; the Dockerfile pre-creates
  `/cb-data` owned by `dash` so the volume inherits writable ownership). CRUD via
  GET/POST `/api/waypoints` (names ≤32 chars of letters/digits/spaces/-_', positions
  strictly "x y z" — only validated pos/dim ever reach RCON). `GET /api/position/{name}`
  grabs an online player's spot via `data get entity` for the capture-position button.
  Waypoint teleports go through `buildWaypointTp` — `execute in <dim> run tp` whenever
  the waypoint recorded a dimension, so cross-dimension teleports work.
- **Per-player analytics page**: clicking a card's name routes to the virtual hash page
  `#player/<name>` (not a tab), rendered from `GET /api/playerdetail/{name}` — the raw
  stat sections passthrough (name resolved case-insensitively to canonical case). The
  breakdown math lives in `app/static/detail.js` (DOM-free, node-tested): top-N bar
  tables per section, deaths split into itemized mob deaths + a derived environmental
  remainder (vanilla doesn't itemize fall/lava/drowning), damage in hearts, movement per
  `*_one_cm` counter, an Interactions panel (`interact_with_*`/`open_*`/`inspect_*` +
  curated keys), and an auto-formatted "everything else" long tail. Bar charts are
  single-hue per panel (MC chat colors, values always visible as text) — keep it that
  way; don't mix hues within one bar table.
- ⚠️ **The container must run as uid 1000** (same as the minecraft container's user):
  the server writes playerdata `.dat` files as mode **600**, so any other uid gets
  permission-denied and XP/health/food silently null out — while the stats JSONs (664)
  and mtimes still work, which masks the problem. The entrypoint starts as root only to
  chown `/cb-data` (self-heal from older uid-10001 images), then drops to `dash` via
  setpriv. Local pytest runs as the file owner and can't catch this class of bug — check
  file *modes*, not just readability, when adding new file-reading features.
- **Gear recovery** (Recovery tab): `app/nbt.py` is a full NBT parser + SNBT writer —
  wrapper types (`Byte`/`Short`/`Long`/`Float`/arrays) preserve tag widths so item
  components round-trip verbatim into `give <player> <id>[components] <count>` strings
  (validated against live Paper 26.2). Sources: each player's current `.dat`, their
  `.dat_old`, or an uploaded backup `.dat` (raw-bytes POST, no multipart dep). Read-only
  on world files; gives go through `/api/command`. NBT gotcha that cost a bug: in
  `out[self.string()] = self.payload(tag)` Python evaluates the RIGHT side first —
  always read the name into a local before the payload.
- UI structure: nine hash-routed tabs — **Dashboard** (Global commands across the top +
  a full-body card per whitelisted/online player), **Server Info** (status/facts +
  world panel), **Console**, **Whitelist**, **Waypoints**, **Forge** (enchanted-item builder), **Recovery** (gear
  restoration from saves/backups), **Settings** (card-stat picker), **Logs** — plus the
  header's sky widget (status dot, in-game clock +
  weather-condition icon, day count). The card vs
  global split is data-driven: each command in `quick-commands.js` carries
  `scope: 'player'|'global'`, and player commands name their `playerField`, which cards
  auto-fill with the card's player and hide (`cardHide` drops extra fields, e.g. summon's
  coords). Add a new command there and the right UI renders it automatically.
- The UI is Minecraft-GUI themed by design (`style.css`): inventory-gray beveled panels,
  stone buttons, black edit boxes, MC chat colors (`#55FF55`/`#FF5555`/`#FFAA00`) — stay
  in that visual language for new UI.
- **RCON has no executor** (no position, no "self") — that's why the quick panel makes
  clear/kill/gamemode targets required and summon goes through
  `execute at <player> run summon … ~ ~ ~` or explicit coords.
- **This MC generation renamed all gamerules to snake_case** (doDaylightCycle →
  `advance_time`, doMobSpawning → `spawn_mobs`, keepInventory → `keep_inventory`…).
  The full registry lives in the server jar's `GameRules.class`; the curated list in
  `quick-commands.js` was extracted from there and verified over RCON on Paper 26.2.

## Verified behavior (2026-08-02, local E2E vs a throwaway Paper 26.2)

Status/players/whitelist/broadcast/command/tps/save/logs all exercised against a real
itzg Paper server; the restart flow confirmed end-to-end (RCON `stop` → clean exit →
`unless-stopped` restart → status green, restart count +1).
