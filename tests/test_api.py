import base64
import gzip
import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.rcon import RconError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("DASH_USER", raising=False)
    monkeypatch.delenv("DASH_PASS", raising=False)
    return TestClient(app)


@pytest.fixture
def rcon_calls(monkeypatch):
    calls = []

    async def fake(command, *, expect_disconnect=False):
        calls.append((command, expect_disconnect))
        return "raw response"

    monkeypatch.setattr(main, "rcon_command", fake)
    return calls


def _basic(user, password):
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_command_strips_leading_slash(client, rcon_calls):
    r = client.post("/api/command", json={"command": "/whitelist reload"})
    assert r.status_code == 200
    assert rcon_calls == [("whitelist reload", False)]
    assert r.json()["raw"] == "raw response"


def test_empty_command_rejected(client, rcon_calls):
    r = client.post("/api/command", json={"command": "  / "})
    assert r.status_code == 400
    assert rcon_calls == []


def test_restart_sends_stop_expecting_disconnect(client, rcon_calls):
    r = client.post("/api/restart")
    assert r.status_code == 200
    assert r.json()["restarting"] is True
    assert rcon_calls == [("stop", True)]


def test_invalid_player_name_rejected(client, rcon_calls):
    for path, body in [
        ("/api/kick", {"name": "bad name; op me"}),
        ("/api/ban", {"name": "x" * 17}),
        ("/api/pardon", {"name": "sneaky\nstop"}),
        ("/api/whitelist", {"action": "add", "name": "not/valid"}),
    ]:
        r = client.post(path, json=body)
        assert r.status_code == 400, path
    assert rcon_calls == []


def test_kick_with_reason(client, rcon_calls):
    r = client.post("/api/kick", json={"name": "griefer_99", "reason": "be nice"})
    assert r.status_code == 200
    assert rcon_calls == [("kick griefer_99 be nice", False)]


def test_whitelist_get_parses_names(client, monkeypatch):
    async def fake(command, *, expect_disconnect=False):
        return "There are 2 whitelisted player(s): alice, bob"

    monkeypatch.setattr(main, "rcon_command", fake)
    r = client.get("/api/whitelist")
    assert r.json()["players"] == ["alice", "bob"]


def test_rcon_failure_is_clean_json_502(client, monkeypatch):
    async def fake(command, *, expect_disconnect=False):
        raise RconError("Can't reach RCON at minecraft:25575 — is the Minecraft server up?")

    monkeypatch.setattr(main, "rcon_command", fake)
    r = client.get("/api/players")
    assert r.status_code == 502
    assert "reach RCON" in r.json()["error"]


def test_status_offline_is_graceful(client, monkeypatch):
    class FakeServer:
        def __init__(self, *a, **kw):
            pass

        async def async_status(self, **kw):
            raise ConnectionRefusedError()

    monkeypatch.setattr(main, "JavaServer", FakeServer)
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json() == {"online": False}


def test_logs_reads_mounted_file(client, monkeypatch, tmp_path):
    log = tmp_path / "latest.log"
    log.write_text("one\ntwo\nthree\n")
    monkeypatch.setenv("LOG_FILE", str(log))
    r = client.get("/api/logs?lines=2")
    assert r.json() == {"lines": ["two", "three"]}


def test_logs_missing_file_is_graceful(client, monkeypatch, tmp_path):
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "gone.log"))
    r = client.get("/api/logs")
    assert r.status_code == 200
    assert r.json()["lines"] == []
    assert "error" in r.json()


def test_auth_disabled_when_env_unset(client, rcon_calls):
    assert client.get("/api/players").status_code == 200


def test_auth_enforced_when_env_set(monkeypatch, rcon_calls):
    monkeypatch.setenv("DASH_USER", "rob")
    monkeypatch.setenv("DASH_PASS", "hunter2")
    c = TestClient(app)
    assert c.get("/api/players").status_code == 401
    assert c.get("/api/players", headers=_basic("rob", "wrong")).status_code == 401
    assert c.get("/api/players", headers=_basic("rob", "hunter2")).status_code == 200
    # /healthz stays open for Uptime Kuma
    assert c.get("/healthz").status_code == 200


def test_broadcast_flattens_whitespace(client, rcon_calls):
    r = client.post("/api/broadcast", json={"message": "hello\neveryone   there"})
    assert r.status_code == 200
    assert rcon_calls == [("say hello everyone there", False)]


