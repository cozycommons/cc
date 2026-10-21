# Home GPU renderer

The local-spool worker runs one edit at a time and writes one H.264/AAC MP4. Automatic production dispatch and publication are a separate milestone; this service does not receive live uploads yet.

## Install

Requires Ubuntu x86_64, working NVIDIA drivers, Python 3.10+, curl, tar/xz, and a user systemd session. Docker and sudo are not needed. From a Mac or Linux checkout:

```bash
scripts/crowdset-gpu-worker.sh pc
```

The installer downloads a checksum-pinned FFmpeg build with NVENC from BtbN/FFmpeg-Builds, tests hardware encoding, and enables `crowdset-gpu-worker.service` under the SSH user's account. The regular imageio FFmpeg bundle does not include NVENC. Existing installations are not overwritten by the installer.

The installed paths are `~/.local/share/crowdset-worker/{gpu_worker.py,ffmpeg,data}` and `~/.config/systemd/user/crowdset-gpu-worker.service`. The service starts on boot if that user's `loginctl show-user USER -p Linger` reports `yes`; otherwise it starts with the user session.

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

The result is `data/outputs/<job>.mp4`; `data/completed/<job>.json` contains output SHA256, size, duration, frame count, encoder and elapsed seconds. `data/completed/<job>.manifest.json` retains the edit. Failed/interrupted jobs appear under `data/failed`; their temporary files remain under `data/work`. A retry uses a new job ID. Sources and outputs are never automatically deleted; reclaim confirmed disposable local copies when admission rejects new work. These limits do not change production's 8 GB R2 allowance.

## Operations

```bash
ssh pc 'systemctl --user status crowdset-gpu-worker.service --no-pager'
ssh pc 'cat ~/.local/share/crowdset-worker/data/status.json'
ssh pc 'journalctl --user -u crowdset-gpu-worker.service -n 30 --no-pager'
```

Inspect `status.json` and the inbox/running directories before stopping or upgrading. Stopping interrupts the active render and preserves its work; startup records it as interrupted instead of publishing incomplete video. Wait for an idle, empty queue before replacing code or FFmpeg. The service is limited to 4 CPU cores, 8 GiB RAM, and one GPU render at a time.

For CPU-only correctness testing, invoke the Python worker with `--encoder libx264`, `--root`, `--ffmpeg`, and `--ffprobe`. Production GPU service explicitly uses NVENC and never silently falls back to CPU encoding.

## Initial verification

On 2026-10-21, `pc` (Ubuntu, RTX 3070 Ti 8 GiB, NVIDIA driver 590.48.01, 32 GiB RAM, 16 logical CPUs) rendered a synthetic 120-second edit with three picture intervals in 9.67 seconds, including input hashing/probing and output validation: about 12.4× real time. The output contained exactly 2,880 video packets/frames; sampled pictures matched the intended sources, and its copied AAC payload hash matched the official source exactly. This is a synthetic benchmark, not a timing guarantee for the full ISOKNOCK set or network transfers.

After restarting with a simulated interrupted job, the service retained the unfinished manifest/work, recorded the interruption, and successfully rendered another two-minute edit in 9.69 seconds with the same output SHA256. The idle service was enabled, its installed source matched the checkout SHA256, and systemd unit validation passed. The 15 new focused tests and all 217 local Crowdset tests passed. No live production jobs, originals, R2 objects or credentials were changed for these tests.
