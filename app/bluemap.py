"""BlueMap pass-through: the plugin's web app, served under /bluemap/.

BlueMap runs inside the minecraft container (Paper plugin, web server on 8100
on the stack network, never published). The dashboard proxies it so the map
shares the dashboard's origin, login and LAN/tailnet reach, and folds its own
waypoints and discovered structures into BlueMap's marker feed.
"""
import html
import http.client
import re
import time
import urllib.error
import urllib.parse
import urllib.request

REQUEST_HEADERS = ("accept-encoding", "if-none-match", "if-modified-since")
RESPONSE_HEADERS = ("content-type", "content-encoding", "cache-control", "etag",
                    "last-modified", "location")

MARKERS_RE = re.compile(r"^maps/([A-Za-z0-9_.\-]+)/live/markers\.json$")
SSE_RE = re.compile(r"^maps/[^/]+/live/sse$")

WAYPOINT_SET = "cb-waypoints"
STRUCTURE_SET = "cb-structures"

# Same palette as the built-in map's STRUCTURE_STYLES in app.js — keep in step.
STRUCTURE_COLORS = {
    "village": "#b08d55", "trial_chambers": "#c15f38", "fortress": "#8f3838",
    "bastion_remnant": "#5c5c66", "stronghold": "#a56fd8", "monument": "#55ffff",
    "ancient_city": "#1d3340", "mansion": "#7a3b2e", "pillager_outpost": "#9b7b4d",
    "ruined_portal": "#8a4ec9", "shipwreck": "#4a72b0", "buried_treasure": "#ffaa00",
    "mineshaft": "#8b8b8b", "desert_pyramid": "#e6d9a0", "jungle_temple": "#4c7c3c",
    "igloo": "#dfe9f0", "swamp_hut": "#3c5c3c",
}
_DEFAULT_COLOR = "#e8e8e8"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # 3xx goes back to the browser, which must see the new URL


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def fetch(url: str, headers: dict, timeout: float = 10) -> tuple[int, dict, bytes]:
    """GET url; any HTTP status comes back as a value, network failure raises OSError."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
    except http.client.HTTPException as e:  # truncated/garbled reply: same as down
        raise OSError(str(e)) from e


def safe_path(path: str) -> str | None:
    """URL-quoted relative path, or None for anything that could climb out."""
    if "\\" in path or "\0" in path or path.startswith("/"):
        return None
    if any(seg in (".", "..") for seg in path.split("/")):
        return None
    return urllib.parse.quote(path, safe="/")


def reply_headers(upstream: dict) -> dict:
    out = {k: upstream[k] for k in RESPONSE_HEADERS if k in upstream}
    if out.get("location", "").startswith("/"):
        out["location"] = "/bluemap" + out["location"]
    return out


def dim_for_map(map_id: str) -> str:
    """BlueMap's default ids: world, world_the_nether / world_nether, world_the_end."""
    m = map_id.lower()
    if "nether" in m:
        return "the_nether"
    if re.search(r"(?:^|_)(?:the_)?end(?:_|$)", m):
        return "the_end"
    return "overworld"


def _svg_uri(svg: str) -> str:
    return "data:image/svg+xml," + urllib.parse.quote(svg)


WAYPOINT_ICON = _svg_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="28" viewBox="0 0 20 28">'
    '<path d="M10 27 C10 27 2 16 2 10 a8 8 0 0 1 16 0 C18 16 10 27 10 27Z" '
    'fill="#ffaa00" stroke="#000" stroke-width="2"/>'
    '<rect x="7" y="7" width="6" height="6" fill="#000"/></svg>')
WAYPOINT_ANCHOR = {"x": 10, "y": 27}
STRUCTURE_ANCHOR = {"x": 9, "y": 9}


def structure_icon(structure_type: str) -> str:
    color = STRUCTURE_COLORS.get(structure_type, _DEFAULT_COLOR)
    return _svg_uri(
        '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
        f'<rect x="3" y="3" width="12" height="12" fill="{color}" stroke="#000" '
        'stroke-width="2" transform="rotate(45 9 9)"/></svg>')


def structure_label(structure_type: str) -> str:
    return structure_type.replace("_", " ").title()


def _poi(label: str, x: float, y: float, z: float, detail: str, icon: str,
         anchor: dict) -> dict:
    return {"type": "poi", "label": label, "position": {"x": x, "y": y, "z": z},
            "detail": detail, "icon": icon, "anchor": anchor, "classes": [],
            "sorting": 0, "listed": True, "minDistance": 0, "maxDistance": 10_000_000}


def _num(v: float) -> str:
    return f"{v:g}"


def marker_sets(dim: str, waypoints: list, structures: list) -> dict:
    """BlueMap marker-set JSON for one dimension. Only non-empty sets appear."""
    wps = {}
    for w in waypoints:
        if (w.get("dim") or "minecraft:overworld").removeprefix("minecraft:") != dim:
            continue
        try:
            x, y, z = (float(v) for v in w["pos"].split())
        except (KeyError, ValueError, AttributeError):
            continue
        name = html.escape(w["name"])
        wps[f"wp:{w['name'].lower()}"] = _poi(
            w["name"], x, y, z,
            f"<b>{name}</b><br>{_num(x)} {_num(y)} {_num(z)}",
            WAYPOINT_ICON, WAYPOINT_ANCHOR)
    found = {}
    for s in structures:
        if s.get("dim") != dim:
            continue
        label = structure_label(s["type"])
        lines = [f"<b>{html.escape(label)}</b>", f"{s['x']} {s['z']}"]
        if s.get("by"):
            credit = f"found by {html.escape(s['by'])}"
            if s.get("backfilled"):
                credit += " (from advancements)"
            elif s.get("at"):
                credit += time.strftime(" · %b %-d, %Y", time.localtime(s["at"]))
            lines.append(credit)
        found[s["key"]] = _poi(label, s["x"], s.get("y", 64), s["z"], "<br>".join(lines),
                               structure_icon(s["type"]), STRUCTURE_ANCHOR)
    out = {}
    if wps:
        out[WAYPOINT_SET] = {"label": "Waypoints", "toggleable": True,
                             "defaultHidden": False, "sorting": 10, "markers": wps}
    if found:
        out[STRUCTURE_SET] = {"label": "Discovered structures", "toggleable": True,
                              "defaultHidden": False, "sorting": 11, "markers": found}
    return out


def merge_markers(upstream: dict, ours: dict) -> dict:
    """Upstream sets stay; ours replace any stale copies of the same ids."""
    merged = {k: v for k, v in upstream.items() if k not in (WAYPOINT_SET, STRUCTURE_SET)}
    merged.update(ours)
    return merged
