"""A synthetic hostile movie and package for the player-origin proof.

The movie is generated AVM1 bytecode, not game content. On its first frame it
tries what an uploaded movie could do with page or Commons standing: call into
the page through ExternalInterface and a javascript: URL, navigate the top
window, and read Commons API responses with loadVariables. Permitted loads of
its own origin before and after those attempts show that the script ran.

Write a local proof package (never commit it):
    python tests/arcade_hostile_movie.py OUT_DIR --ruffle PLAYER_DIR --api https://api.example.test
"""
import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path

MARKER = "window.top.document.title='hostile-movie-ran'"


def _push_strings(*values: str) -> bytes:
    body = b"".join(b"\x00" + value.encode() + b"\x00" for value in values)
    return b"\x96" + struct.pack("<H", len(body)) + body


def _push_int(value: int) -> bytes:
    return b"\x96\x05\x00\x07" + struct.pack("<i", value)


def _get_url(url: str, target: str) -> bytes:
    body = url.encode() + b"\x00" + target.encode() + b"\x00"
    return b"\x83" + struct.pack("<H", len(body)) + body


def _load_variables(url: str) -> bytes:
    # loadVariablesNum(url, 0): GetURL2 pops the level target, then the URL; 0x80
    # is its load-variables flag. (Ruffle reads a bare "_root" string as navigation.)
    return _push_strings(url, "_level0") + b"\x9a\x01\x00\x80"


def _tag(code: int, body: bytes) -> bytes:
    return struct.pack("<H", (code << 6) | 0x3F) + struct.pack("<I", len(body)) + body


def attempts(api: str) -> dict[str, str]:
    """Request URLs the movie makes, keyed by what each one shows."""
    return {
        "ran-start": "/arcade/assets/hostile-ran?step=start",
        "commons-api": api.rstrip("/") + "/arcade/package?hostile=api",
        "player-host-commons-route": "/arcade/profile?hostile=player",
        "ran-end": "/arcade/assets/hostile-ran?step=end",
    }


def hostile_swf(api: str) -> bytes:
    urls = attempts(api)
    actions = b"".join([
        _load_variables(urls["ran-start"]),
        # flash.external.ExternalInterface.call("eval", MARKER)
        _push_strings(MARKER, "eval"), _push_int(2), _push_strings("flash"), b"\x1c",
        _push_strings("external"), b"\x4e", _push_strings("ExternalInterface"), b"\x4e",
        _push_strings("call"), b"\x52", b"\x17",
        _get_url("javascript:" + MARKER, ""),
        _get_url("https://hostile.invalid/phish", "_top"),
        _load_variables(urls["commons-api"]),
        _load_variables(urls["player-host-commons-route"]),
        _load_variables(urls["ran-end"]),
        b"\x00",
    ])
    tags = b"".join([
        _tag(69, struct.pack("<I", 0x01)),  # FileAttributes: AVM1, network sandbox
        _tag(9, b"\x20\x10\x10"),  # SetBackgroundColor
        _tag(12, actions),  # DoAction
        struct.pack("<H", 1 << 6),  # ShowFrame
        struct.pack("<H", 0),  # End
    ])
    # 550x400 stage in twips as a 15-bit RECT, then 24 fps and one frame.
    bits = "01111" + "".join(format(value, "015b") for value in (0, 11000, 0, 8000))
    bits += "0" * (-len(bits) % 8)
    rect = int(bits, 2).to_bytes(len(bits) // 8, "big")
    body = rect + struct.pack("<HH", 24 << 8, 1) + tags
    return b"FWS" + bytes([8]) + struct.pack("<I", 8 + len(body)) + body


def write_package(destination: Path, ruffle: Path, api: str, trusted: bool = False) -> None:
    """A local package with the synthetic movie as its entry, untrusted by default."""
    movie = hostile_swf(api)
    digest = hashlib.sha256(movie).hexdigest()
    (destination / "files").mkdir(parents=True)
    (destination / "files" / digest).write_bytes(movie)
    shutil.copytree(ruffle, destination / "player")
    manifest = {"version": 2, "trusted": trusted, "entry": "hostile.swf", "frame_rates": [0, 60, 100, 144, 240],
                "origins": {}, "callbacks": {}, "wire_key": "synthetic-test-key",
                "assets": {"hostile.swf": {"file": digest, "content_type": "application/x-shockwave-flash"}}}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("destination", type=Path)
    parser.add_argument("--ruffle", type=Path, required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--trusted", action="store_true", help="control run with the legacy trusted config")
    options = parser.parse_args()
    write_package(options.destination, options.ruffle, options.api, options.trusted)
