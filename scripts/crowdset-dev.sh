#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.crowdset-venv"
case "${1:-run}" in
  setup)
    PYTHON=""
    for candidate in python3.12 python3.13 python3.14 python3.11 python3; do
      if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        PYTHON="$candidate"
        break
      fi
    done
    if [ -z "$PYTHON" ]; then
      echo "Crowdset requires Python 3.11 or newer. Install Python 3.12, then retry setup." >&2
      exit 1
    fi
    "$PYTHON" -m venv "$VENV"
    "$VENV/bin/python" -m pip install -r "$ROOT/backend/requirements-crowdset.txt"
    ;;
  run)
    if [ ! -x "$VENV/bin/python" ]; then
      echo "Run bash scripts/crowdset-dev.sh setup first." >&2
      exit 1
    fi
    cd "$ROOT/backend"
    exec "$VENV/bin/python" -m uvicorn crowdset.app:app --host 127.0.0.1 --port 8010 --no-proxy-headers
    ;;
  *) echo "Usage: bash scripts/crowdset-dev.sh [setup|run]" >&2; exit 1 ;;
esac
