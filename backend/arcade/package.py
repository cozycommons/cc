"""Read an offline asset package. No upstream fetch path exists."""
import json
from pathlib import Path

class Package:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.manifest = json.loads((self.root / "manifest.json").read_text())

    def file(self, key: str) -> tuple[Path, str] | None:
        entry = self.manifest["assets"].get(key)
        if not entry:
            return None
        path = (self.root / "files" / entry["file"]).resolve()
        if not path.is_relative_to(self.root / "files") or not path.is_file():
            return None
        return path, entry["content_type"]
