# Home GPU renderer

The local-spool worker runs one edit at a time and writes one H.264/AAC MP4. Automatic production dispatch and publication are a separate milestone; this service does not receive live uploads yet.

## Install

Requires Ubuntu x86_64, working NVIDIA drivers, Python 3.10+, curl, tar/xz, and a user systemd session. Docker, sudo, a VPN and inbound ports are not needed. The PC makes outbound HTTPS requests to the public GitHub repository. From a Mac or Linux checkout:

```bash
scripts/crowdset-gpu-worker.sh pc
```

The installer downloads a checksum-pinned FFmpeg build with NVENC from BtbN/FFmpeg-Builds, tests hardware encoding, and enables `crowdset-gpu-worker.service` plus `crowdset-gpu-update.timer` under the SSH user's account. The regular imageio FFmpeg bundle does not include NVENC. Existing installations are not overwritten by the installer.

The installed paths are `~/.local/share/crowdset-worker/{gpu_worker.py,gpu_updater.py,ffmpeg,data}` and `~/.config/systemd/user/crowdset-gpu-worker.service`. The service starts on boot if that user's `loginctl show-user USER -p Linger` reports `yes`; otherwise it starts with the user session.

## Queue an edit

Copy normalized source MP4s into `data/sources/<sha256>.mp4`. Each source must have one H.264 1080p24 yuv420p SDR picture stream, square pixels, and no display rotation. The official source also needs one AAC soundtrack covering the complete output. Normalize original iPhone/HDR media before this stage.

A manifest uses integer frames on the shared 24 fps clock. Segments are concatenated in listed order; `start_frame` indexes that source's picture, while audio always starts at zero in the official source. For example:

```json
{
  "version": 1,
  "audio_source": "official",
  "sources": {
    "official": {"sha256": "<64 lowercase hex characters>", "bytes": 123456},
    "friend": {"sha256": "<64 lowercase hex characters>", "bytes": 23456}
  },
  "segments": [
    {"source": "official", "start_frame": 0, "frames": 720},
    {"source": "friend", "start_frame": 0, "frames": 720},
    {"source": "official", "start_frame": 1440, "frames": 1440}
  ]
}
```

Use a fresh UUID hex job ID. Write the JSON as `data/inbox/<job>.tmp`, then rename it to `<job>.json` on the same filesystem to submit atomically. Maximums: 128 sources, 512 picture intervals, four hours of output. The renderer checks source size/hash before encoding, deadlines, disk space, byte ceilings, output frame count and duration. A source or output validation failure cannot replace another completed job.

The result is `data/outputs/<job>.mp4`; `data/completed/<job>.json` contains output SHA256, size, duration, frame count, encoder and elapsed seconds. `data/completed/<job>.manifest.json` retains the edit. Failed/interrupted jobs appear under `data/failed`; their temporary files remain under `data/work`. A retry uses a new job ID. Sources and outputs are never automatically deleted; reclaim confirmed disposable local copies when admission rejects new work. These limits do not change production's 100 GB R2 allowance.

## Operations

```bash
ssh pc 'systemctl --user status crowdset-gpu-worker.service --no-pager'
ssh pc 'cat ~/.local/share/crowdset-worker/data/status.json'
ssh pc 'journalctl --user -u crowdset-gpu-worker.service -n 30 --no-pager'
```

Inspect `status.json` and the inbox/running directories before stopping or upgrading. A normal stop finishes the active render before exiting and does not claim another job. The service allows four hours for that drain. A forced stop preserves unfinished work; startup records it as interrupted instead of publishing incomplete video. Wait for an idle, empty queue before replacing code or FFmpeg. The service is limited to 4 CPU cores, 8 GiB RAM, and one GPU render at a time.

For CPU-only correctness testing, invoke the Python worker with `--encoder libx264`, `--root`, `--ffmpeg`, and `--ffprobe`. Production GPU service explicitly uses NVENC and never silently falls back to CPU encoding.

## Initial verification

On 2026-10-21, `pc` (Ubuntu, RTX 3070 Ti 8 GiB, NVIDIA driver 590.48.01, 32 GiB RAM, 16 logical CPUs) rendered a synthetic 120-second edit with three picture intervals in 9.67 seconds, including input hashing/probing and output validation: about 12.4× real time. The output contained exactly 2,880 video packets/frames; sampled pictures matched the intended sources, and its copied AAC payload hash matched the official source exactly. This is a synthetic benchmark, not a timing guarantee for the full ISOKNOCK set or network transfers.

After restarting with a simulated interrupted job, the service retained the unfinished manifest/work, recorded the interruption, and successfully rendered another two-minute edit in 9.69 seconds with the same output SHA256. The idle service was enabled, its installed source matched the checkout SHA256, and systemd unit validation passed. The 15 new focused tests and all 217 local Crowdset tests passed. No live production jobs, originals, R2 objects or credentials were changed for these tests.

## Automatic updates

The user systemd timer checks public `cozycommons/cc` main about every five minutes (plus up to 30 seconds jitter). Changes must be merged/pushed to **main**. With project-aware CI, `changes`, `frontend`, and `backend` must pass on that exact commit; the final gates verify that every selected job passed and every skipped job was deliberately excluded. Only the known conditional CI jobs may report `skipped`. Other GitHub Actions checks must pass. Older commits without project selection still require successful frontend, backend, Crowdset container and Ubuntu checks. Feature branches are never deployed. No GitHub token is needed; normal polling uses at most two API requests per interval, within the anonymous allowance when this is its only API traffic.

