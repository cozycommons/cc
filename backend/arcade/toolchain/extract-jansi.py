"""Image build step: copy Jansi's Linux native library out of the JPEXS bundle."""
import platform
import sys
import zipfile
from pathlib import Path

lib, target = Path(sys.argv[1]), Path(sys.argv[2])
arch = {"x86_64": "x86_64", "aarch64": "arm64"}[platform.machine()]
(jar,) = lib.glob("jansi-*.jar")
target.mkdir(parents=True)
with zipfile.ZipFile(jar) as archive:
    (target / "libjansi.so").write_bytes(
        archive.read(f"org/fusesource/jansi/internal/native/Linux/{arch}/libjansi.so"))
