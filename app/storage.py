"""Placed-container scanning + shared item rendering.

Containers players place (chests, trapped chests, barrels, shulker boxes) are
block entities in the chunk NBT, read straight from the region files on the
read-only world mount. Untouched world-generated loot chests carry a LootTable
tag and are skipped — what remains is player storage (a looted dungeon chest is
indistinguishable from a placed one; the UI says so). Region files are cached
by (mtime, size) so refreshes only re-parse chunks that actually changed.

The item -> tooltip-view rendering lives here too (moved from main.py) since
chest slots and inventory slots must describe items identically.
"""

import json
from pathlib import Path

from app import nbt

_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]

CONTAINER_IDS = {  # block-entity ids (all shulker colors share one id)
    "minecraft:chest": "Chest",
    "minecraft:trapped_chest": "Trapped Chest",
    "minecraft:barrel": "Barrel",
    "minecraft:shulker_box": "Shulker Box",
}
_DIMS = ("overworld", "the_nether", "the_end")


def _roman(n: int) -> str:
    return _ROMAN[n] if 0 < n < len(_ROMAN) else str(n)


def _pretty_mc(mc_id: str) -> str:
    return str(mc_id).split(":")[-1].replace("_", " ").title()


def _text_of(v) -> str:
    """Flatten a Minecraft text component (JSON string, dict, or list)."""
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except ValueError:
            return v
        return v if isinstance(parsed, (int, float)) else _text_of(parsed)
    if isinstance(v, dict):
        base = str(v.get("text", ""))
        extra = v.get("extra")
        if isinstance(extra, list):
            base += "".join(_text_of(e) for e in extra)
        return base
    if isinstance(v, list):
        return "".join(_text_of(e) for e in v)
    return str(v)


def _compact(v) -> str:
    """Readable one-line rendering for arbitrary component values."""
    if isinstance(v, dict):
        return "{" + ", ".join(
            f"{_pretty_mc(k) if ':' in str(k) else k}: {_compact(x)}"
            for k, x in v.items()) + "}"
    if isinstance(v, (list, nbt.ByteArray, nbt.IntArray, nbt.LongArray)):
        return "[" + ", ".join(_compact(x) for x in v) + "]"
    if isinstance(v, str):
        return _pretty_mc(v) if v.startswith("minecraft:") else v
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _component_lines(key: str, val) -> list[str]:
    """Every component becomes readable tooltip lines — nothing is elided."""
    bare = key.split(":")[-1]
    if bare == "trim" and isinstance(val, dict):
        return [f"Trim: {_pretty_mc(str(val.get('pattern', '?')))} + "
                f"{_pretty_mc(str(val.get('material', '?')))}"]
    if bare == "potion_contents":
        if isinstance(val, str):
            return [f"Potion: {_pretty_mc(val)}"]
        if isinstance(val, dict):
            lines = []
            if val.get("potion"):
                lines.append(f"Potion: {_pretty_mc(str(val['potion']))}")
            for eff in val.get("custom_effects", []) or []:
                if isinstance(eff, dict) and eff.get("id"):
                    amp = int(eff.get("amplifier", 0)) + 1
                    lines.append(f"Effect: {_pretty_mc(str(eff['id']))} {_roman(amp)}")
            return lines or [f"Potion Contents: {_compact(val)}"]
    if bare == "lore" and isinstance(val, list):
        return [f"“{_text_of(line)}”" for line in val]
    if bare == "unbreakable":
        return ["Unbreakable"]
    if bare == "repair_cost":
        return [f"Repair cost: {val}"]
    if bare == "container" and isinstance(val, list):
        lines = ["Contains:"]
        for entry in val:
            item = entry.get("item", {}) if isinstance(entry, dict) else {}
            if isinstance(item, dict) and item.get("id"):
                lines.append(f"· {int(item.get('count', 1))}× {_pretty_mc(item['id'])}")
        return lines
    if bare == "attribute_modifiers":
        mods = (val if isinstance(val, list)
                else val.get("modifiers", []) if isinstance(val, dict) else [])
        lines = []
        for m in mods:
            if isinstance(m, dict) and m.get("type") is not None:
                amount = float(m.get("amount", 0))
                lines.append(f"{_pretty_mc(str(m['type']))}: "
                             f"{'+' if amount >= 0 else ''}{amount:g}")
        if lines:
            return lines
    return [f"{_pretty_mc(key)}: {_compact(val)}"]


