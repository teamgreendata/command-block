"""NBT parser + SNBT writer tests, plus a binary builder shared with API tests."""
import gzip
import struct

import pytest

from app import nbt


# -- tiny binary NBT encoder (test-side ground truth) --------------------------

def t_string(s: str) -> bytes:
    b = s.encode()
    return len(b).to_bytes(2, "big") + b


def named(tag: int, name: str, payload: bytes) -> bytes:
    return bytes([tag]) + t_string(name) + payload


def t_byte(v): return v.to_bytes(1, "big", signed=True)
def t_short(v): return v.to_bytes(2, "big", signed=True)
def t_int(v): return v.to_bytes(4, "big", signed=True)
def t_long(v): return v.to_bytes(8, "big", signed=True)
def t_float(v): return struct.pack(">f", v)
def t_double(v): return struct.pack(">d", v)
def t_compound(*children): return b"".join(children) + b"\x00"


def t_list(elem_tag: int, *payloads: bytes) -> bytes:
    return bytes([elem_tag]) + len(payloads).to_bytes(4, "big") + b"".join(payloads)


def root(*children) -> bytes:
    return gzip.compress(named(10, "", t_compound(*children)))


# -- parser --------------------------------------------------------------------

def test_parse_every_tag_type():
    blob = root(
        named(1, "byte", t_byte(-3)),
        named(2, "short", t_short(300)),
        named(3, "int", t_int(70000)),
        named(4, "long", t_long(1 << 40)),
        named(5, "float", t_float(1.5)),
        named(6, "double", t_double(2.25)),
        named(7, "bytes", t_int(2) + t_byte(1) + t_byte(-2)),
        named(8, "str", t_string("héllo")),
        named(9, "list", t_list(3, t_int(7), t_int(8))),
        named(10, "nested", t_compound(named(1, "inner", t_byte(1)))),
        named(11, "ints", t_int(2) + t_int(5) + t_int(-6)),
        named(12, "longs", t_int(1) + t_long(9)),
    )
    r = nbt.parse(blob)
    assert r["byte"] == -3 and isinstance(r["byte"], nbt.Byte)
    assert r["short"] == 300 and isinstance(r["short"], nbt.Short)
    assert r["int"] == 70000 and type(r["int"]) is int
    assert r["long"] == 1 << 40 and isinstance(r["long"], nbt.Long)
    assert r["float"] == 1.5 and isinstance(r["float"], nbt.Float)
    assert r["double"] == 2.25 and type(r["double"]) is float
    assert list(r["bytes"]) == [1, -2]
    assert r["str"] == "héllo"
    assert r["list"] == [7, 8]
    assert r["nested"] == {"inner": 1}
    assert list(r["ints"]) == [5, -6]
    assert list(r["longs"]) == [9]


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        nbt.parse(b"definitely not nbt")


def test_parse_raw_uncompressed():
    blob = named(10, "", t_compound(named(3, "x", t_int(1))))
    assert nbt.parse(blob) == {"x": 1}


# -- SNBT writer ---------------------------------------------------------------

def test_snbt_types_and_quoting():
    assert nbt.snbt(nbt.Byte(1)) == "1b"
    assert nbt.snbt(nbt.Short(2)) == "2s"
    assert nbt.snbt(nbt.Long(3)) == "3L"
    assert nbt.snbt(5) == "5"
    assert nbt.snbt(nbt.Float(1.5)) == "1.5f"
    assert nbt.snbt(2.25) == "2.25d"
    assert nbt.snbt('say "hi" \\ there') == '"say \\"hi\\" \\\\ there"'
    assert nbt.snbt(nbt.IntArray([1, -2])) == "[I;1,-2]"
    assert nbt.snbt([nbt.Byte(1), nbt.Byte(0)]) == "[1b,0b]"
    # namespaced keys need quotes; bare keys don't
    assert nbt.snbt({"minecraft:sharpness": 5, "lvl": nbt.Short(1)}) \
        == '{"minecraft:sharpness":5,lvl:1s}'


def test_snbt_round_trips_a_parsed_component():
    comp = t_compound(
        named(10, "minecraft:enchantments", t_compound(
            named(3, "minecraft:sharpness", t_int(5)),
            named(3, "minecraft:unbreaking", t_int(3)),
        )),
    )
    r = nbt.parse(root(named(10, "components", comp)))
    assert nbt.snbt(r["components"]) \
        == '{"minecraft:enchantments":{"minecraft:sharpness":5,"minecraft:unbreaking":3}}'
