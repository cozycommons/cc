#!/usr/bin/env python3
"""Measure a synthetic long video rendition in an isolated temporary directory."""
import argparse
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import imageio_ffmpeg
from crowd_set import video
from crowd_set.limits import Limits
from crowd_set.storage import OriginalStore

parser = argparse.ArgumentParser()
parser.add_argument('--seconds', type=int, default=7200)
parser.add_argument('--report', type=Path, required=True)
args = parser.parse_args()
if not 1 <= args.seconds <= 7200:
    parser.error('seconds must be between 1 and 7200')
with tempfile.TemporaryDirectory(prefix='crowd-set-video-capacity-') as temporary:
    root = Path(temporary)
    originals = OriginalStore(root)
    folder = root / 'set'
    folder.mkdir()
    audio = folder / 'pending.wav'
    with wave.open(str(audio), 'wb') as output:
        output.setparams((1, 2, 32000, 0, 'NONE', 'not compressed'))
        for _ in range(args.seconds):
            output.writeframes(b'\0' * 64000)
    seed = root / 'seed.mp4'
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', f'testsrc2=s={video.WIDTH}x{video.HEIGHT}:r=24:d=5',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-threads', '1', str(seed)], check=True, timeout=30)
    item = {'id': 'motion', 'file': 'motion.mp4', 'name': 'motion.mp4', 'role': 'crowd', 'included': True,
            'duration': args.seconds, 'alignment': {'status': 'matched', 'offset_seconds': 0},
            'video': {'start': 0, 'end': args.seconds, 'audio_start': 0}}
    source = originals.destination('set', item)
    subprocess.run([ffmpeg, '-v', 'error', '-stream_loop', '-1', '-i', str(seed), '-i', str(audio),
                    '-t', str(args.seconds), '-c:v', 'copy', '-c:a', 'aac', '-threads', '1', str(source)], check=True, timeout=300)
    timeline = video.plan_video([item], {'duration': args.seconds, 'origin_seconds': 0})
    started = time.monotonic()
    video.render(timeline, [item], originals, 'set', folder, Limits())
    elapsed = time.monotonic() - started
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    report = {'duration_seconds': args.seconds, 'render_seconds': round(elapsed, 2),
              'width': video.WIDTH, 'height': video.HEIGHT,
              'output_bytes': (folder / 'pending.mp4').stat().st_size,
              'peak_child_rss_bytes': rss if sys.platform == 'darwin' else rss * 1024,
              'encoder_threads': 1, 'host_platform': sys.platform}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