def test_tps_endpoint_parses(client, monkeypatch):
    async def fake(command, *, expect_disconnect=False):
        return "§6TPS from last 1m, 5m, 15m: §a20.0, 20.0, 20.0"

    monkeypatch.setattr(main, "rcon_command", fake)
    r = client.get("/api/tps")
    assert r.json()["tps_1m"] == 20.0


@pytest.fixture
def avatar_fetches(monkeypatch):
    main._avatar_cache.clear()
    calls = []

    def fake(url):
        calls.append(url)
        return b"png-bytes"

    monkeypatch.setattr(main, "fetch_avatar", fake)
    monkeypatch.delenv("AVATAR_URL", raising=False)
    yield calls
    main._avatar_cache.clear()


def test_avatar_proxies_and_caches(client, avatar_fetches):
    r = client.get("/api/avatar/alice")
    assert r.status_code == 200
    assert r.content == b"png-bytes"
    assert r.headers["content-type"] == "image/png"
    assert "max-age" in r.headers["cache-control"]
    client.get("/api/avatar/alice")  # second hit comes from the cache
    assert avatar_fetches == ["https://mc-heads.net/avatar/alice/64"]


def test_avatar_rejects_bad_names(client, avatar_fetches):
    assert client.get("/api/avatar/bad%20name").status_code == 400
    assert client.get("/api/avatar/" + "x" * 17).status_code == 400
    assert avatar_fetches == []


def test_avatar_failure_is_404_and_negative_cached(client, monkeypatch):
    main._avatar_cache.clear()
    monkeypatch.delenv("AVATAR_URL", raising=False)
    calls = []

    def boom(url):
        calls.append(url)
        raise OSError("no internet")

    monkeypatch.setattr(main, "fetch_avatar", boom)
    assert client.get("/api/avatar/alice").status_code == 404
    assert client.get("/api/avatar/alice").status_code == 404
    assert len(calls) == 1  # failures are negative-cached, not hammered
    main._avatar_cache.clear()


def test_avatar_disabled_via_empty_env(client, monkeypatch, avatar_fetches):
    monkeypatch.setenv("AVATAR_URL", "")
    assert client.get("/api/avatar/alice").status_code == 404
    assert avatar_fetches == []


UUID_A = "11111111-2222-3333-4444-555555555555"
UUID_B = "66666666-7777-8888-9999-000000000000"

# Byte-for-byte from a live Paper 26.2 world: raining=1, thundering=0, and
# world_clocks with overworld total_ticks=0x698e (27022 -> day 2).
WEATHER_NBT = (
    b"\n\x00\x00\x03\x00\x0bDataVersion\x00\x00\x13'\n\x00\x04data"
    b"\x03\x00\x0cthunder_time\x00\x00A\xca\x01\x00\nthundering\x00"
    b"\x03\x00\x09rain_time\x00\x00A\xca\x01\x00\x07raining\x01"
    b"\x03\x00\x12clear_weather_time\x00\x00\x00\x00\x00\x00"
)
CLOCKS_NBT = (
    b"\n\x00\x00\x03\x00\x0bDataVersion\x00\x00\x13'\n\x00\x04data"
    b"\n\x00\x13minecraft:overworld\x04\x00\x0btotal_ticks\x00\x00\x00\x00\x00\x00i\x8e\x00"
    b"\n\x00\x11minecraft:the_end\x04\x00\x0btotal_ticks\x00\x00\x00\x00\x00\x00\x0b\xce\x00\x00\x00"
)


@pytest.fixture
def world_files(tmp_path, monkeypatch):
    """A modern-layout world with weather, clocks, session.lock, properties."""
    monkeypatch.setenv("MC_DATA", str(tmp_path))
    main._world_size_cache = None
    world = tmp_path / "world"
    (world / "players" / "data").mkdir(parents=True)
    ow_data = world / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft"
    ow_data.mkdir(parents=True)
    (ow_data / "weather.dat").write_bytes(gzip.compress(WEATHER_NBT))
    # live clocks are per-dimension; the world-level file stays at 0 (decoy)
    (ow_data / "world_clocks.dat").write_bytes(gzip.compress(CLOCKS_NBT))
    (world / "session.lock").write_bytes(b"\xe2\x98\x83")
    (world / "region").mkdir()
    (world / "region" / "r.0.0.mca").write_bytes(b"\x00" * 1_500_000)
    (tmp_path / "server.properties").write_text(
        "#comment\nview-distance=10\nsimulation-distance=8\nmax-players=20\nmotd=A=B\n")
    return tmp_path


