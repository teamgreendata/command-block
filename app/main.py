"""command-block — RCON-shaped admin dashboard for the minecraft stack.

No Docker socket, no database. Everything is RCON plus read-only mounts of
the server's logs and data dir; config comes from the environment only. The
single piece of state is waypoints.json in the cb_data volume.
"""

import asyncio
import base64
import json
import os
import re
import secrets
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from mcstatus import JavaServer
from pydantic import BaseModel

from app import rcon
from app.rcon import RconError

PING_PORT = 25565  # server-list ping; RCON port comes from the env
STATIC_DIR = Path(__file__).parent / "static"
MAX_LOG_LINES = 500

app = FastAPI(title="command-block", docs_url=None, redoc_url=None, openapi_url=None)


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _log_file() -> Path:
    return Path(_env("LOG_FILE", "/mc-logs/latest.log"))


async def rcon_command(command: str, *, expect_disconnect: bool = False) -> str:
    return await rcon.execute(
        _env("RCON_HOST", "minecraft"),
        int(_env("RCON_PORT", "25575")),
        _env("RCON_PASSWORD", ""),
        command,
        expect_disconnect=expect_disconnect,
    )


# ---------------------------------------------------------------- parsers

_LIST_RE = re.compile(r"There are (\d+) of a max of (\d+) players online:?\s*(.*)", re.I)
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")


def strip_colors(raw: str) -> str:
    return re.sub("§.", "", raw)


def parse_list(raw: str) -> dict:
    m = _LIST_RE.search(strip_colors(raw))
    if not m:
        return {"online": None, "max": None, "players": [], "raw": raw}
    players = [p.strip() for p in m.group(3).split(",") if p.strip()]
    return {"online": int(m.group(1)), "max": int(m.group(2)), "players": players, "raw": raw}


def parse_whitelist(raw: str) -> list[str]:
    cleaned = strip_colors(raw)
    if ":" not in cleaned:  # "There are no whitelisted players"
        return []
    names = re.split(r",|\band\b", cleaned.split(":", 1)[1])
    return [n.strip() for n in names if n.strip()]


def parse_tps(raw: str) -> dict:
    # Paper: "TPS from last 1m, 5m, 15m: 20.0, 20.0, 20.0" (newer builds
    # prepend a 5s figure) — take the last three floats after the last colon.
    cleaned = strip_colors(raw).strip()
    if ":" in cleaned:
        floats = re.findall(r"\d+(?:\.\d+)?", cleaned.rsplit(":", 1)[1])
        if len(floats) >= 3:
            one, five, fifteen = (float(f) for f in floats[-3:])
            return {"tps_1m": one, "tps_5m": five, "tps_15m": fifteen, "raw": cleaned}
    return {"raw": cleaned}


def tail_lines(path: Path, count: int) -> list[str]:
    count = max(1, min(count, MAX_LOG_LINES))
    with path.open(errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=count)]


# ---------------------------------------------------------------- auth & errors


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    user, password = _env("DASH_USER"), _env("DASH_PASS")
    if user and password and request.url.path != "/healthz":
        supplied = request.headers.get("authorization", "")
        ok = False
        if supplied.startswith("Basic "):
            try:
                got_user, _, got_pass = base64.b64decode(supplied[6:]).decode().partition(":")
                user_ok = secrets.compare_digest(got_user, user)
                pass_ok = secrets.compare_digest(got_pass, password)
                ok = user_ok and pass_ok
            except Exception:
                ok = False
        if not ok:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="command-block"'},
            )
    return await call_next(request)


@app.exception_handler(RconError)
async def rcon_error_handler(request: Request, exc: RconError):
    return JSONResponse(status_code=502, content={"error": str(exc)})


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": message})


# ---------------------------------------------------------------- models


class WhitelistChange(BaseModel):
    action: Literal["add", "remove"]
    name: str


class NameReason(BaseModel):
    name: str
    reason: str | None = None


class NameOnly(BaseModel):
    name: str


class Broadcast(BaseModel):
    message: str


class Command(BaseModel):
    command: str


class WaypointChange(BaseModel):
    action: Literal["add", "remove"]
    name: str
    pos: str | None = None
    dim: str | None = None


# ---------------------------------------------------------------- endpoints


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/status")
async def status():
    host = _env("RCON_HOST", "minecraft")
    try:
        s = await JavaServer(host, PING_PORT, timeout=3).async_status(tries=1)
        return {
            "online": True,
            "version": s.version.name,
            "players_online": s.players.online,
            "players_max": s.players.max,
            "motd": s.motd.to_plain().strip(),
            "latency_ms": round(s.latency, 1),
        }
    except Exception:
        return {"online": False}


