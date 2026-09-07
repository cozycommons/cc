import os
import subprocess
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
SCRIPT = REPO_DIR / "scripts" / "dice-codespace-url.sh"


def _write_executable(path, contents):
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def test_codespace_url_prints_fresh_mobile_sign_in_link(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "gh",
        """#!/bin/sh
case "$1 $2" in
  "codespace view") printf 'Available\\n' ;;
  "codespace ssh") exit 0 ;;
  "codespace ports") printf 'https://dice-test-8080.app.github.dev\\n' ;;
  *) exit 1 ;;
esac
""",
    )
    _write_executable(
        fake_bin / "curl",
        """#!/bin/sh
printf 'HTTP/2 302\\r\\n'
printf 'location: https://github.dev/pf-signin?id=fresh-mobile-link\\r\\n'
""",
    )
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DICE_CODESPACE_MAX_ATTEMPTS": "1",
        "DICE_CODESPACE_POLL_SECONDS": "1",
    }

    result = subprocess.run(
        [str(SCRIPT), "dice-test"],
        cwd=REPO_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Dice sandbox: https://dice-test-8080.app.github.dev/dice" in result.stdout
    assert "Mobile GitHub sign-in: https://github.dev/pf-signin?id=fresh-mobile-link" in result.stdout


def test_codespace_url_rejects_an_unsafe_name_before_running_gh():
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "../not-a-codespace"],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Usage:" in result.stderr
