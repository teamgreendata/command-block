"""command-block — RCON-shaped admin dashboard for the minecraft stack.

No Docker socket, no database. Everything is RCON plus read-only mounts of
the server's logs and data dir; config comes from the environment only. The
single piece of state is waypoints.json in the cb_data volume.
"""

import asyncio
import base64
import gzip
import json
import os
import re
import secrets
import struct
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

from app import nbt, rcon
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


@app.middleware("http")
async def no_stale_cache(request: Request, call_next):
    # The UI ships new tabs/features often; force revalidation (cheap 304s via
    # ETags) so a stale cached app.js can never mismatch fresh index.html.
    # Endpoints that set their own Cache-Control (avatars) keep it.
    response = await call_next(request)
    if request.method == "GET" and "cache-control" not in response.headers:
        response.headers["cache-control"] = "no-cache"
    return response


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


class Settings(BaseModel):
    card_stats: list[str]


class RecoveryRead(BaseModel):
    player: str
    which: Literal["current", "previous"]


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


# ---------------------------------------------------------------- settings

# Dumb storage next to waypoints.json in the cb_data volume: the frontend's
# stats.js owns the registry keys and the defaults (card_stats: None = unset).
_SETTING_KEY_RE = re.compile(r"^[a-z_]{1,32}$")


def _settings_file() -> Path:
    return Path(_env("CB_DATA", "/cb-data")) / "settings.json"


@app.get("/api/settings")
async def settings():
    try:
        return json.loads(_settings_file().read_text())
    except (OSError, ValueError):
        return {"card_stats": None}


@app.post("/api/settings")
async def settings_change(body: Settings):
    if len(body.card_stats) > 50 or not all(_SETTING_KEY_RE.match(k) for k in body.card_stats):
        return _bad_request("Invalid stat keys.")
    path = _settings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"card_stats": body.card_stats}, indent=2))
        tmp.replace(path)
    except OSError:
        return JSONResponse(
            status_code=500,
            content={"error": f"Can't write settings under {path.parent}."},
        )
    return {"card_stats": body.card_stats}


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


def _world_root(data: Path) -> Path | None:
    # the world folder name varies (level-name) — find it by its player files
    try:
        for d in sorted(data.iterdir()):
            if (d / "players").is_dir() or (d / "playerdata").is_dir():
                return d
    except OSError:
        pass
    return None


def _player_dirs(data: Path) -> tuple[Path, Path] | None:
    """(stats_dir, playerdata_dir) — this MC generation moved the files:
    world/players/{stats,data} instead of the classic world/{stats,playerdata}.
    Support both."""
    world = _world_root(data)
    if world is None:
        return None
    if (world / "players").is_dir():
        return world / "players" / "stats", world / "players" / "data"
    return world / "stats", world / "playerdata"


def _name_uuid_pairs(data: Path) -> list[tuple[str, str]] | None:
    """Merge usercache.json (entries expire ~30 days after a player's last
    join) with whitelist.json (permanent) so long-absent whitelisted players
    keep their lifetime stats. Returns None only if neither file is readable."""
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    found = False
    for fname in ("usercache.json", "whitelist.json"):
        try:
            entries = json.loads((data / fname).read_text())
        except (OSError, ValueError):
            continue
        found = True
        for entry in entries:
            name, uuid = entry.get("name"), entry.get("uuid")
            if name and uuid and name.lower() not in seen:
                seen.add(name.lower())
                pairs.append((name, uuid))
    return pairs if found else None


def _top_entry(section: dict) -> dict | None:
    if not section:
        return None
    entity, count = max(section.items(), key=lambda kv: kv[1])
    return {"id": entity, "count": count}