@app.get("/api/players")
async def players():
    return parse_list(await rcon_command("list"))


@app.get("/api/whitelist")
async def whitelist():
    raw = await rcon_command("whitelist list")
    return {"players": parse_whitelist(raw), "raw": raw}


@app.post("/api/whitelist")
async def whitelist_change(body: WhitelistChange):
    if not _NAME_RE.match(body.name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    return {"raw": await rcon_command(f"whitelist {body.action} {body.name}")}


@app.post("/api/kick")
async def kick(body: NameReason):
    if not _NAME_RE.match(body.name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    cmd = f"kick {body.name}"
    if body.reason:
        cmd += f" {body.reason.strip()}"
    return {"raw": await rcon_command(cmd)}


@app.post("/api/ban")
async def ban(body: NameReason):
    if not _NAME_RE.match(body.name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    cmd = f"ban {body.name}"
    if body.reason:
        cmd += f" {body.reason.strip()}"
    return {"raw": await rcon_command(cmd)}


@app.post("/api/pardon")
async def pardon(body: NameOnly):
    if not _NAME_RE.match(body.name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    return {"raw": await rcon_command(f"pardon {body.name}")}


@app.post("/api/broadcast")
async def broadcast(body: Broadcast):
    message = " ".join(body.message.split())
    if not message:
        return _bad_request("Empty message.")
    return {"raw": await rcon_command(f"say {message}")}


@app.post("/api/save")
async def save():
    return {"raw": await rcon_command("save-all flush")}


@app.post("/api/command")
async def command(body: Command):
    cmd = body.command.strip().lstrip("/")
    if not cmd:
        return _bad_request("Empty command.")
    return {"raw": await rcon_command(cmd)}


@app.post("/api/restart")
async def restart():
    # `stop` saves the world and exits; Docker's unless-stopped policy brings
    # the server back. The connection dropping mid-command is success here.
    raw = await rcon_command("stop", expect_disconnect=True)
    return {"restarting": True, "raw": raw}


@app.get("/api/logs")
async def logs(lines: int = Query(100, ge=1)):
    path = _log_file()
    try:
        return {"lines": tail_lines(path, lines)}
    except OSError:
        return {"lines": [], "error": f"Log file not readable at {path}."}


@app.get("/api/tps")
async def tps():
    return parse_tps(await rcon_command("tps"))


# ---------------------------------------------------------------- waypoints

# Saved teleport targets — the one piece of dashboard state, a small JSON file
# in the cb_data volume (CB_DATA overrides the dir for tests/local runs).
_WP_NAME_RE = re.compile(r"^[A-Za-z0-9 _\-']{1,32}$")
_WP_POS_RE = re.compile(r"^-?\d+(?:\.\d+)? -?\d+(?:\.\d+)? -?\d+(?:\.\d+)?$")
_DIMENSIONS = {"minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"}


def _waypoints_file() -> Path:
    return Path(_env("CB_DATA", "/cb-data")) / "waypoints.json"


def _load_waypoints() -> list[dict]:
    try:
        return json.loads(_waypoints_file().read_text())
    except (OSError, ValueError):
        return []


def _store_waypoints(wps: list[dict]) -> None:
    path = _waypoints_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(wps, indent=2))
    tmp.replace(path)  # atomic on the same filesystem


@app.get("/api/waypoints")
async def waypoints():
    return {"waypoints": _load_waypoints()}


@app.post("/api/waypoints")
async def waypoints_change(body: WaypointChange):
    name = body.name.strip()
    if not _WP_NAME_RE.match(name):
        return _bad_request("Waypoint names: letters, digits, spaces, -_' — max 32.")
    wps = [w for w in _load_waypoints() if w["name"].lower() != name.lower()]
    if body.action == "add":
        pos = " ".join((body.pos or "").split())
        if not _WP_POS_RE.match(pos):
            return _bad_request('Position must be three numbers: "x y z".')
        if body.dim and body.dim not in _DIMENSIONS:
            return _bad_request("Unknown dimension.")
        wps.append({"name": name, "pos": pos, "dim": body.dim})
        wps.sort(key=lambda w: w["name"].lower())
    try:
        _store_waypoints(wps)
    except OSError:
        return JSONResponse(
            status_code=500,
            content={"error": f"Can't write waypoints under {_waypoints_file().parent}."},
        )
    return {"waypoints": wps}


# Live position over RCON (online players only) — lets the UI capture "where
# I'm standing" as a waypoint instead of typing coordinates.
_POS_DATA_RE = re.compile(r"\[(-?[\d.]+)d?, (-?[\d.]+)d?, (-?[\d.]+)d?\]")


@app.get("/api/position/{name}")
async def position(name: str):
    if not _NAME_RE.match(name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    raw = strip_colors(await rcon_command(f"data get entity {name} Pos"))
    m = _POS_DATA_RE.search(raw)
    if not m:  # offline: "No entity was found"
        return JSONResponse(status_code=404, content={"error": raw})
    pos = " ".join(str(round(float(g))) for g in m.groups())
    dim_raw = strip_colors(await rcon_command(f"data get entity {name} Dimension"))
    dim = re.search(r'"(minecraft:[a-z_]+)"', dim_raw)
    return {"pos": pos, "dim": dim.group(1) if dim else None}


# ---------------------------------------------------------------- player stats

# Served from a read-only mount of the minecraft data dir (same spectator
# pattern as the log mount): usercache.json maps names to UUIDs, the world's
# stats/<uuid>.json holds the play-time counter, and playerdata/<uuid>.dat's
# mtime is the last time the server saved that player (logout or autosave).
_PLAY_TIME_KEYS = ("minecraft:play_time", "minecraft:play_one_minute")  # modern / pre-1.17


def _data_dir() -> Path:
    return Path(_env("MC_DATA", "/mc-data"))


def _player_dirs(data: Path) -> tuple[Path, Path] | None:
    """(stats_dir, playerdata_dir) — the world folder name varies, and this MC
    generation moved the files: world/players/{stats,data} instead of the
    classic world/{stats,playerdata}. Support both."""
    try:
        for d in sorted(data.iterdir()):
            if (d / "players").is_dir():
                return d / "players" / "stats", d / "players" / "data"
            if (d / "playerdata").is_dir():
                return d / "stats", d / "playerdata"
    except OSError:
        pass
    return None


@app.get("/api/playerstats")
async def playerstats():
    data = _data_dir()
    try:
        cache = json.loads((data / "usercache.json").read_text())
    except (OSError, ValueError):
        return {"players": {}, "error": f"usercache.json not readable under {data}."}
    dirs = _player_dirs(data)
    players: dict[str, dict] = {}
    for entry in cache:
        name, uuid = entry.get("name"), entry.get("uuid")
        if not name or not uuid or dirs is None:
            continue
        stats_dir, playerdata_dir = dirs
        info: dict = {"last_seen": None, "hours": None}
        try:
            info["last_seen"] = int((playerdata_dir / f"{uuid}.dat").stat().st_mtime)
        except OSError:
            pass
        try:
            stats = json.loads((stats_dir / f"{uuid}.json").read_text())
            custom = stats.get("stats", {}).get("minecraft:custom", {})
            for key in _PLAY_TIME_KEYS:
                if key in custom:
                    info["hours"] = round(custom[key] / 72000, 1)  # 20 ticks/second
                    break
        except (OSError, ValueError):
            pass
        players[name] = info
    return {"players": players}


# ---------------------------------------------------------------- avatars

# The one backend-outbound internet call in the project: player heads for the
# dashboard cards, proxied so the browser still only ever talks to command-block.
# AVATAR_URL env overrides the template; set it empty to disable fetching
# entirely (the frontend falls back to a built-in placeholder face on 404).
AVATAR_DEFAULT_URL = "https://mc-heads.net/avatar/{name}/64"
AVATAR_TTL = 6 * 3600
AVATAR_NEG_TTL = 600  # failed lookups retry after 10 minutes
_avatar_cache: dict[str, tuple[bytes | None, float]] = {}


def fetch_avatar(url: str) -> bytes:
    # module-level (and sync, run via to_thread) so tests can monkeypatch it
    with urllib.request.urlopen(url, timeout=4) as resp:
        return resp.read()


def _avatar_reply(data: bytes | None) -> Response:
    if data is None:
        return JSONResponse(status_code=404, content={"error": "Avatar unavailable."})
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/avatar/{name}")
async def avatar(name: str):
    if not _NAME_RE.match(name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    template = _env("AVATAR_URL", AVATAR_DEFAULT_URL)
    if not template:
        return _avatar_reply(None)
    cached = _avatar_cache.get(name)
    if cached:
        data, fetched_at = cached
        ttl = AVATAR_TTL if data is not None else AVATAR_NEG_TTL
        if time.monotonic() - fetched_at < ttl:
            return _avatar_reply(data)
    try:
        data = await asyncio.to_thread(fetch_avatar, template.format(name=name))
    except Exception:
        data = None
    _avatar_cache[name] = (data, time.monotonic())
    return _avatar_reply(data)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
