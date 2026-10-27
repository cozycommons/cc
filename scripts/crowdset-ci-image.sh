#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PLATFORM="${CROWDSET_CI_PLATFORM:-linux/amd64}"
export CROWDSET_CI_PLATFORM="$PLATFORM"
IMAGE="$(python3 - <<'PYTHON'
import hashlib
import os
from pathlib import Path
inputs = ('.github/images/crowdset-tests.Dockerfile',
          'backend/requirements-crowdset.txt', 'backend/crowdset/tests/requirements.txt')
digest = hashlib.sha256(os.environ['CROWDSET_CI_PLATFORM'].encode() + b'\0')
for name in inputs:
    digest.update(name.encode() + b'\0' + Path(name).read_bytes() + b'\0')
repository = os.environ.get('GITHUB_REPOSITORY', 'cozycommons/cc').lower()
print(f'ghcr.io/{repository}/crowdset-tests:deps-{digest.hexdigest()}')
PYTHON
)"
case "${1:-ref}" in
  ref) echo "$IMAGE" ;;
  build)
    docker build --platform "$PLATFORM" -f .github/images/crowdset-tests.Dockerfile -t "$IMAGE" .
    ;;
  prepare)
    if ! docker pull --platform "$PLATFORM" "$IMAGE"; then
      echo 'Prebuilt image unavailable; building the exact dependency image locally.'
      bash "$0" build
    fi
    ;;
  test)
    if [ -n "${RUNNER_TEMP:-}" ]; then
      MEDIA_TEMP="$RUNNER_TEMP/crowdset-media"
      mkdir -p "$MEDIA_TEMP"
      MEDIA_TEMP="$(cd "$MEDIA_TEMP" && pwd -P)"
      MEDIA_MOUNT="type=bind,source=$MEDIA_TEMP,target=/media-temp"
    else
      # Docker Desktop bind mounts do not preserve the spool's flock semantics.
      MEDIA_VOLUME="$(docker volume create)"
      trap 'docker volume rm "$MEDIA_VOLUME" >/dev/null || true' EXIT
      MEDIA_MOUNT="type=volume,source=$MEDIA_VOLUME,target=/media-temp"
      docker run --rm --platform "$PLATFORM" --mount "$MEDIA_MOUNT" "$IMAGE" \
        chown "$(id -u):$(id -g)" /media-temp
    fi
    docker run --rm --init --platform "$PLATFORM" --user "$(id -u):$(id -g)" \
      --mount "type=bind,source=$ROOT,target=/workspace,readonly" \
      --mount "$MEDIA_MOUNT" \
      --env TMPDIR=/media-temp "$IMAGE" sh -ec '
        df -h /tmp "$TMPDIR"
        python - <<"PYTHON"
import shutil
import tempfile
root = tempfile.gettempdir()
free = shutil.disk_usage(root).free
print(f"Media test temp directory: {root}; free: {free / 1024 ** 3:.1f} GiB")
if free < 16 * 1024 ** 3:
    raise SystemExit("Media tests require at least 16 GiB free on their temp filesystem")
PYTHON
        python -m pytest backend/crowdset/tests -q -n 2 --dist=worksteal \
          --max-worker-restart=0 --durations=15 -p no:cacheprovider --basetemp="$TMPDIR/pytest"
      '
    ;;
  *) echo "Usage: bash scripts/crowdset-ci-image.sh [ref|build|prepare|test]" >&2; exit 1 ;;
esac