def _stats_fields(stats: dict) -> dict:
    """Every card stat derivable from one player's stats JSON. The frontend's
    stats.js registry decides which of these actually render."""
    sections = stats.get("stats", {})
    custom = sections.get("minecraft:custom", {})
    mined = sections.get("minecraft:mined", {})
    out: dict = {}
    for key in _PLAY_TIME_KEYS:
        if key in custom:
            out["hours"] = round(custom[key] / 72000, 1)  # 20 ticks/second
            break
    for out_key, stat in (
        ("deaths", "deaths"), ("mob_kills", "mob_kills"), ("player_kills", "player_kills"),
        ("sleep_count", "sleep_in_bed"), ("enchanted", "enchant_item"),
        ("fish_caught", "fish_caught"), ("animals_bred", "animals_bred"),
        ("trades", "traded_with_villager"),
        ("damage_dealt", "damage_dealt"), ("damage_taken", "damage_taken"),  # 10 = 1 heart
    ):
        out[out_key] = custom.get(f"minecraft:{stat}", 0)
    out["life_s"] = custom.get("minecraft:time_since_death", 0) // 20
    out["since_sleep_s"] = custom.get("minecraft:time_since_rest", 0) // 20
    out["aviate_cm"] = custom.get("minecraft:aviate_one_cm", 0)
    out["distance_cm"] = sum(
        v for k, v in custom.items()
        if k.endswith("_one_cm") and k != "minecraft:aviate_one_cm")
    out["mined_total"] = sum(mined.values())
    out["diamonds"] = (mined.get("minecraft:diamond_ore", 0)
                       + mined.get("minecraft:deepslate_diamond_ore", 0))
    out["crafted_total"] = sum(sections.get("minecraft:crafted", {}).values())
    out["nemesis"] = _top_entry(sections.get("minecraft:killed_by", {}))
    out["top_victim"] = _top_entry(sections.get("minecraft:killed", {}))
    return out


