#!/usr/bin/env bash
# Install the local-spool GPU renderer on an Ubuntu x86_64 host over SSH.
set -euo pipefail
worker_host=${1:?Usage: scripts/crowdset-gpu-worker.sh SSH_HOST}
case "$worker_host" in -*|*[!a-zA-Z0-9_.@:-]*) echo 'Use an SSH hostname or alias.' >&2; exit 1 ;; esac
worker_repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ssh "$worker_host" 'test ! -x "$HOME/.local/share/crowdset-worker/ffmpeg/bin/ffmpeg" || { echo "Worker already installed; retain it and upgrade only when its queue is idle." >&2; exit 1; }; mkdir -p "$HOME/.local/share/crowdset-worker" "$HOME/.config/systemd/user"; chmod 700 "$HOME/.local/share/crowdset-worker"'
scp "$worker_repo/backend/crowdset/gpu_worker.py" "$worker_repo/backend/crowdset/gpu_updater.py" "$worker_host:.local/share/crowdset-worker/"
ssh "$worker_host" 'mkdir -p "$HOME/.local/share/crowdset-worker/crowdset"'
for worker_module in audio video progress limits config storage blobs r2 worker composition previews timestamps gpu_worker remote_agent youtube compute_jobs; do
    scp "$worker_repo/backend/crowdset/$worker_module.py" "$worker_host:.local/share/crowdset-worker/crowdset/"
done
ssh "$worker_host" 'mkdir -p ~/.local/share/crowdset-worker/compute'
for worker_module in __init__ jobs queue client runner execute worker example process; do
    scp "$worker_repo/backend/compute/$worker_module.py" "$worker_host:.local/share/crowdset-worker/compute/"
done
for worker_unit in crowdset-gpu-worker.service crowdset-gpu-update.service crowdset-gpu-update.timer; do
    scp "$worker_repo/scripts/systemd/$worker_unit" "$worker_host:.config/systemd/user/$worker_unit"
done
ssh "$worker_host" 'bash -s' <<'REMOTE'
set -euo pipefail
test "$(uname -s)" = Linux && test "$(uname -m)" = x86_64
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
umask 077
worker_home="$HOME/.local/share/crowdset-worker"
worker_stage=$(mktemp -d "$worker_home/install.XXXXXX")
trap 'rm -rf "$worker_stage"' EXIT
curl --fail --location --silent --show-error 'https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-21-13-06/ffmpeg-n8.1.3-20-gc8de997cb1-linux64-gpl-8.1.tar.xz' -o "$worker_stage/ffmpeg.tar.xz"
python3 - "$worker_stage/ffmpeg.tar.xz" <<'PY'
import hashlib,sys
with open(sys.argv[1], 'rb') as source:
    value = hashlib.sha256()
    for part in iter(lambda: source.read(1024 ** 2), b''):
        value.update(part)
if value.hexdigest() != '35168ba5f8edfa264eb2e2e3071d1b9d67d88ae667b665b284cb4be7f68ab23c':
    raise SystemExit('FFmpeg archive checksum mismatch')
PY
mkdir -p "$worker_home/ffmpeg"
tar -xJf "$worker_stage/ffmpeg.tar.xz" --strip-components=1 -C "$worker_home/ffmpeg"
"$worker_home/ffmpeg/bin/ffmpeg" -v error -f lavfi -i color=s=1920x1080:r=24 -t 1 -c:v h264_nvenc -f null -
systemctl --user daemon-reload
systemctl --user enable --now crowdset-gpu-worker.service crowdset-gpu-update.timer
systemctl --user status crowdset-gpu-worker.service --no-pager
loginctl show-user "$USER" -p Linger
REMOTE