def test_clock_reads_timeline_weather_and_day(client, world_files, monkeypatch):
    async def fake(command, *, expect_disconnect=False):
        return "Timeline minecraft:day is at 6212 tick(s)"

    monkeypatch.setattr(main, "rcon_command", fake)
    c = client.get("/api/clock").json()
    assert c["online"] is True
    assert c["clock"] == "12:12"  # tick 0 = 06:00
    assert c["phase"] == "day"
    assert c["weather"] == "rain"
    assert c["day"] == 2  # 27022 total ticks


def test_clock_night_and_rcon_down(client, world_files, monkeypatch):
    async def fake(command, *, expect_disconnect=False):
        return "Timeline minecraft:day is at 18000 tick(s)"

    monkeypatch.setattr(main, "rcon_command", fake)
    c = client.get("/api/clock").json()
    assert (c["clock"], c["phase"]) == ("00:00", "night")

    async def down(command, *, expect_disconnect=False):
        raise RconError("down")

    monkeypatch.setattr(main, "rcon_command", down)
    c = client.get("/api/clock").json()
    assert c["online"] is False
    assert c["weather"] == "rain"  # file-based facts survive RCON being down


def test_serverinfo_combines_rcon_and_files(client, world_files, monkeypatch):
    responses = {
        "difficulty": "The difficulty is Hard",
        "seed": "Seed: [8349692590103972803]",
        "mspt": "Server tick times (avg/min/max) from last 5s, 10s, 1m: "
                "0.9/0.3/21.5, 0.9/0.3/21.5, 1.3/0.3/22.2",
        "banlist": "There are no bans",
        "whitelist list": "There are 2 whitelisted player(s): alice, bob",
    }

    async def fake(command, *, expect_disconnect=False):
        return responses[command]

    monkeypatch.setattr(main, "rcon_command", fake)
    s = client.get("/api/serverinfo").json()
    assert s["online"] is True
    assert s["difficulty"] == "Hard"
    assert s["seed"] == "8349692590103972803"
    assert s["mspt"] == {"avg": 1.3, "min": 0.3, "max": 22.2}  # the 1m figures
    assert s["bans"] == 0
    assert s["whitelisted"] == 2
    assert s["view_distance"] == "10"
    assert s["simulation_distance"] == "8"
    assert 0 <= s["uptime_s"] < 10  # session.lock just written
    assert s["world_size_mb"] == 1.5
    assert s["day"] == 2


def test_avatar_full_body_cached_separately(client, avatar_fetches):
    client.get("/api/avatar/alice")
    client.get("/api/avatar/alice?full=1")
    client.get("/api/avatar/alice?full=1")  # cache hit
    assert avatar_fetches == [
        "https://mc-heads.net/avatar/alice/64",
        "https://mc-heads.net/body/alice/100",
    ]


