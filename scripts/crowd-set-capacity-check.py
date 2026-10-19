#!/usr/bin/env python3
"""Synthetic capacity check in a disposable store; never touches the preview catalog."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def generate(path, seconds):
    rng = np.random.default_rng(20261018)
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        t = np.arange(3200) / 16000
        envelope = np.hanning(3200)
        for _ in range(seconds * 5):
            notes = rng.choice(np.arange(90, 4000, 37), 4, replace=False)
            values = sum(np.sin(2 * np.pi * note * t + rng.uniform(0, 6)) for note in notes)
            values *= envelope * rng.uniform(800, 2500)
            output.writeframesraw(np.clip(values, -32768, 32767).astype('<i2').tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clips', type=int, default=50)
    parser.add_argument('--anchor-minutes', type=int, default=120)
    parser.add_argument('--clip-minutes', type=int, default=5)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not 1 <= args.clips <= 63 or not 1 <= args.clip_minutes <= args.anchor_minutes <= 120:
        parser.error('Use 1–63 clips, with 1–120 minute durations and clips no longer than the anchor.')
    anchor_seconds = args.anchor_minutes * 60
    clip_seconds = args.clip_minutes * 60
    if anchor_seconds + args.clips * clip_seconds > 28800:
        parser.error('This check must fit the eight-hour aggregate duration limit.')
    with tempfile.TemporaryDirectory(prefix='crowd-set-capacity-') as temporary:
        root = Path(temporary)
        set_id = uuid4().hex
        directory = root / set_id
        directory.mkdir()
        originals = root / 'originals' / set_id
        originals.mkdir(parents=True)
        anchor = originals / 'anchor.wav.upload'
        print(f'Generating {args.anchor_minutes}-minute synthetic anchor and {args.clips} excerpts…', flush=True)
        generate(anchor, anchor_seconds)
        clips = [{'id': 'anchor', 'name': 'Released-set synthetic.wav', 'file': anchor.name, 'role': 'recording',
                  'included': True, 'bytes': anchor.stat().st_size, 'expected_duration': anchor_seconds}]
        offsets = np.linspace(0, anchor_seconds - clip_seconds, args.clips).astype(int)
        with wave.open(str(anchor), 'rb') as source:
            for index, offset in enumerate(offsets):
                path = originals / f'friend-{index}.wav.upload'
                source.setpos(int(offset) * 16000)
                with wave.open(str(path), 'wb') as output:
                    output.setparams(source.getparams())
                    output.writeframes(source.readframes(clip_seconds * 16000))
                clips.append({'id': f'friend-{index}', 'name': f'Friend {index}.wav', 'file': path.name, 'role': 'recording',
                              'included': True, 'bytes': path.stat().st_size, 'expected_duration': clip_seconds})
        data = {'id': set_id, 'name': 'Isolated capacity check', 'clips': clips}
        (directory / 'job.json').write_text(json.dumps(data))
        (directory / 'set.json').write_text(json.dumps(data))
        program = '''
import json, os, resource, signal, sys
from pathlib import Path
from crowd_set.worker import process
signal.signal(signal.SIGALRM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL))
signal.alarm(3600)
process(Path(sys.argv[1]))
factor = 1 if sys.platform == 'darwin' else 1024
peak = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss + resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) * factor
print(json.dumps({'conservative_peak_rss_bytes': peak}))
'''
        env = {key: value for key, value in os.environ.items() if not key.startswith('CROWD_SET_')}
        env.update(PYTHONPATH=str(ROOT / 'backend'), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
        started = time.monotonic()
        print('Running one worker; this may take several minutes…', flush=True)
        with (root / 'worker.log').open('w+') as log:
            result = subprocess.run([sys.executable, '-c', program, str(directory)], env=env, start_new_session=True,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=3660)
            log.seek(0)
            output = log.read()
        if result.returncode:
            raise RuntimeError(output[-6000:])
        resources = json.loads(output.splitlines()[-1])
        result = json.loads((directory / 'result.json').read_text())
        matches = [clip for clip in result['clips'][1:] if clip['alignment']['status'] == 'matched']
        errors = [abs(clip['alignment']['offset_seconds'] - int(offset))
                  for clip, offset in zip(result['clips'][1:], offsets) if clip['alignment']['status'] == 'matched']
        report = {'recordings': len(clips), 'anchor_seconds': anchor_seconds, 'clip_seconds': clip_seconds,
                  'elapsed_seconds': round(time.monotonic() - started, 2), **resources,
                  'matched_friends': len(matches), 'max_offset_error_seconds': max(errors, default=None),
                  'mix_seconds': result['timeline']['duration'], 'playable': result['playable']}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2), flush=True)
        assert report['matched_friends'] == args.clips, 'A synthetic excerpt did not align.'
        assert report['max_offset_error_seconds'] <= .16, 'Synthetic timing exceeded the existing tolerance.'
        assert report['conservative_peak_rss_bytes'] < 2 * 1024 ** 3, 'Worker exceeded the 2 GiB memory target.'
        assert report['mix_seconds'] == anchor_seconds and report['playable']


if __name__ == '__main__':
    main()
