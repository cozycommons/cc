"""Seed a newly provisioned app's local Git repository."""

from pathlib import Path
import shutil
import subprocess

root = Path("/workspace")
if (root / ".git").exists():
    raise SystemExit("App already has a Git repository")
for name, source in [
    ("AGENTS.md", "/opt/app-AGENTS.md"),
    (".gitignore", "/opt/app-gitignore"),
]:
    if not (root / name).exists():
        shutil.copyfile(source, root / name)


def git(*args):
    subprocess.run(["git", "-C", str(root), *args], check=True)


git("init", "--initial-branch=main")
git("config", "user.name", "Cozy Commons")
git("config", "user.email", "apps@cozycommons.invalid")
git("add", "AGENTS.md", ".gitignore")
git("commit", "-m", "Initialize app workspace")