def item_view(item) -> dict | None:
    """One item stack -> everything the tooltip shows (complete: every
    component renders — the UI never alludes to hidden information)."""
    if not isinstance(item, dict) or "id" not in item:
        return None
    comps = item.get("components", {})
    ench = comps.get("minecraft:enchantments") or comps.get("minecraft:stored_enchantments") or {}
    if isinstance(ench, dict) and isinstance(ench.get("levels"), dict):
        ench = ench["levels"]
    enchants = ([f"{_pretty_mc(k)} {_roman(int(v))}" for k, v in ench.items()]
                if isinstance(ench, dict) else [])
    extras = []
    dmg = comps.get("minecraft:damage")
    if isinstance(dmg, int) and dmg > 0:
        extras.append(f"Damage: {dmg}")
    name = _text_of(comps["minecraft:custom_name"]) \
        if "minecraft:custom_name" in comps else None
    shown = {"minecraft:enchantments", "minecraft:stored_enchantments",
             "minecraft:damage", "minecraft:custom_name"}
    for key in comps:
        if key not in shown:
            extras.extend(_component_lines(key, comps[key]))
    return {"id": item["id"], "count": int(item.get("count", 1)), "enchants": enchants,
            "extras": extras, "custom_name": name or None}


# ---------------------------------------------------------------- region scan

_cache: dict[str, tuple[int, int, list]] = {}  # path -> (mtime_ns, size, containers)


def _add_totals(totals: dict, item: dict) -> None:
    totals[item["id"]] = totals.get(item["id"], 0) + int(item.get("count", 1))
    container = item.get("components", {}).get("minecraft:container")
    if isinstance(container, list):  # shulker inside a chest: count its contents too
        for entry in container:
            inner = entry.get("item") if isinstance(entry, dict) else None
            if isinstance(inner, dict) and inner.get("id"):
                _add_totals(totals, inner)


def _containers_in_region(path: Path, dim: str) -> list:
    raw = path.read_bytes()
    out = []
    for i in range(1024):
        entry = int.from_bytes(raw[i * 4:i * 4 + 4], "big")
        offset, sectors = entry >> 8, entry & 0xFF
        if not (offset and sectors):
            continue
        blob = raw[offset * 4096:(offset + sectors) * 4096]
        if len(blob) < 5:
            continue
        length = int.from_bytes(blob[:4], "big")
        try:  # nbt.parse handles gzip/zlib/raw, covering compression bytes 1/2/3
            chunk = nbt.parse(blob[5:4 + length])
        except Exception:
            continue
        for be in chunk.get("block_entities", []):
            if not isinstance(be, dict) or str(be.get("id")) not in CONTAINER_IDS:
                continue
            if "LootTable" in be:  # untouched world-generated loot chest
                continue
            totals: dict = {}
            items: dict = {}
            for item in be.get("Items", []):
                view = item_view(item)
                if view:
                    items[str(int(item.get("Slot", 0)))] = view
                    _add_totals(totals, item)
            name = _text_of(be["CustomName"]) if "CustomName" in be else None
            out.append({"dim": dim, "x": be.get("x"), "y": be.get("y"), "z": be.get("z"),
                        "kind": CONTAINER_IDS[str(be["id"])], "name": name or None,
                        "items": items, "totals": totals})
    return out


def scan_containers(data_dir: Path) -> list:
    """All player-relevant containers across the three dimensions, cached per
    region file by (mtime, size)."""
    world = None
    try:
        for d in sorted(Path(data_dir).iterdir()):
            if (d / "players").is_dir() or (d / "playerdata").is_dir():
                world = d
                break
    except OSError:
        pass
    if world is None:
        return []
    containers: list = []
    for dim in _DIMS:
        region_dir = world / "dimensions" / "minecraft" / dim / "region"
        if not region_dir.is_dir() and dim == "overworld":
            region_dir = world / "region"  # classic layout
        if not region_dir.is_dir():
            continue
        for path in sorted(region_dir.glob("*.mca")):
            try:
                st = path.stat()
            except OSError:
                continue
            key = str(path)
            hit = _cache.get(key)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                containers.extend(hit[2])
                continue
            try:
                found = _containers_in_region(path, dim)
            except OSError:
                continue
            _cache[key] = (st.st_mtime_ns, st.st_size, found)
            containers.extend(found)
    order = {d: i for i, d in enumerate(_DIMS)}
    containers.sort(key=lambda c: (order[c["dim"]], c["x"] or 0, c["z"] or 0, c["y"] or 0))
    return containers
