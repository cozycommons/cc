"""The portable package must contain patched movies before offering faster rates."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("use_override", [False, True])
def test_importer_copies_overrides_and_records_timing_support(tmp_path, use_override):
    archive = tmp_path / "archive"
    (archive / "files").mkdir(parents=True)
    player = tmp_path / "player"
    player.mkdir()
    (player / "ruffle.js").write_text("player")
    key = tmp_path / "wire-key"
    key.write_text("test-package-key")
    movie_path = "private.test/assets/games/Sprint/game.swf"
    page = 'swfobject.embedSWF("https://' + movie_path + '?version=0", "game");'
    rows = []
    for name, body, kind in [
        ("private.test/games/sprint", page.encode(), "text/html"),
        (movie_path, b"original movie", "application/x-shockwave-flash"),
        ("opponents.test/battle/0.xml", b"unused opponent", "text/xml"),
    ]:
        digest = hashlib.sha256(body).hexdigest()
        (archive / "files" / digest).write_bytes(body)
        rows.append({"key": name, "status": 200, "file": digest, "contentType": kind})
    (archive / "index.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
    destination = tmp_path / "package"
    command = [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/import-arcade-package.py"),
               str(archive), str(destination), "--wire-key-file", str(key), "--ruffle", str(player)]
    if use_override:
        overrides = tmp_path / "overrides"
        movie = overrides / movie_path
        movie.parent.mkdir(parents=True)
        movie.write_bytes(b"timing corrected movie")
        command.extend(["--overrides", str(overrides)])
    subprocess.run(command, check=True, capture_output=True, timeout=20)
    manifest = json.loads((destination / "manifest.json").read_text())
    assert manifest["frame_rates"] == ([0, 60, 100, 144, 240] if use_override else [0])
    assert len(manifest["assets"]) == 1
    stored = manifest["assets"][manifest["entry"]]["file"]
    assert (destination / "files" / stored).read_bytes() == (
        b"timing corrected movie" if use_override else b"original movie")
