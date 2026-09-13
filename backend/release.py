"""Start an incoming backend only after its own migrations have succeeded."""
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    # A failure exits before the HTTP listener exists. The runner holds a
    # database advisory lock and validates both migration families.
    subprocess.run(
        [sys.executable, str(root / "migration_runner.py"), "--family", "all"],
        cwd=root, check=True,
    )
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "main:app",
                            "--host", "0.0.0.0", "--port", "8000"])


if __name__ == "__main__":
    main()
