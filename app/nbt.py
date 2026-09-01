"""Minimal NBT reader + SNBT writer, for inventory recovery from playerdata.

Parses a whole (gzipped or raw) NBT blob into Python values with thin wrapper
types that preserve the numeric tag widths, so values can be re-serialized to
SNBT exactly as the game expects them in commands (1b, 2s, 3L, 1.5f, [I;…]).
"""

import gzip
import struct


class Byte(int):
    pass


class Short(int):
    pass


class Long(int):
    pass


class Float(float):
    pass


class ByteArray(list):
    pass


class IntArray(list):
    pass


class LongArray(list):
    pass


class _Reader:
    def __init__(self, raw: bytes):
        self.raw = raw
        self.pos = 0

    def take(self, n: int) -> bytes:
        chunk = self.raw[self.pos:self.pos + n]
        if len(chunk) < n:
            raise ValueError("Truncated NBT data.")
        self.pos += n
        return chunk

    def num(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self) -> str:
        length = self.num(">H")
        return self.take(length).decode("utf-8", errors="replace")

    def payload(self, tag: int):
        if tag == 1:
            return Byte(self.num(">b"))
        if tag == 2:
            return Short(self.num(">h"))
        if tag == 3:
            return self.num(">i")
        if tag == 4:
            return Long(self.num(">q"))
        if tag == 5:
            return Float(self.num(">f"))
        if tag == 6:
            return self.num(">d")
        if tag == 7:
            return ByteArray(self.num(">b") for _ in range(self.num(">i")))
        if tag == 8:
            return self.string()
        if tag == 9:
            elem = self.num(">B")
            return [self.payload(elem) for _ in range(self.num(">i"))]
        if tag == 10:
            out = {}
            while True:
                inner = self.num(">B")
                if inner == 0:
                    return out
                name = self.string()  # must read the name BEFORE the payload
                out[name] = self.payload(inner)
        if tag == 11:
            return IntArray(self.num(">i") for _ in range(self.num(">i")))
        if tag == 12:
            return LongArray(self.num(">q") for _ in range(self.num(">i")))
        raise ValueError(f"Unknown NBT tag {tag}.")


def parse(blob: bytes) -> dict:
    """Root compound of a .dat blob (gzip, zlib or raw)."""
    try:
        raw = gzip.decompress(blob)
    except (gzip.BadGzipFile, EOFError, OSError):
        import zlib
        try:
            raw = zlib.decompress(blob)
        except zlib.error:
            raw = blob
    r = _Reader(raw)
    if r.num(">B") != 10:
        raise ValueError("Not an NBT compound file.")
    r.string()  # root name, usually empty
    return r.payload(10)


_BARE_KEY_OK = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.+")


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def snbt(v) -> str:
    """Serialize a parsed value back to SNBT (command syntax)."""
    if isinstance(v, Byte):
        return f"{int(v)}b"
    if isinstance(v, Short):
        return f"{int(v)}s"
    if isinstance(v, Long):
        return f"{int(v)}L"
    if isinstance(v, bool):
        return "1b" if v else "0b"
    if isinstance(v, Float):
        return f"{float(v)}f"
    if isinstance(v, ByteArray):
        return "[B;" + ",".join(f"{int(x)}b" for x in v) + "]"
    if isinstance(v, IntArray):
        return "[I;" + ",".join(str(int(x)) for x in v) + "]"
    if isinstance(v, LongArray):
        return "[L;" + ",".join(f"{int(x)}L" for x in v) + "]"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v}d"
    if isinstance(v, str):
        return _quote(v)
    if isinstance(v, list):
        return "[" + ",".join(snbt(x) for x in v) + "]"
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            key = k if k and all(c in _BARE_KEY_OK for c in k) else _quote(k)
            parts.append(f"{key}:{snbt(val)}")
        return "{" + ",".join(parts) + "}"
    raise ValueError(f"Can't serialize {type(v).__name__} to SNBT.")
