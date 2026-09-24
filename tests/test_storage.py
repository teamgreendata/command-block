"""Region-file container scanning: extraction, filtering, totals, caching."""
import zlib

import pytest

from app import storage
from tests.test_nbt import named, t_byte, t_compound, t_int, t_list, t_string


def chunk_nbt(x, z, *block_entities) -> bytes:
    raw = named(10, "", t_compound(
        named(3, "xPos", t_int(x)),
        named(3, "zPos", t_int(z)),
        named(9, "block_entities", t_list(10, *block_entities)),
    ))
    return zlib.compress(raw)


def region_file(*chunks: bytes) -> bytes:
    """Anvil container: 4KB offset header + 4KB timestamps + chunk sectors."""
    header = bytearray(8192)
    body = b""
    sector = 2
    for i, comp in enumerate(chunks):
        # Anvil length field counts the compression byte + data
        blob = (len(comp) + 1).to_bytes(4, "big") + b"\x02" + comp
        sectors = -(-len(blob) // 4096)
        header[i * 4:i * 4 + 4] = ((sector << 8) | sectors).to_bytes(4, "big")
        body += blob.ljust(sectors * 4096, b"\x00")
        sector += sectors
    return bytes(header) + body


def block_entity(be_id, x, y, z, items=(), loot_table=None, custom_name=None):
    children = [
        named(8, "id", t_string(be_id)),
        named(3, "x", t_int(x)), named(3, "y", t_int(y)), named(3, "z", t_int(z)),
        named(9, "Items", t_list(10, *items)),
    ]
    if loot_table:
        children.append(named(8, "LootTable", t_string(loot_table)))
    if custom_name:
        children.append(named(8, "CustomName", t_string(custom_name)))
    return t_compound(*children)


def stack(slot, item_id, count, *components):
    return t_compound(
        named(1, "Slot", t_byte(slot)),
        named(8, "id", t_string(item_id)),
        named(3, "count", t_int(count)),
        *((named(10, "components", t_compound(*components)),) if components else ()))


@pytest.fixture
def world(tmp_path):
    storage._cache.clear()
    (tmp_path / "world" / "playerdata").mkdir(parents=True)
    for dim in ("overworld", "the_nether", "the_end"):
        (tmp_path / "world" / "dimensions" / "minecraft" / dim / "region").mkdir(parents=True)
    yield tmp_path
    storage._cache.clear()


def _region_dir(world, dim):
    return world / "world" / "dimensions" / "minecraft" / dim / "region"


def test_scan_extracts_containers_and_totals(world):
    shulker_contents = named(9, "minecraft:container", t_list(
        10,
        t_compound(named(3, "slot", t_int(0)),
                   named(10, "item", t_compound(
                       named(8, "id", t_string("minecraft:diamond")),
                       named(3, "count", t_int(64)))))))
    chest = block_entity("minecraft:chest", 100, 64, -30, items=[
        stack(0, "minecraft:torch", 64),
        stack(1, "minecraft:shulker_box", 1, shulker_contents),
    ])
    barrel = block_entity("minecraft:barrel", 101, 64, -30,
                          items=[stack(0, "minecraft:bread", 12)],
                          custom_name='{"text":"Snacks"}')
    loot = block_entity("minecraft:chest", 999, 30, 999,
                        loot_table="minecraft:chests/simple_dungeon")
    furnace = block_entity("minecraft:furnace", 1, 1, 1,
                           items=[stack(0, "minecraft:iron_ore", 3)])
    (_region_dir(world, "overworld") / "r.0.-1.mca").write_bytes(
        region_file(chunk_nbt(6, -2, chest, barrel, loot, furnace)))

    found = storage.scan_containers(world)
    assert [(c["kind"], c["x"]) for c in found] == [("Chest", 100), ("Barrel", 101)]
    chest_rec = found[0]
    assert chest_rec["items"]["0"]["id"] == "minecraft:torch"
    # nested shulker contents surface in the tooltip AND count into totals
    assert "· 64× Diamond" in chest_rec["items"]["1"]["extras"]
    assert chest_rec["totals"] == {"minecraft:torch": 64, "minecraft:shulker_box": 1,
                                   "minecraft:diamond": 64}
    assert found[1]["name"] == "Snacks"
    assert found[1]["totals"] == {"minecraft:bread": 12}


def test_scan_covers_other_dimensions(world):
    chest = block_entity("minecraft:chest", 10, 64, 10,
                         items=[stack(0, "minecraft:netherrack", 1)])
    (_region_dir(world, "the_nether") / "r.0.0.mca").write_bytes(
        region_file(chunk_nbt(0, 0, chest)))
    found = storage.scan_containers(world)
    assert len(found) == 1 and found[0]["dim"] == "the_nether"


def test_scan_caches_by_mtime(world, monkeypatch):
    a = _region_dir(world, "overworld") / "r.0.0.mca"
    b = _region_dir(world, "overworld") / "r.0.1.mca"
    a.write_bytes(region_file(chunk_nbt(0, 0, block_entity(
        "minecraft:chest", 1, 64, 1, items=[stack(0, "minecraft:dirt", 1)]))))
    b.write_bytes(region_file(chunk_nbt(0, 32, block_entity(
        "minecraft:chest", 2, 64, 512, items=[stack(0, "minecraft:sand", 2)]))))
    calls = []
    real = storage._containers_in_region

    def counting(path, dim):
        calls.append(path.name)
        return real(path, dim)

    monkeypatch.setattr(storage, "_containers_in_region", counting)
    assert len(storage.scan_containers(world)) == 2
    assert sorted(calls) == ["r.0.0.mca", "r.0.1.mca"]
    assert len(storage.scan_containers(world)) == 2
    assert len(calls) == 2  # both served from cache
    # change one region: only it re-parses
    b.write_bytes(region_file(chunk_nbt(0, 32, block_entity(
        "minecraft:chest", 2, 64, 512, items=[stack(0, "minecraft:sand", 3)]))))
    found = storage.scan_containers(world)
    assert calls.count("r.0.1.mca") == 2 and calls.count("r.0.0.mca") == 1
    assert next(c for c in found if c["x"] == 2)["totals"] == {"minecraft:sand": 3}


def test_scan_handles_garbage_chunks(world):
    header = bytearray(8192)
    header[0:4] = ((2 << 8) | 1).to_bytes(4, "big")
    (_region_dir(world, "overworld") / "r.0.0.mca").write_bytes(
        bytes(header) + b"\x00\x00\x00\x08\x02notzlib".ljust(4096, b"\x00"))
    assert storage.scan_containers(world) == []
