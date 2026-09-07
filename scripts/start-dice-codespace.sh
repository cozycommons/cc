#!/usr/bin/env bash
set -euo pipefail

if [[ "${CODESPACES:-}" != "true" ]]; then
  printf 'This launcher runs only inside GitHub Codespaces.\n' >&2
  exit 2
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_path="/tmp/dice-codespace.log"

python3 - "$repo_dir" "$log_path" <<'PY'
import subprocess
import sys

repo_dir, log_path = sys.argv[1:]
command = "scripts/dice-dev.sh setup && exec scripts/dice-dev.sh codespace"
with open(log_path, "wb", buffering=0) as log:
    subprocess.Popen(
        ["bash", "-lc", command],
        cwd=repo_dir,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
PY

printf 'Dice sandbox is starting. Log: %s\n' "$log_path"
