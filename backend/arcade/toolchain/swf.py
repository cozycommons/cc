"""SWF header checks and a synthetic test movie. Standard library only.

The header check is the host's first gate before any toolchain runs: it reads
only the first 8 bytes, so it never decompresses attacker-controlled data.
It is compatibility evidence, not proof the movie is safe.
"""
import struct
from dataclasses import dataclass

SIGNATURES = {b"FWS": "none", b"CWS": "zlib", b"ZWS": "lzma"}


class SwfRejected(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    compression: str
    version: int
    declared_length: int


def check(data: bytes, max_compressed: int, max_declared: int) -> Header:
    """Reject non-SWF input and movies whose declared size exceeds the limit.

    The declared length is the uncompressed size; refusing a large one stops
    a small CWS/ZWS bomb before JPEXS inflates it. The sandbox memory and
    tmpfs caps are the backstop for movies that lie about their length.
    """
    if len(data) > max_compressed:
        raise SwfRejected(f"movie is larger than {max_compressed} bytes")
    if len(data) < 8 or data[:3] not in SIGNATURES:
        raise SwfRejected("not a SWF movie")
    version = data[3]
    (declared,) = struct.unpack_from("<I", data, 4)
    if declared > max_declared:
        raise SwfRejected(f"movie declares {declared} uncompressed bytes (limit {max_declared})")
    if data[:3] == b"FWS" and declared != len(data):
        raise SwfRejected("uncompressed movie length does not match its header")
    return Header(SIGNATURES[data[:3]], version, declared)


# --- Synthetic movies for tests -------------------------------------------

def _tag(code: int, body: bytes) -> bytes:
    if len(body) < 0x3F:
        return struct.pack("<H", code << 6 | len(body)) + body
    return struct.pack("<HI", code << 6 | 0x3F, len(body)) + body


def _rect(x_min: int, x_max: int, y_min: int, y_max: int) -> bytes:
    values = (x_min, x_max, y_min, y_max)
    bits = max(abs(v) for v in values).bit_length() + 1
    stream = format(bits, "05b") + "".join(format(v & (1 << bits) - 1, f"0{bits}b") for v in values)
    stream += "0" * (-len(stream) % 8)
    return int(stream, 2).to_bytes(len(stream) // 8, "big")


def _u30(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


# AVM2 opcodes used below.
GETLOCAL0, PUSHSCOPE, POPSCOPE, RETURNVOID, RETURNVALUE = 0xD0, 0x30, 0x1D, 0x47, 0x48
CONSTRUCTSUPER, PUSHSTRING, GETSCOPEOBJECT, GETLEX, NEWCLASS, INITPROPERTY = 0x49, 0x2C, 0x65, 0x60, 0x58, 0x68
PACKAGE_NAMESPACE, QNAME, CLASS_SEALED, TRAIT_METHOD, TRAIT_CLASS = 0x16, 0x07, 0x01, 0x01, 0x04


def _abc(package: str, classes: list[tuple[str, str, str]]) -> bytes:
    """ABC for `package p { public class C { public function m():* { return "s"; } } }` per (C, m, s).

    Hand-assembled so tests own every byte of their movie. Stack and scope
    sizes follow what mxmlc emits for package-level classes.
    """
    strings: list[str] = []

    def string(text: str) -> int:
        if text not in strings:
            strings.append(text)
        return strings.index(text) + 1  # index 0 is the pool's implicit entry

    public_ns, package_ns = 1, 2
    namespaces = [string(""), string(package)]
    multinames: list[tuple[int, int]] = []

    def qname(ns: int, text: str) -> int:
        multinames.append((ns, string(text)))
        return len(multinames)

    obj = qname(public_ns, "Object")
    instances, statics, bodies, scripts = [], [], [], []
    for index, (name, method, value) in enumerate(classes):
        class_name, method_name, text = qname(package_ns, name), qname(public_ns, method), string(value)
        iinit, cinit, member, init = (4 * index + k for k in range(4))
        instances.append(_u30(class_name) + _u30(obj) + bytes([CLASS_SEALED]) + _u30(0) + _u30(iinit)
                         + _u30(1) + _u30(method_name) + bytes([TRAIT_METHOD]) + _u30(0) + _u30(member))
        statics.append(_u30(cinit) + _u30(0))
        # One script per class, as mxmlc emits; JPEXS imports class by class.
        scripts.append(_u30(init) + _u30(1) + _u30(class_name) + bytes([TRAIT_CLASS]) + _u30(1) + _u30(index))
        bodies += [
            (iinit, 1, 4, 5, bytes([GETLOCAL0, PUSHSCOPE, GETLOCAL0, CONSTRUCTSUPER, 0, RETURNVOID])),
            (cinit, 1, 3, 4, bytes([GETLOCAL0, PUSHSCOPE, RETURNVOID])),
            (member, 1, 4, 5, bytes([GETLOCAL0, PUSHSCOPE, PUSHSTRING]) + _u30(text) + bytes([RETURNVALUE])),
            # getscopeobject 0; getlex Object; pushscope; getlex Object; newclass; popscope; initproperty
            (init, 2, 1, 3, bytes([GETLOCAL0, PUSHSCOPE, GETSCOPEOBJECT, 0, GETLEX]) + _u30(obj)
             + bytes([PUSHSCOPE, GETLEX]) + _u30(obj) + bytes([NEWCLASS]) + _u30(index)
             + bytes([POPSCOPE, INITPROPERTY]) + _u30(class_name) + bytes([RETURNVOID])),
        ]
    pool = b"".join((
        _u30(0) * 3,  # int, uint and double pools
        _u30(len(strings) + 1), *(_u30(len(t.encode())) + t.encode() for t in strings),
        _u30(len(namespaces) + 1), *(bytes([PACKAGE_NAMESPACE]) + _u30(n) for n in namespaces),
        _u30(0),  # namespace sets
        _u30(len(multinames) + 1), *(bytes([QNAME]) + _u30(ns) + _u30(n) for ns, n in multinames),
    ))
    methods = _u30(len(bodies)) + (_u30(0) * 3 + b"\0") * len(bodies)  # no params, untyped, unnamed
    return b"".join((
        struct.pack("<HH", 16, 46), pool, methods, _u30(0),  # no metadata
        _u30(len(classes)), *instances, *statics,
        _u30(len(scripts)), *scripts,
        _u30(len(bodies)),
        *(_u30(m) + _u30(stack) + _u30(1) + _u30(low) + _u30(high) + _u30(len(code)) + code + _u30(0) + _u30(0)
          for m, stack, low, high, code in bodies),
    ))


def demo_movie(classes: list[tuple[str, str, str]], package: str = "demo", version: int = 10) -> bytes:
    """An uncompressed AS3 movie whose ABC holds the given synthetic classes.

    Each (Class, method, text) becomes a class whose method returns text.
    Tests decompile, edit and rebuild these instead of any original movie.
    """
    tags = b"".join((
        _tag(69, struct.pack("<I", 0x08)),  # FileAttributes: ActionScript 3
        _tag(9, bytes([0x20, 0x20, 0x30])),  # SetBackgroundColor
        _tag(82, struct.pack("<I", 1) + b"\0" + _abc(package, classes)),  # DoABC: lazy init, unnamed
        _tag(1, b""),  # ShowFrame
        _tag(0, b""),  # End
    ))
    body = _rect(0, 320 * 20, 0, 240 * 20) + struct.pack("<HH", 30 << 8, 1) + tags
    return b"FWS" + bytes([version]) + struct.pack("<I", 8 + len(body)) + body