@app.get("/api/playerdetail/{name}")
async def playerdetail(name: str):
    """Full raw stat sections for one player — the analytics page's data. The
    frontend (detail.js) does all the breakdown math."""
    if not _NAME_RE.match(name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    data = _data_dir()
    match = next(
        (p for p in (_name_uuid_pairs(data) or []) if p[0].lower() == name.lower()), None)
    if match is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown player {name}."})
    canonical, uuid = match
    dirs = _player_dirs(data)
    if dirs is None:
        return JSONResponse(status_code=404, content={"error": "World data not found."})
    stats_dir, playerdata_dir = dirs
    out: dict = {"name": canonical, "last_seen": None, "sections": {}}
    pdata_path = playerdata_dir / f"{uuid}.dat"
    try:
        out["last_seen"] = int(pdata_path.stat().st_mtime)
    except OSError:
        pass
    try:
        out["sections"] = json.loads((stats_dir / f"{uuid}.json").read_text()).get("stats", {})
    except (OSError, ValueError):
        pass
    raw = _read_nbt_file(pdata_path)
    if raw is not None:
        out["xp_level"] = _nbt_int(raw, b"XpLevel")
        health = _nbt_float(raw, b"Health")
        out["health"] = round(health, 1) if health is not None else None
        out["food"] = _nbt_int(raw, b"foodLevel")
    return out


@app.get("/api/playerstats")
async def playerstats():
    data = _data_dir()
    pairs = _name_uuid_pairs(data)
    if pairs is None:
        return {"players": {},
                "error": f"Neither usercache.json nor whitelist.json readable under {data}."}
    dirs = _player_dirs(data)
    players: dict[str, dict] = {}
    for name, uuid in pairs:
        if dirs is None:
            continue
        stats_dir, playerdata_dir = dirs
        info: dict = {"last_seen": None, "hours": None}
        pdata_path = playerdata_dir / f"{uuid}.dat"
        try:
            info["last_seen"] = int(pdata_path.stat().st_mtime)
        except OSError:
            pass
        try:
            info.update(_stats_fields(json.loads((stats_dir / f"{uuid}.json").read_text())))
        except (OSError, ValueError):
            pass
        raw = _read_nbt_file(pdata_path)  # XP/health/hunger, as of the last save
        if raw is not None:
            info["xp_level"] = _nbt_int(raw, b"XpLevel")
            health = _nbt_float(raw, b"Health")
            info["health"] = round(health, 1) if health is not None else None
            info["food"] = _nbt_int(raw, b"foodLevel")
        players[name] = info
    return {"players": players}


# ---------------------------------------------------------------- world clock & info

# This MC generation gutted level.dat: weather lives in the overworld's
# dimensions/.../data/minecraft/weather.dat and cumulative day ticks in the
# world's data/minecraft/world_clocks.dat (both NBT, updated on save). The
# live time of day comes from RCON `time query day` — the new timeline system
# ("Timeline minecraft:day is at N tick(s)", wrapping at 24000).
_TICKS_PER_DAY = 24000
_DAY_TICK_RE = re.compile(r"is at (\d+) tick")
_INT_RE = re.compile(r"-?\d+")


def _nbt_byte(raw: bytes, name: bytes) -> int | None:
    pat = b"\x01" + len(name).to_bytes(2, "big") + name
    i = raw.find(pat)
    return raw[i + len(pat)] if i >= 0 else None


def _nbt_int(raw: bytes, name: bytes) -> int | None:
    pat = b"\x03" + len(name).to_bytes(2, "big") + name
    i = raw.find(pat)
    if i < 0:
        return None
    j = i + len(pat)
    return int.from_bytes(raw[j:j + 4], "big", signed=True)


def _nbt_float(raw: bytes, name: bytes) -> float | None:
    pat = b"\x05" + len(name).to_bytes(2, "big") + name
    i = raw.find(pat)
    if i < 0:
        return None
    j = i + len(pat)
    return struct.unpack(">f", raw[j:j + 4])[0]


def _nbt_long_after(raw: bytes, anchor: bytes, name: bytes) -> int | None:
    start = raw.find(anchor)
    if start < 0:
        return None
    pat = b"\x04" + len(name).to_bytes(2, "big") + name
    i = raw.find(pat, start)
    if i < 0:
        return None
    j = i + len(pat)
    return int.from_bytes(raw[j:j + 8], "big", signed=True)


def _read_nbt_file(path: Path) -> bytes | None:
    try:
        return gzip.decompress(path.read_bytes())
    except (OSError, gzip.BadGzipFile, EOFError):
        return None


def _read_weather(data: Path) -> str | None:
    world = _world_root(data)
    if world is None:
        return None
    raw = _read_nbt_file(
        world / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft" / "weather.dat")
    if raw is None:
        return None
    if _nbt_byte(raw, b"thundering"):
        return "thunder"
    if _nbt_byte(raw, b"raining"):
        return "rain"
    return "clear"


def _read_day(data: Path) -> int | None:
    world = _world_root(data)
    if world is None:
        return None
    # the overworld's own data file is the live one; the world-level
    # world_clocks.dat exists but stays at 0 on Paper 26.2
    candidates = (
        world / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft" / "world_clocks.dat",
        world / "data" / "minecraft" / "world_clocks.dat",
    )
    for path in candidates:
        raw = _read_nbt_file(path)
        if raw is None:
            continue
        total = _nbt_long_after(raw, b"minecraft:overworld", b"total_ticks")
        if total is not None:
            return total // _TICKS_PER_DAY + 1
    return None


def clock_from_tick(t: int) -> dict:
    # tick 0 = 06:00; beds work 12542–23459, call that night
    hours = (6 + t / 1000) % 24
    return {
        "clock": f"{int(hours):02d}:{int(hours % 1 * 60):02d}",
        "phase": "night" if 12542 <= t < 23459 else "day",
    }


@app.get("/api/clock")
async def clock():
    data = _data_dir()
    out: dict = {"online": False, "weather": _read_weather(data), "day": _read_day(data)}
    try:
        raw = strip_colors(await rcon_command("time query day"))
        m = _DAY_TICK_RE.search(raw)
        if m:
            tick = int(m.group(1)) % _TICKS_PER_DAY
            out.update(clock_from_tick(tick), online=True, daytick=tick)
    except RconError:
        pass
    return out


def parse_mspt(raw: str) -> dict:
    # "Server tick times (avg/min/max) from last 5s, 10s, 1m: a/b/c, a/b/c, a/b/c"
    cleaned = strip_colors(raw)
    if ":" not in cleaned:
        return {}
    floats = re.findall(r"\d+(?:\.\d+)?", cleaned.rsplit(":", 1)[1])
    if len(floats) < 9:
        return {}
    avg, low, high = (float(f) for f in floats[-3:])  # the 1m figures
    return {"avg": avg, "min": low, "max": high}


def _server_props(data: Path) -> dict:
    try:
        lines = (data / "server.properties").read_text().splitlines()
    except OSError:
        return {}
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


_world_size_cache: tuple[float, int] | None = None


def _world_size(data: Path) -> int | None:
    global _world_size_cache
    if _world_size_cache and time.monotonic() - _world_size_cache[0] < 300:
        return _world_size_cache[1]
    world = _world_root(data)
    if world is None:
        return None
    total = 0
    for p in world.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    _world_size_cache = (time.monotonic(), total)
    return total


@app.get("/api/serverinfo")
async def serverinfo():
    data = _data_dir()
    out: dict = {"online": False}

    async def query(cmd: str) -> str | None:
        try:
            raw = strip_colors(await rcon_command(cmd))
            out["online"] = True
            return raw
        except RconError:
            return None

    if (r := await query("difficulty")) and (m := re.search(r"difficulty is (\w+)", r)):
        out["difficulty"] = m.group(1)
    if (r := await query("seed")) and (m := re.search(r"\[(-?\d+)\]", r)):
        out["seed"] = m.group(1)
    if r := await query("mspt"):
        mspt = parse_mspt(r)
        if mspt:
            out["mspt"] = mspt
    if r := await query("banlist"):
        out["bans"] = 0 if "no ban" in r.lower() else \
            int(m.group()) if (m := _INT_RE.search(r)) else 0
    if r := await query("whitelist list"):
        out["whitelisted"] = len(parse_whitelist(r))

    props = _server_props(data)
    for key, out_key in (("view-distance", "view_distance"),
                         ("simulation-distance", "simulation_distance"),
                         ("max-players", "max_players")):
        if key in props:
            out[out_key] = props[key]
    world = _world_root(data)
    if world is not None:
        try:  # session.lock is (re)written when the server locks the world at boot
            out["uptime_s"] = max(0, int(time.time() - (world / "session.lock").stat().st_mtime))
        except OSError:
            pass
    size = _world_size(data)
    if size is not None:
        out["world_size_mb"] = round(size / 1e6, 1)
    out["day"] = _read_day(data)
    return out


# ---------------------------------------------------------------- gear recovery

# Reads an inventory out of a playerdata .dat (the live one, the previous
# save, or an uploaded backup) and turns each item into a give-ready string —
# components (enchantments, names, …) round-trip verbatim through app.nbt.
# Strictly read-only on world files; the actual gives go through /api/command.


def _inventory_items(root: dict) -> list[dict]:
    items = []
    for item in root.get("Inventory", []):
        if not isinstance(item, dict) or "id" not in item:
            continue
        slot = int(item.get("Slot", 0))
        comps = item.get("components", {})
        item_part = str(item["id"])
        if comps:
            item_part += "[" + ",".join(f"{k}={nbt.snbt(v)}" for k, v in comps.items()) + "]"
        count = int(item.get("count", 1))
        if count > 1:
            item_part += f" {count}"
        ench = comps.get("minecraft:enchantments", {})
        if isinstance(ench, dict) and isinstance(ench.get("levels"), dict):
            ench = ench["levels"]  # older component layout
        enchants = ([f"{k.split(':')[-1].replace('_', ' ')} {int(v)}" for k, v in ench.items()]
                    if isinstance(ench, dict) else [])
        where = ("armor" if 100 <= slot <= 103 else
                 "offhand" if slot == -106 else
                 "hotbar" if 0 <= slot <= 8 else "inventory")
        items.append({"slot": slot, "where": where, "id": item["id"], "count": count,
                      "enchants": enchants, "components": len(comps), "item_part": item_part})
    order = {"armor": 0, "offhand": 1, "hotbar": 2, "inventory": 3}
    items.sort(key=lambda i: (order[i["where"]], i["slot"]))
    return items


def _parse_recovery(blob: bytes):
    try:
        root = nbt.parse(blob)
        items = _inventory_items(root)
    except (ValueError, TypeError, KeyError):
        return _bad_request("That file doesn't parse as playerdata NBT.")
    return {"items": items, "xp_level": root.get("XpLevel")}


@app.get("/api/recovery/sources")
async def recovery_sources():
    data = _data_dir()
    dirs = _player_dirs(data)
    sources = []
    if dirs is not None:
        playerdata_dir = dirs[1]
        for name, uuid in (_name_uuid_pairs(data) or []):
            for which, suffix in (("current", ".dat"), ("previous", ".dat_old")):
                try:
                    st = (playerdata_dir / f"{uuid}{suffix}").stat()
                except OSError:
                    continue
                sources.append({"player": name, "which": which,
                                "mtime": int(st.st_mtime), "size": st.st_size})
    return {"sources": sources}


@app.post("/api/recovery/read")
async def recovery_read(body: RecoveryRead):
    if not _NAME_RE.match(body.player):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    data = _data_dir()
    match = next(
        (p for p in (_name_uuid_pairs(data) or []) if p[0].lower() == body.player.lower()), None)
    dirs = _player_dirs(data)
    if match is None or dirs is None:
        return JSONResponse(status_code=404, content={"error": "Unknown player or no world data."})
    suffix = ".dat" if body.which == "current" else ".dat_old"
    try:
        blob = (dirs[1] / f"{match[1]}{suffix}").read_bytes()
    except OSError:
        return JSONResponse(status_code=404, content={"error": f"No {body.which} save found."})
    return _parse_recovery(blob)


@app.post("/api/recovery/upload")
async def recovery_upload(request: Request):
    blob = await request.body()
    if not blob:
        return _bad_request("Empty upload.")
    if len(blob) > 5_000_000:
        return _bad_request("File too large (5 MB max).")
    return _parse_recovery(blob)


# ---------------------------------------------------------------- avatars

# The one backend-outbound internet call in the project: player heads for the
# dashboard cards, proxied so the browser still only ever talks to command-block.
# AVATAR_URL env overrides the template; set it empty to disable fetching
# entirely (the frontend falls back to a built-in placeholder face on 404).
AVATAR_DEFAULT_URL = "https://mc-heads.net/avatar/{name}/64"
AVATAR_BODY_DEFAULT_URL = "https://mc-heads.net/body/{name}/100"  # 100x240 full render
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
async def avatar(name: str, full: bool = False):
    if not _NAME_RE.match(name):
        return _bad_request("Invalid player name (letters, digits, underscore; max 16).")
    # AVATAR_URL= (empty) is the kill switch for ALL avatar fetching
    template = _env("AVATAR_URL", AVATAR_DEFAULT_URL)
    if not template:
        return _avatar_reply(None)
    if full:
        template = _env("AVATAR_BODY_URL", AVATAR_BODY_DEFAULT_URL)
    key = f"body:{name}" if full else name
    cached = _avatar_cache.get(key)
    if cached:
        data, fetched_at = cached
        ttl = AVATAR_TTL if data is not None else AVATAR_NEG_TTL
        if time.monotonic() - fetched_at < ttl:
            return _avatar_reply(data)
    try:
        data = await asyncio.to_thread(fetch_avatar, template.format(name=name))
    except Exception:
        data = None
    _avatar_cache[key] = (data, time.monotonic())
    return _avatar_reply(data)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
