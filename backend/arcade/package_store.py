"""Private package installation through Commons Storage; only playback cache is local."""
import hashlib
import io
import json
import re
import shutil
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .package import Package

BUCKET = "arcade-packages"
MAX_UPLOAD = 40 * 1024 * 1024
MAX_UNPACKED = 160 * 1024 * 1024


def unpack(content: bytes, destination: Path) -> Package:
    if len(content) > MAX_UPLOAD:
        raise ValueError("Game package exceeds 40 MB")
    total = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode="r|gz") as archive:
        for count, member in enumerate(archive):
            if count > 10000:
                raise ValueError("Too many package files")
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Invalid package path")
            if member.isdir():
                continue
            if not member.isfile() or not name.parts or name.parts[0] not in {"manifest.json", "files", "player"}:
                raise ValueError("Unexpected package entry")
            if (name.parts[0] == "manifest.json" and len(name.parts) != 1) or (name.parts[0] != "manifest.json" and len(name.parts) < 2):
                raise ValueError("Invalid package layout")
            total += member.size
            if total > MAX_UNPACKED:
                raise ValueError("Expanded game package exceeds 160 MB")
            target = destination.joinpath(*name.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    if not (destination / "manifest.json").is_file():
        raise ValueError("Missing package manifest")
    bundle = Package(destination)
    manifest = bundle.manifest
    if not isinstance(manifest, dict):
        raise ValueError("Invalid package manifest")
    if not isinstance(manifest.get("origins"), dict) or not isinstance(manifest.get("callbacks"), dict):
        raise ValueError("Missing compatibility configuration")
    if not isinstance(manifest.get("assets"), dict) or manifest.get("entry") not in manifest["assets"]:
        raise ValueError("Missing game entry")
    if not isinstance(manifest.get("wire_key"), str) or not 4 <= len(manifest["wire_key"].encode()) <= 56:
        raise ValueError("Invalid game compatibility key")
    if not (destination / "player/ruffle.js").is_file():
        raise ValueError("Missing browser player")
    for key, entry in manifest["assets"].items():
        if not isinstance(entry, dict):
            raise ValueError("Invalid asset entry")
        digest = entry.get("file", "")
        if not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("Invalid asset digest")
        found = bundle.file(key)
        if not found or hashlib.sha256(found[0].read_bytes()).hexdigest() != digest:
            raise ValueError("Game asset is missing or damaged")
    return bundle


class PackageStore:
    def __init__(self, client):
        self.client = client
        self.cache = tempfile.TemporaryDirectory(prefix="cozy-arcade-")
        self.lock = threading.RLock()
        self.active = None
        self.checked_at = 0.0
        self.loaded = {}

    def installed(self) -> bool:
        return bool(self.client.table("arcade_package").select("digest").eq("singleton", True).limit(1).execute().data)

    def current(self) -> Package | None:
        with self.lock:
            if time.monotonic() - self.checked_at > 5:
                rows = self.client.table("arcade_package").select("digest").eq("singleton", True).limit(1).execute().data
                self.active = rows[0]["digest"] if rows else None
                self.checked_at = time.monotonic()
            if not self.active:
                return None
            if self.active not in self.loaded:
                content = self.client.storage.from_(BUCKET).download(self.active + ".tar.gz")
                if hashlib.sha256(content).hexdigest() != self.active:
                    raise ValueError("Stored game package is damaged")
                self.loaded[self.active] = self.prepare(content)
            return self.loaded[self.active]

    def prepare(self, content: bytes) -> Package:
        directory = Path(tempfile.mkdtemp(dir=self.cache.name))
        try:
            return unpack(content, directory)
        except (ValueError, OSError, tarfile.TarError, KeyError, TypeError):
            shutil.rmtree(directory)
            raise

    def install(self, content: bytes, user_id: str) -> None:
        with self.lock:
            bundle = self.prepare(content)
            digest = hashlib.sha256(content).hexdigest()
            # Activate only after the complete archive was validated and uploaded.
            self.client.storage.from_(BUCKET).upload(digest + ".tar.gz", content, file_options={
                "content-type": "application/gzip", "upsert": "true",
            })
            self.client.table("arcade_package").upsert({
                "singleton": True, "digest": digest, "installed_by": user_id,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            self.loaded[digest] = bundle
            self.active, self.checked_at = digest, time.monotonic()
