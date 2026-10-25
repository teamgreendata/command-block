import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app import bluemap
from app import storage as storage_mod
from app.main import app

TILE = b"\x01\x02prbm-bytes" * 20


class FakeBlueMap(BaseHTTPRequestHandler):
    hits: list = []

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeBlueMap.hits.append((self.path, dict(self.headers)))
        if self.path == "/":
            self._send(200, b"<html>bluemap</html>", {"Content-Type": "text/html"})
        elif self.path == "/settings.json":
            self._send(200, b'{"maps":["world"]}', {"Content-Type": "application/json"})
        elif self.path.startswith("/maps/world/tiles/0/x0/z0.prbm"):
            if self.headers.get("If-None-Match") == '"t1"':
                self._send(304, headers={"ETag": '"t1"'})
            elif "gzip" in self.headers.get("Accept-Encoding", ""):
                self._send(200, gzip.compress(TILE), {
                    "Content-Type": "application/octet-stream", "Content-Encoding": "gzip",
                    "ETag": '"t1"', "Cache-Control": "public, max-age=86400",
                    "X-Internal": "drop-me"})
            else:
                self._send(200, TILE, {"Content-Type": "application/octet-stream"})
        elif self.path == "/maps/world":
            self._send(303, headers={"Location": "/maps/world/"})
        elif self.path == "/maps/world/live/markers.json":
            body = json.dumps({"bm-own": {"label": "Plugin set", "markers": {}},
                               bluemap.WAYPOINT_SET: {"label": "stale", "markers": {}}})
            self._send(200, body.encode(), {"Content-Type": "application/json"})
        else:
            self._send(404)


@pytest.fixture
def upstream():
    FakeBlueMap.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBlueMap)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def bm(monkeypatch, upstream, tmp_path):
    monkeypatch.delenv("DASH_USER", raising=False)
    monkeypatch.delenv("DASH_PASS", raising=False)
    monkeypatch.setenv("BLUEMAP_URL", upstream + "/")
    monkeypatch.setenv("CB_DATA", str(tmp_path))
    storage_mod.scan_state.clear()
    storage_mod.scan_state["state"] = "idle"
    return TestClient(app)


# ------------------------------------------------------------ pure helpers

def test_safe_path_refuses_climbing_out():
    assert bluemap.safe_path("") == ""
    assert bluemap.safe_path("maps/world/tiles/0/x-1/z2.prbm") == "maps/world/tiles/0/x-1/z2.prbm"
    assert bluemap.safe_path("assets/a b.png") == "assets/a%20b.png"
    for bad in ("../secret", "maps/../../etc", "/abs", "maps/./x", "a\\b", "a\0b"):
        assert bluemap.safe_path(bad) is None, bad


def test_dim_for_map_handles_both_world_layouts():
    assert bluemap.dim_for_map("world") == "overworld"
    assert bluemap.dim_for_map("world_the_nether") == "the_nether"
    assert bluemap.dim_for_map("world_nether") == "the_nether"
    assert bluemap.dim_for_map("world_the_end") == "the_end"
    assert bluemap.dim_for_map("end") == "the_end"
    assert bluemap.dim_for_map("legend_world") == "overworld"


def test_marker_sets_filter_by_dimension_and_escape():
    wps = [{"name": "Main Storage", "pos": "10 64 -20", "dim": None},
           {"name": "Nether hub", "pos": "1 70 1", "dim": "minecraft:the_nether"},
           {"name": "Rob's <b>base", "pos": "5.5 80 5", "dim": "minecraft:overworld"},
           {"name": "Broken", "pos": "not a pos", "dim": None}]
    structures = [
        {"key": "overworld:village:1:1", "type": "village", "dim": "overworld",
         "x": 24, "z": 24, "y": 70, "by": "TeamGreenRob", "at": 1760000000},
        {"key": "overworld:stronghold:5:5", "type": "stronghold", "dim": "overworld",
         "x": 88, "z": 88, "by": "RaRaShiskumba", "at": None, "backfilled": True},
        {"key": "the_nether:fortress:2:2", "type": "fortress", "dim": "the_nether",
         "x": 40, "z": 40, "y": 60, "by": "TeamGreenRob", "at": 1},
    ]
    sets = bluemap.marker_sets("overworld", wps, structures)
    wp = sets[bluemap.WAYPOINT_SET]["markers"]
    assert set(wp) == {"wp:main storage", "wp:rob's <b>base"}  # nether + broken skipped
    main_storage = wp["wp:main storage"]
    assert main_storage["type"] == "poi"
    assert main_storage["position"] == {"x": 10.0, "y": 64.0, "z": -20.0}
    assert main_storage["classes"] == []  # BlueMap spreads this list; must exist
    assert main_storage["icon"].startswith("data:image/svg+xml,")
    assert "&lt;b&gt;" in wp["wp:rob's <b>base"]["detail"]  # never raw HTML
    found = sets[bluemap.STRUCTURE_SET]["markers"]
    assert set(found) == {"overworld:village:1:1", "overworld:stronghold:5:5"}
    assert found["overworld:village:1:1"]["position"]["y"] == 70
    assert found["overworld:stronghold:5:5"]["position"]["y"] == 64  # unknown → default
    assert "(from advancements)" in found["overworld:stronghold:5:5"]["detail"]
    assert "found by TeamGreenRob · " in found["overworld:village:1:1"]["detail"]
    # a dimension with nothing in it adds no empty toggles to BlueMap's menu
    assert bluemap.marker_sets("the_end", wps, structures) == {}


