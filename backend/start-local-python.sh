#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${BACKEND_VENV_DIR:-$SCRIPT_DIR/.venv}"
PYTHON_BIN="${DICE_PYTHON_BIN:-}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
ENABLE_SCHEDULER="${ENABLE_SCHEDULER:-false}"
NEEDS_INSTALL=0
SETUP_ONLY=0
REQUIREMENTS_STAMP="$VENV_DIR/.requirements-checksum"
REQUIREMENTS_CHECKSUM="$(cksum < "$SCRIPT_DIR/requirements.txt")"

usage() {
  cat <<'EOF'
Usage: ./start-local-python.sh [--enable-scheduler <true|false>] [--setup-only]
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --enable-scheduler)
      if [ "$#" -lt 2 ]; then
        printf 'Error: --enable-scheduler requires a value (true or false).\n' >&2
        usage
        exit 1
      fi
      case "$2" in
        true|false)
          ENABLE_SCHEDULER="$2"
          shift 2
          ;;
        *)
          printf 'Error: --enable-scheduler must be true or false.\n' >&2
          usage
          exit 1
          ;;
      esac
      ;;
    --setup-only)
      SETUP_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Error: unknown argument: %s\n' "$1" >&2
      usage
      exit 1
      ;;
  esac
done

if [ -z "$PYTHON_BIN" ]; then
  if command -v python3.12 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.12)"
  elif command -v python3.13 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.13)"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    printf 'Python 3.12 or 3.13 is required.\n' >&2
    exit 1
  fi
fi

PYTHON_VERSION="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "$PYTHON_VERSION" in
  3.12|3.13) ;;
  *)
    printf 'Python 3.12 or 3.13 is required; found %s at %s.\n' "$PYTHON_VERSION" "$PYTHON_BIN" >&2
    exit 1
    ;;
esac

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  NEEDS_INSTALL=1
fi

if ! "$VENV_DIR/bin/python" -c "import uvicorn" >/dev/null 2>&1; then
  NEEDS_INSTALL=1
fi

if [ ! -f "$REQUIREMENTS_STAMP" ] || [ "$(cat "$REQUIREMENTS_STAMP")" != "$REQUIREMENTS_CHECKSUM" ]; then
  NEEDS_INSTALL=1
fi

if [ "$NEEDS_INSTALL" -eq 1 ]; then
  # `python -m pip` remains portable when a bind-mounted venv was originally
  # created at a different absolute workspace path.
  "$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"
  printf '%s\n' "$REQUIREMENTS_CHECKSUM" > "$REQUIREMENTS_STAMP"
fi

if [ "$SETUP_ONLY" -eq 1 ]; then
  printf 'Backend virtual environment is ready.\n'
  exit 0
fi

if [ "${DICE_LOCAL_HARNESS:-}" != "true" ] && [ ! -f "$SCRIPT_DIR/.env.local" ]; then
  printf 'Warning: backend/.env.local not found. The app may fail if required env vars are missing.\n'
fi

export ENABLE_SCHEDULER
exec "$VENV_DIR/bin/python" -m uvicorn main:app --host "$HOST" --port "$PORT" --app-dir "$SCRIPT_DIR"