@pytest.fixture
def mc_data(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_DATA", str(tmp_path))
    world = tmp_path / "world"  # any dir name works — found via playerdata/
    (world / "playerdata").mkdir(parents=True)
    (world / "stats").mkdir()
    (tmp_path / "usercache.json").write_text(json.dumps([
        {"name": "alice", "uuid": UUID_A, "expiresOn": "2026-09-01 00:00:00 +0000"},
        {"name": "bob", "uuid": UUID_B, "expiresOn": "2026-09-01 00:00:00 +0000"},
    ]))
    (world / "stats" / f"{UUID_A}.json").write_text(json.dumps(
        {"stats": {"minecraft:custom": {"minecraft:play_time": 144000}}}))  # 2h of ticks
    (world / "playerdata" / f"{UUID_A}.dat").write_bytes(b"")
    return tmp_path


def test_playerstats_reads_world_files(client, mc_data):
    r = client.get("/api/playerstats")
    assert r.status_code == 200
    alice = r.json()["players"]["alice"]
    assert alice["hours"] == 2.0
    assert isinstance(alice["last_seen"], int)  # playerdata mtime
    # bob is in usercache but has no world files yet — present, empty stats
    assert r.json()["players"]["bob"] == {"last_seen": None, "hours": None}


def test_playerstats_supports_legacy_play_time_key(client, mc_data):
    (mc_data / "world" / "stats" / f"{UUID_B}.json").write_text(json.dumps(
        {"stats": {"minecraft:custom": {"minecraft:play_one_minute": 72000}}}))
    r = client.get("/api/playerstats")
    assert r.json()["players"]["bob"]["hours"] == 1.0


def test_playerstats_whitelist_json_covers_expired_usercache(client, mc_data):
    # usercache entries expire ~30 days after last join; whitelist.json never
    # does — a whitelisted player absent from usercache must still get stats
    uuid_c = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    (mc_data / "whitelist.json").write_text(json.dumps([{"uuid": uuid_c, "name": "carol"}]))
    (mc_data / "world" / "stats" / f"{uuid_c}.json").write_text(json.dumps(
        {"stats": {"minecraft:custom": {"minecraft:play_time": 720000}}}))  # 10h lifetime
    r = client.get("/api/playerstats")
    assert r.json()["players"]["carol"]["hours"] == 10.0
    assert r.json()["players"]["alice"]["hours"] == 2.0  # usercache entries still work


def test_playerstats_modern_players_layout(client, tmp_path, monkeypatch):
    # this MC generation nests everything under world/players/{data,stats}
    # (verified against a live Paper 26.2 world) — the classic layout in the
    # mc_data fixture is world/{playerdata,stats}
    monkeypatch.setenv("MC_DATA", str(tmp_path))
    players_dir = tmp_path / "world" / "players"
    (players_dir / "data").mkdir(parents=True)
    (players_dir / "stats").mkdir()
    (tmp_path / "usercache.json").write_text(json.dumps([{"name": "alice", "uuid": UUID_A}]))
    (players_dir / "stats" / f"{UUID_A}.json").write_text(json.dumps(
        {"stats": {"minecraft:custom": {"minecraft:play_time": 36000}}}))  # half an hour
    (players_dir / "data" / f"{UUID_A}.dat").write_bytes(b"")
    r = client.get("/api/playerstats")
    alice = r.json()["players"]["alice"]
    assert alice["hours"] == 0.5
    assert isinstance(alice["last_seen"], int)


def test_playerstats_missing_mount_is_graceful(client, monkeypatch, tmp_path):
    monkeypatch.setenv("MC_DATA", str(tmp_path / "nope"))
    r = client.get("/api/playerstats")
    assert r.status_code == 200
    assert r.json()["players"] == {}
    assert "error" in r.json()


@pytest.fixture
def wp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CB_DATA", str(tmp_path))
    return tmp_path


def test_waypoints_roundtrip(client, wp_dir):
    assert client.get("/api/waypoints").json() == {"waypoints": []}
    r = client.post("/api/waypoints", json={
        "action": "add", "name": "Home base", "pos": "100 64 -200",
        "dim": "minecraft:overworld"})
    assert r.status_code == 200
    r = client.post("/api/waypoints", json={"action": "add", "name": "cave", "pos": "-10.5 12 900"})
    assert [w["name"] for w in r.json()["waypoints"]] == ["cave", "Home base"]
    # re-adding the same name (any case) replaces it
    r = client.post("/api/waypoints", json={"action": "add", "name": "home BASE", "pos": "1 2 3"})
    assert [(w["name"], w["pos"]) for w in r.json()["waypoints"]] == [
        ("cave", "-10.5 12 900"), ("home BASE", "1 2 3")]
    r = client.post("/api/waypoints", json={"action": "remove", "name": "cave"})
    assert [w["name"] for w in r.json()["waypoints"]] == ["home BASE"]
    # state survives a container restart: it's a real file
    assert json.loads((wp_dir / "waypoints.json").read_text())[0]["name"] == "home BASE"


def test_waypoints_validation(client, wp_dir):
    bad = [
        {"action": "add", "name": "x" * 33, "pos": "1 2 3"},
        {"action": "add", "name": "no; injection", "pos": "1 2 3"},
        {"action": "add", "name": "ok", "pos": "1 2"},
        {"action": "add", "name": "ok", "pos": "1 2 three"},
        {"action": "add", "name": "ok", "pos": "1 2 3", "dim": "minecraft:moon"},
    ]
    for body in bad:
        assert client.post("/api/waypoints", json=body).status_code == 400, body
    assert client.get("/api/waypoints").json()["waypoints"] == []


def test_position_grabs_online_player(client, monkeypatch):
    async def fake(command, *, expect_disconnect=False):
        if command.endswith("Pos"):
            return "RobGreen has the following entity data: [186.61d, 63.0d, -14.36d]"
        return 'RobGreen has the following entity data: "minecraft:the_nether"'

    monkeypatch.setattr(main, "rcon_command", fake)
    r = client.get("/api/position/RobGreen")
    assert r.json() == {"pos": "187 63 -14", "dim": "minecraft:the_nether"}


def test_position_offline_player_is_404(client, monkeypatch):
    async def fake(command, *, expect_disconnect=False):
        return "No entity was found"

    monkeypatch.setattr(main, "rcon_command", fake)
    assert client.get("/api/position/ghost").status_code == 404