def test_merge_keeps_plugin_sets_and_replaces_ours():
    upstream = {"bm-own": {"label": "x"}, bluemap.WAYPOINT_SET: {"label": "stale"}}
    merged = bluemap.merge_markers(upstream, {bluemap.WAYPOINT_SET: {"label": "fresh"}})
    assert merged == {"bm-own": {"label": "x"}, bluemap.WAYPOINT_SET: {"label": "fresh"}}
    assert bluemap.WAYPOINT_SET not in bluemap.merge_markers(upstream, {})


# ------------------------------------------------------------ proxy endpoints

def test_unconfigured_bluemap_is_off(monkeypatch):
    monkeypatch.delenv("BLUEMAP_URL", raising=False)
    monkeypatch.delenv("DASH_USER", raising=False)
    monkeypatch.delenv("DASH_PASS", raising=False)
    c = TestClient(app)
    assert c.get("/api/map/config").json() == {"bluemap": False}
    assert c.get("/bluemap/settings.json").status_code == 404


def test_proxy_serves_the_app_and_passes_compression_through(bm):
    assert bm.get("/api/map/config").json() == {"bluemap": True}
    root = bm.get("/bluemap", follow_redirects=False)
    assert root.status_code == 307 and root.headers["location"] == "/bluemap/"
    assert bm.get("/bluemap/").text == "<html>bluemap</html>"
    r = bm.get("/bluemap/maps/world/tiles/0/x0/z0.prbm?123")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"  # forwarded, not re-encoded
    assert r.content == TILE                         # client decodes it
    assert r.headers["cache-control"] == "public, max-age=86400"
    assert "x-internal" not in r.headers
    path, headers = FakeBlueMap.hits[-1]
    assert path == "/maps/world/tiles/0/x0/z0.prbm?123"
    assert "gzip" in headers.get("Accept-Encoding", "")


def test_proxy_forwards_304_and_hands_redirects_back(bm):
    r = bm.get("/bluemap/maps/world/tiles/0/x0/z0.prbm", headers={"If-None-Match": '"t1"'})
    assert r.status_code == 304
    r = bm.get("/bluemap/maps/world", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/bluemap/maps/world/"


def test_proxy_refuses_sse_and_traversal(bm):
    assert bm.get("/bluemap/maps/world/live/sse").status_code == 204
    assert bm.get("/bluemap/maps/%2e%2e/%2e%2e/etc/passwd").status_code == 400
    assert all("sse" not in p and ".." not in p for p, _ in FakeBlueMap.hits)


def test_markers_json_gets_waypoints_and_discoveries(bm, tmp_path):
    (tmp_path / "waypoints.json").write_text(json.dumps([
        {"name": "Main Storage", "pos": "10 64 -20", "dim": "minecraft:overworld"},
        {"name": "Nether hub", "pos": "1 70 1", "dim": "minecraft:the_nether"}]))
    (tmp_path / "discoveries.json").write_text(json.dumps({
        "overworld:village:1:1": {"type": "village", "dim": "overworld", "x": 24,
                                  "z": 24, "by": "TeamGreenRob", "at": 1760000000}}))
    storage_mod.scan_state.update({"state": "ready", "structures": [
        {"key": "overworld:village:1:1", "type": "village", "dim": "overworld",
         "x": 24, "z": 24, "pieces": [[0, 60, 0, 40, 80, 40]]}]})
    r = bm.get("/bluemap/maps/world/live/markers.json")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["bm-own"]["label"] == "Plugin set"  # the plugin's own sets survive
    assert list(data[bluemap.WAYPOINT_SET]["markers"]) == ["wp:main storage"]
    village = data[bluemap.STRUCTURE_SET]["markers"]["overworld:village:1:1"]
    assert village["position"] == {"x": 24, "y": 70, "z": 24}  # middle of the pieces
    assert FakeBlueMap.hits[-1][1].get("Accept-Encoding") == "identity"
    # nether map: upstream has no file (404) — ours still arrive
    nether = bm.get("/bluemap/maps/world_the_nether/live/markers.json").json()
    assert list(nether) == [bluemap.WAYPOINT_SET]
    assert list(nether[bluemap.WAYPOINT_SET]["markers"]) == ["wp:nether hub"]
    storage_mod.scan_state.clear()
    storage_mod.scan_state["state"] = "idle"


def test_upstream_down_is_a_clear_502(monkeypatch, tmp_path):
    monkeypatch.delenv("DASH_USER", raising=False)
    monkeypatch.delenv("DASH_PASS", raising=False)
    monkeypatch.setenv("BLUEMAP_URL", "http://127.0.0.1:9")  # discard port: refused
    monkeypatch.setenv("CB_DATA", str(tmp_path))
    c = TestClient(app)
    r = c.get("/bluemap/settings.json")
    assert r.status_code == 502 and "isn't answering" in r.text
    assert c.get("/bluemap/maps/world/live/markers.json").json() == {}


def test_bluemap_sits_behind_the_dashboard_login(bm, monkeypatch):
    monkeypatch.setenv("DASH_USER", "rob")
    monkeypatch.setenv("DASH_PASS", "hunter2")
    assert bm.get("/bluemap/").status_code == 401
    assert bm.get("/bluemap/", auth=("rob", "hunter2")).status_code == 200
