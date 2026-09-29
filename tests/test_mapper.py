"""Map tile rendering: heightmap decode, palette lookup, shading, caching."""
import os
import struct
import zlib

import pytest

from app import mapper
from tests.test_nbt import named, t_byte, t_compound, t_int, t_list, t_string
from tests.test_storage import region_file


def t_long_array(values):
    out = len(values).to_bytes(4, "big")
    for v in values:
        out += (v & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big")
    return out


def pack(values, bits):
    """Non-spanning little-endian-in-long packing, like the game writes."""
    per_long = 64 // bits
    longs = []
    for i in range(0, len(values), per_long):
        v = 0
        for j, val in enumerate(values[i:i + per_long]):
            v |= (val & ((1 << bits) - 1)) << (bits * j)
        longs.append(v)
    return longs


def make_chunk(cx, cz):
    """One section (Y=4): x0=grass y64, x1=water y64 depth 5, x2=sand y64."""
    heights = [0] * 256
    floors = [0] * 256
    for x in range(3):
        heights[x] = 129          # y = -64 + 129 - 1 = 64
        floors[x] = 129
    floors[1] = 124               # water column: floor 5 below surface
    palette = t_list(10,
                     t_compound(named(8, "Name", t_string("minecraft:grass_block"))),
                     t_compound(named(8, "Name", t_string("minecraft:water"))),
                     t_compound(named(8, "Name", t_string("minecraft:sand"))))
    cells = [0] * 4096
    cells[1] = 1                  # cell index = y&15<<8 | z<<4 | x
    cells[2] = 2
    section = t_compound(
        named(1, "Y", t_byte(4)),
        named(10, "block_states", t_compound(
            named(9, "palette", palette),
            named(12, "data", t_long_array(pack(cells, 4))))))
    raw = named(10, "", t_compound(
        named(3, "xPos", t_int(cx)),
        named(3, "zPos", t_int(cz)),
        named(3, "yPos", t_int(-4)),
        named(10, "Heightmaps", t_compound(
            named(12, "WORLD_SURFACE", t_long_array(pack(heights, 9))),
            named(12, "OCEAN_FLOOR", t_long_array(pack(floors, 9))))),
        named(9, "sections", t_list(10, section)),
    ))
    return zlib.compress(raw)


def decode_png(png: bytes):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat = 8, b""
    while pos < len(png):
        length = int.from_bytes(png[pos:pos + 4], "big")
        tag = png[pos + 4:pos + 8]
        if tag == b"IDAT":
            idat += png[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = mapper.TILE * 4 + 1
    rows = [raw[i * stride + 1:(i + 1) * stride] for i in range(mapper.TILE)]
    return lambda x, z: tuple(rows[z][x * 4:x * 4 + 4])


def test_render_known_pixels(tmp_path):
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(region_file(make_chunk(0, 0)))
    px = decode_png(mapper.render_region(region))
    grass = mapper._shade(mapper.BLOCK_COLORS["grass_block"], 64)
    sand = mapper._shade(mapper.BLOCK_COLORS["sand"], 64)
    water = mapper._water_shade(5)
    assert px(0, 0) == (*grass, 255)
    assert px(1, 0) == (*water, 255)
    assert px(2, 0) == (*sand, 255)
    assert px(3, 0) == (0, 0, 0, 0)      # empty column -> transparent
    assert px(100, 100) == (0, 0, 0, 0)  # missing chunk -> transparent


def test_chunk_offset_lands_in_the_right_tile_corner(tmp_path):
    region = tmp_path / "r.1.-1.mca"  # offsets only depend on cx&31 / cz&31
    region.write_bytes(region_file(make_chunk(33, -31)))  # local chunk (1, 1)
    px = decode_png(mapper.render_region(region))
    grass = mapper._shade(mapper.BLOCK_COLORS["grass_block"], 64)
    assert px(16, 16) == (*grass, 255)
    assert px(0, 0) == (0, 0, 0, 0)


def test_shading_is_monotonic_with_height():
    lo = mapper._shade((100, 100, 100), 40)
    hi = mapper._shade((100, 100, 100), 120)
    assert hi > lo
    deep = mapper._water_shade(20)
    shallow = mapper._water_shade(1)
    assert shallow > deep


def test_block_color_fallbacks():
    assert mapper.block_color("minecraft:birch_leaves") == mapper.BLOCK_COLORS["birch_leaves"]
    assert mapper.block_color("minecraft:pale_oak_log") == mapper._WOOD
    assert mapper.block_color("minecraft:deepslate_emerald_ore") == mapper._STONEISH
    assert mapper.block_color("minecraft:torchflower") == mapper._PLANT
    assert mapper.block_color("minecraft:mystery_gizmo") == mapper._UNKNOWN


def test_tile_cache_by_mtime(tmp_path, monkeypatch):
    region = tmp_path / "r.0.0.mca"
    region.write_bytes(region_file(make_chunk(0, 0)))
    cache = tmp_path / "tiles"
    calls = []
    real = mapper.render_region
    monkeypatch.setattr(mapper, "render_region", lambda p: calls.append(1) or real(p))
    out1 = mapper.tile_for(region, cache)
    assert out1.is_file() and len(calls) == 1
    mapper.tile_for(region, cache)
    assert len(calls) == 1  # cache hit
    os.utime(region, ns=(1, 1))  # region changed -> re-render
    mapper.tile_for(region, cache)
    assert len(calls) == 2