The updater stages the two Python modules and three service/timer definitions, checks Python syntax/imports and systemd unit validity, then asks the worker to pause claims after finishing its current job. If a render is still running, the update waits for the next timer run without stopping it. The next update installs files with the spool locked, restarts the service, and verifies the new process writes a fresh healthy status. Identical worker bundles are recorded without restarting. Queue manifests, cached sources and completed videos remain in place.

A failed startup restores the previous code and units. Interrupted installations recover their backup on the next timer run, including when GitHub is unreachable. A release that fails startup is not retried until main changes. The updater itself is part of the release bundle. The Python 3.10+ standard-library runtime and checksum-pinned FFmpeg installation are separate prerequisites; changes requiring a new runtime/binary need an explicit migration.

```bash
ssh pc 'systemctl --user list-timers crowdset-gpu-update.timer --no-pager'
ssh pc 'cat ~/.local/share/crowdset-worker/update-status.json'
ssh pc 'cat ~/.local/share/crowdset-worker/deployment.json'
ssh pc 'journalctl --user -u crowdset-gpu-update.service -n 30 --no-pager'
```

`deployment.json` records the installed commit and file hashes. `update-status.json` distinguishes waiting for CI, waiting for a release, waiting for a render, current and rolled-back releases. Initially the installed, tested checkout is identified as a bootstrap release until its first main deployment is approved.

Live verification on the PC confirmed that an update waited for a two-minute GPU job to finish, preserved its output, installed and restarted a healthy service, then rolled back a deliberately broken synthetic release. The update timer was enabled and its first outbound check waited for main CI. It does not yet add production job dispatch; only worker deployment is automated.

## Production remote mode

The optional remote mode keeps large originals, audio caches, normalization and render files on the PC. The browser uploads parts directly to R2 using expiring part URLs. The API maintains reservations, multipart completion and renewable job claims. The PC holds a job-control token, never R2 credentials. Published media is served through authorized R2 redirects. Existing local mode remains available when the feature is disabled.

Runtime prerequisites are Python 3.11+, Node.js 22+ on the worker PATH for YouTube challenge handling, and `backend/requirements-crowdset.txt` in a dedicated processing venv. Pin/update those independently from source releases. The release updater installs all required `crowdset/` processing modules with the renderer, preserves active work, and handles expansion from the earlier five-file bundle.

Production Coolify runtime settings: `CROWDSET_REMOTE_WORKER=1`, `CROWDSET_WORKER_TOKEN=<random worker-only secret>`. Preserve existing R2 configuration and request ledger; do not initialize new counters. Configure bucket CORS for exactly `https://cozycommons.dev`, methods GET/HEAD/PUT, allowed headers Content-Type/Range, exposed headers ETag/Content-Length/Content-Range. Public bucket access remains disabled.

Remote mode allows recordings up to 8 GiB by default, including full YouTube sets. Local R2 processing retains its 3 GiB per-recording cap. The configured total R2 budget, worker spool quota and disk free floor still apply independently; enabling remote mode does not increase the storage budget.

The PC keeps up to 16 GiB of verified source recordings in its spool cache. Analysis, preview generation and video assembly share temporary hard links to those bytes, so stage cleanup does not trigger repeated R2 downloads. Unused cache entries are evicted oldest first; active stage files and authoritative R2 originals are preserved. The cache remains subject to the worker's 60 GiB spool quota and disk free floor.

PC `~/.local/share/crowdset-worker/worker.env` (mode 0600):

```text
CROWDSET_WORKER_URL=https://cozycommons.dev
CROWDSET_WORKER_TOKEN=<same worker-only secret>
CROWDSET_WORKER_PYTHON=/home/jason/.local/share/crowdset-worker/processing-venv/bin/python
IMAGEIO_FFMPEG_EXE=/home/jason/.local/share/crowdset-worker/ffmpeg/bin/ffmpeg
PATH=/home/jason/.local/share/crowdset-worker/node/bin:/usr/local/bin:/usr/bin:/bin
```

The systemd unit reads this optional file. After installing prerequisites and a CI-approved complete source bundle, activate remote mode on production, then restart the idle PC service. Verify a newly created test set through browser direct upload, worker claim/validation, rendering and playback. Never test by rebuilding the existing live ISOKNOCK set. Inspect `data/status.json`, per-job metadata under `data/remote/`, and the set’s job record under production `/data/remote-jobs/`. Old production caches are retained during rollout; new remote work must not create media files there. Signed URLs are capabilities and must not be printed in logs or copied into error notices.

### Shared project jobs

The remote worker now uses the shared compute runner. It can alternate Crowdset
with project-declared jobs using the same execution slot. See
[Shared project jobs](../compute.md) for declarations, configuration, capacity
settings, and the two-cycle updater transition.

## Prioritizing an interactive model session

The shared worker supports a separate, durable GPU-session reservation that
finishes an active render before pausing new claims. It holds the reservation
through the model server's lifetime, including idle periods with resident
weights. See [Exclusive interactive GPU sessions](../compute.md#exclusive-interactive-gpu-sessions)
for the Linux/systemd supervisor, acknowledgment barrier, release transition,
and fail-closed recovery rules. The initial policy pauses CPU-only jobs too;
it does not add a new queue or cancel work. Activate it only through the normal
CI-approved-main worker release path.
