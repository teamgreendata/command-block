"""Top-down map tiles rendered from region files.

One PNG per region (512x512, 1px per block column): the WORLD_SURFACE
heightmap picks each column's top block, the section block_states palette
names it, a curated color table paints it, and height/water-depth shading
gives the classic map look. Tiles cache on disk keyed by the region file's
mtime — a changed region re-renders, everything else is served as-is.
Stdlib only (zlib/struct PNG encoder), same as the rest of the project.
"""

import os
import struct
import zlib
from pathlib import Path

from app import nbt

TILE = 512

# base colors, loosely after the vanilla map palette
BLOCK_COLORS = {
    "grass_block": (127, 178, 56), "dirt": (151, 109, 77), "coarse_dirt": (151, 109, 77),
    "rooted_dirt": (151, 109, 77), "podzol": (90, 63, 35), "mud": (60, 57, 60),
    "mycelium": (111, 99, 105), "dirt_path": (148, 122, 65), "farmland": (114, 82, 47),
    "stone": (112, 112, 112), "deepslate": (70, 70, 70), "cobblestone": (110, 110, 110),
    "mossy_cobblestone": (100, 118, 90), "bedrock": (60, 60, 60),
    "granite": (149, 103, 85), "diorite": (180, 180, 183), "andesite": (130, 131, 131),
    "tuff": (108, 109, 102), "calcite": (203, 205, 201), "dripstone_block": (134, 107, 92),
    "gravel": (136, 126, 126), "sand": (247, 233, 163), "red_sand": (216, 127, 51),
    "sandstone": (230, 221, 158), "red_sandstone": (200, 118, 51),
    "clay": (164, 168, 184), "terracotta": (152, 94, 67),
    "water": (63, 118, 228), "lava": (207, 16, 32), "ice": (160, 187, 255),
    "packed_ice": (141, 180, 250), "blue_ice": (116, 167, 253),
    "snow": (250, 250, 250), "snow_block": (250, 250, 250), "powder_snow": (248, 246, 250),
    "short_grass": (88, 141, 46), "tall_grass": (88, 141, 46), "fern": (82, 139, 62),
    "large_fern": (82, 139, 62), "seagrass": (63, 118, 228), "kelp": (63, 118, 228),
    "lily_pad": (32, 128, 48), "moss_block": (89, 125, 39), "moss_carpet": (89, 125, 39),
    "pale_moss_block": (160, 170, 150), "vine": (74, 110, 38),
    "cactus": (85, 128, 32), "pumpkin": (198, 118, 24), "melon": (111, 153, 31),
    "sugar_cane": (130, 168, 89), "bamboo": (118, 145, 47),
    "azalea": (95, 130, 55), "flowering_azalea": (120, 130, 90),
    "netherrack": (111, 54, 52), "soul_sand": (84, 64, 51), "soul_soil": (75, 57, 46),
    "basalt": (88, 88, 92), "smooth_basalt": (80, 80, 84), "blackstone": (42, 36, 41),
    "magma_block": (142, 63, 30), "glowstone": (248, 198, 116),
    "crimson_nylium": (149, 42, 42), "warped_nylium": (43, 114, 101),
    "nether_wart_block": (145, 30, 30), "warped_wart_block": (22, 122, 122),
    "shroomlight": (235, 146, 82),
    "end_stone": (221, 223, 165), "obsidian": (21, 20, 31), "crying_obsidian": (42, 20, 60),
    "purpur_block": (170, 126, 170), "chorus_plant": (110, 74, 110),
    "chorus_flower": (150, 110, 150),
    "oak_leaves": (60, 130, 33), "birch_leaves": (107, 141, 70),
    "spruce_leaves": (52, 90, 52), "jungle_leaves": (48, 128, 20),
    "acacia_leaves": (94, 130, 42), "dark_oak_leaves": (46, 102, 24),
    "mangrove_leaves": (48, 118, 30), "cherry_leaves": (228, 177, 202),
    "azalea_leaves": (90, 128, 50), "pale_oak_leaves": (140, 150, 135),
    "mushroom_stem": (203, 196, 185), "red_mushroom_block": (200, 46, 45),
    "brown_mushroom_block": (149, 111, 81),
    "cobweb": (228, 233, 234), "bee_nest": (180, 140, 60),
}
_FOLIAGE = (0, 124, 0)
_WOOD = (143, 119, 72)
_STONEISH = (112, 112, 112)
_PLANT = (88, 141, 46)
_UNKNOWN = (128, 108, 128)


