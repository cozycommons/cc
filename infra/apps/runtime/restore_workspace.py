"""Stage a complete extraction before touching current app data."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def restore(workspace, archive):
    workspace = Path(workspace)
    staging = Path(tempfile.mkdtemp(prefix=".commons-restore-", dir=workspace))
    incoming, previous = staging / "incoming", staging / "previous"
    incoming.mkdir()
    previous.mkdir()
    saved, installed = [], []
    try:
        # Same volume: extraction failure (including disk full) leaves originals
        # untouched, and replacement uses renames rather than another full copy.
        subprocess.run(["tar", "xzf", str(archive), "-C", str(incoming)], check=True)
        if (incoming / staging.name).exists() or (incoming / staging.name).is_symlink():
            raise ValueError("Archive conflicts with restore staging directory")
        try:
            for path in workspace.iterdir():
                if path != staging:
                    path.rename(previous / path.name)
                    saved.append(path.name)
            for path in incoming.iterdir():
                path.rename(workspace / path.name)
                installed.append(path.name)
        except Exception:
            for name in reversed(installed):
                (workspace / name).rename(incoming / name)
            for name in reversed(saved):
                (previous / name).rename(workspace / name)
            saved.clear()
            raise
    except Exception:
        # If rollback itself fails, keep previous files for manual recovery.
        if not saved:
            shutil.rmtree(staging)
        raise
    else:
        shutil.rmtree(staging)


if __name__ == "__main__":
    restore("/workspace", sys.argv[1])
