#!/usr/bin/env python3
"""Import an existing private archive into a portable package. Never downloads."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--wire-key-file", required=True, type=Path)
    parser.add_argument("--ruffle", required=True, type=Path)
    args = parser.parse_args()
    if not 4 <= len(args.wire_key_file.read_text().strip().encode()) <= 56:
        parser.error("wire key must contain 4–56 bytes")
    source = args.archive
    destination = args.destination
    if destination.exists():
        parser.error("destination must not already exist")
    index = {}
    if (source / "index.json").exists():
        index.update(json.loads((source / "index.json").read_text()))
    for line in (source / "index.jsonl").read_text().splitlines():
        row = json.loads(line)
        index[row["key"]] = row
    # Source hostnames belong to the private package, never runtime configuration.
    pages = [(key, value) for key, value in index.items() if key.endswith("/games/sprint")]
    if len(pages) != 1:
        parser.error("archive must contain exactly one Sprint page")
    page_key, page = pages[0]
    origin = page_key.split("/", 1)[0]
    html = (source / "files" / page["file"]).read_text()
    match = re.search(r'embedSWF\("https?://([^"]+?)(?:\?[^"]*)?"', html)
    if not match:
        parser.error("game entry point not found")
    movie = match.group(1)
    assets = {}
    origins = {}
    destination.mkdir(parents=True)
    (destination / "files").mkdir()
    for key, entry in index.items():
        if entry["status"] != 200:
            continue
        host, path = key.split("/", 1)
        if host != origin:
            continue  # Sprint has no opponent-recording dependency.
        # Website HTML and scripts are replaced by the Commons page.
        if entry.get("contentType", "").split(";")[0] in {"text/html", "text/javascript", "application/javascript"}:
            continue
        alias = origins.setdefault(host, "main" if host == origin else f"source{len(origins)}")
        logical = alias + "/" + path.split("?", 1)[0]
        blob = source / "files" / entry["file"]
        digest = hashlib.sha256(blob.read_bytes()).hexdigest()
        target = destination / "files" / digest
        if not target.exists():
            shutil.copyfile(blob, target)
        assets[logical] = {"file": digest, "content_type": entry["contentType"]}
    host, path = movie.split("/", 1)
    movie_key = origins[host] + "/" + path
    if movie_key not in assets:
        parser.error("movie missing from archive")
    shutil.copytree(args.ruffle, destination / "player")
    manifest = {"version": 1, "entry": movie_key, "origins": origins, "assets": assets,
                "wire_key": args.wire_key_file.read_text().strip(),
                "callbacks": {name: ("result" if "ShowResults" in name else "error" if "ShowHome" in name else "ignore")
                              for name in re.findall(r"function (js_[A-Za-z0-9_]+)\(", html)},
                "provenance": "Private imported archive. Original authorship and distribution terms remain applicable."}
    (destination / "manifest.json").write_text(json.dumps(manifest))
    print(f"Imported {len(assets)} files into {destination}")

if __name__ == "__main__":
    main()