def block_color(block_id: str) -> tuple:
    bare = block_id.split(":")[-1]
    if bare in BLOCK_COLORS:
        return BLOCK_COLORS[bare]
    if bare.startswith("stripped_"):
        return _WOOD
    if bare.endswith(("_leaves",)):
        return _FOLIAGE
    if bare.endswith(("_log", "_wood", "_planks", "_stem", "_hyphae", "_fence", "_stairs",
                      "_slab", "_trapdoor", "_door")):
        return _WOOD
    if bare.endswith(("_ore", "_deepslate", "stone", "_block")):
        return _STONEISH
    if bare.endswith(("_sapling", "flower", "_bush", "_crop", "_plant", "_roots",
                      "_fungus", "_vines", "_petals", "tulip", "orchid", "daisy")) \
            or bare in ("poppy", "dandelion", "allium", "lilac", "peony"):
        return _PLANT
    if bare.endswith(("_terracotta",)):
        return BLOCK_COLORS["terracotta"]
    if bare.endswith(("_wool", "_carpet", "_concrete", "_concrete_powder")):
        return (199, 199, 199)
    if bare.endswith("_coral") or "coral" in bare:
        return (216, 127, 251)
    return _UNKNOWN


def _unpack(longs, bits: int, count: int) -> list:
    """Non-spanning packed values (heightmaps and palette indices alike)."""
    per_long = 64 // bits
    mask = (1 << bits) - 1
    out = []
    for value in longs:
        value &= 0xFFFFFFFFFFFFFFFF
        for _ in range(per_long):
            out.append(value & mask)
            value >>= bits
            if len(out) == count:
                return out
    return out


def _shade(color: tuple, y: int) -> tuple:
    factor = 0.72 + max(0.0, min(1.0, (y - 50) / 80)) * 0.34
    return tuple(min(255, int(c * factor)) for c in color)


def _water_shade(depth: int) -> tuple:
    factor = max(0.55, 0.95 - depth * 0.02)
    return tuple(min(255, int(c * factor)) for c in BLOCK_COLORS["water"])


def _png_rgba(rows: list) -> bytes:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", TILE, TILE, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def _render_chunk(chunk: dict, pixels: list) -> None:
    lcx = chunk["xPos"] & 31
    lcz = chunk["zPos"] & 31
    hm_longs = (chunk.get("Heightmaps") or {}).get("WORLD_SURFACE")
    if hm_longs is None:
        return
    min_y = int(chunk.get("yPos", 0)) * 16
    heights = _unpack(list(hm_longs), 9, 256)
    ocean = (chunk.get("Heightmaps") or {}).get("OCEAN_FLOOR")
    floors = _unpack(list(ocean), 9, 256) if ocean is not None else None
    sections = {}
    for s in chunk.get("sections", []):
        bs = s.get("block_states")
        if bs and bs.get("palette"):
            palette = [str(p.get("Name", "minecraft:air")) for p in bs["palette"]]
            data = bs.get("data")
            bits = max(4, (len(palette) - 1).bit_length())
            sections[int(s["Y"])] = (palette, None if data is None else list(data), bits)
    for i in range(256):
        if heights[i] == 0:  # empty column
            continue
        y = min_y + heights[i] - 1
        x, z = i & 15, i >> 4
        sec = sections.get(y >> 4)
        if sec is None:
            continue
        palette, data, bits = sec
        if data is None:
            block = palette[0]
        else:
            cell = ((y & 15) << 8) | ((z & 15) << 4) | (x & 15)
            block = palette[_unpack_at(data, bits, cell)]
        bare = block.split(":")[-1]
        if bare == "water":
            depth = (heights[i] - floors[i]) if floors else 0
            rgb = _water_shade(depth)
        else:
            rgb = _shade(block_color(block), y)
        px, pz = lcx * 16 + x, lcz * 16 + z
        pixels[pz][px] = bytes((*rgb, 255))


def _unpack_at(longs, bits: int, index: int) -> int:
    per_long = 64 // bits
    value = longs[index // per_long] & 0xFFFFFFFFFFFFFFFF
    return (value >> (bits * (index % per_long))) & ((1 << bits) - 1)


def render_region(path: Path) -> bytes:
    raw = path.read_bytes()
    pixels = [[b"\x00\x00\x00\x00"] * TILE for _ in range(TILE)]
    for i in range(1024):
        entry = int.from_bytes(raw[i * 4:i * 4 + 4], "big")
        offset, sectors = entry >> 8, entry & 0xFF
        if not (offset and sectors):
            continue
        blob = raw[offset * 4096:(offset + sectors) * 4096]
        if len(blob) < 5:
            continue
        length = int.from_bytes(blob[:4], "big")
        try:
            chunk = nbt.parse(blob[5:4 + length])
        except Exception:
            continue
        if "xPos" not in chunk or "zPos" not in chunk:
            continue
        try:
            _render_chunk(chunk, pixels)
        except Exception:
            continue  # a malformed chunk must not sink the whole tile
    return _png_rgba([b"".join(row) for row in pixels])


def tile_for(region_path: Path, cache_dir: Path) -> Path:
    """Cached tile path for a region, rendering if missing or stale.
    Freshness contract: the tile PNG's mtime is SET EQUAL to the region's."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / (region_path.stem + ".png")
    src_stat = region_path.stat()
    try:
        if out.stat().st_mtime_ns == src_stat.st_mtime_ns:
            return out
    except OSError:
        pass
    tmp = out.with_suffix(".tmp")
    tmp.write_bytes(render_region(region_path))
    os.utime(tmp, ns=(src_stat.st_mtime_ns, src_stat.st_mtime_ns))
    tmp.replace(out)
    return out
