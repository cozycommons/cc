import json
import os
import signal
from pathlib import Path
import sys

import numpy as np

from .audio import align, decode, features, plan_timeline, render, match_levels, loudness, recording_quality, choose_anchor, probe, RATE, FPS
from .limits import Limits
from .storage import OriginalStore
from .blobs import environment


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False))
    temporary.replace(path)


def process(directory):
    data = json.loads((directory / 'job.json').read_text())
    clips = data['clips']
    limits = Limits.environment()
    originals = OriginalStore(directory.parent, environment(directory.parent))
    def progress(stage):
        write_json(directory / 'progress.json', {'stage': stage})

    candidates = []
    for clip in clips:
        clip.pop('alignment', None)
        if clip['role'] == 'reference' or not clip['included']:
            continue
        try:
            if not clip.get('expected_duration'):
                source = originals.materialize(data['id'], clip, directory)
                clip['expected_duration'] = probe(source, limits=limits)
                if clip.get('object_key'):
                    source.unlink(missing_ok=True)
            candidates.append(clip)
        except ValueError as exc:
            clip['alignment'] = {'status': 'error', 'reason': str(exc), 'windows': []}
    total = sum(clip['expected_duration'] for clip in candidates)
    if total > limits.set_seconds:
        raise ValueError(f'This set exceeds {limits.set_seconds // 3600} hours of included recordings. Exclude recordings and retry.')
    needed = int(total * RATE * 2) + 32 * 1024 ** 2
    for clip in candidates:
        if not all((directory / f'{clip["id"]}{suffix}').exists() for suffix in ('.wav', '.npy', '.analysis.json')):
            needed += int((clip['expected_duration'] + 2) * (RATE * 4 + FPS * 24 * 4)) + 16384
    needed += max((clip.get('bytes', 0) for clip in candidates if clip.get('object_key')), default=0)
    originals.admit(limits, work_needed=needed)
    usable = []
    for index, clip in enumerate(candidates):
        progress(f'Preparing recording {index + 1} of {len(candidates)}…')
        path = directory / f'{clip["id"]}.wav'
        cache = directory / f'{clip["id"]}.analysis.json'
        feature_path = directory / f'{clip["id"]}.npy'
        try:
            analysis = json.loads(cache.read_text()) if cache.exists() else {}
            if analysis.get('version') != 1 or not path.exists() or not feature_path.exists():
                source = originals.materialize(data['id'], clip, directory)
                try:
                    duration = decode(source, path, expected_duration=clip['expected_duration'], limits=limits)
                finally:
                    if clip.get('object_key'):
                        source.unlink(missing_ok=True)
                quality = recording_quality(path)
                measurement = loudness(path)
                np.save(feature_path, features(path), allow_pickle=False)
                analysis = {'version': 1, 'duration': duration, 'quality': quality, 'measurement': measurement}
                write_json(cache, analysis)
            clip.update({key: analysis[key] for key in ('duration', 'quality', 'measurement')})
            usable.append(clip)
        except ValueError as exc:
            clip['alignment'] = {'status': 'error', 'reason': str(exc), 'windows': []}
            path.unlink(missing_ok=True)
            cache.unlink(missing_ok=True)
            feature_path.unlink(missing_ok=True)
    if not usable:
        raise ValueError('No usable recordings. Add a video with audible sound, then retry.')
    if sum(clip['duration'] for clip in usable) > limits.set_seconds:
        raise ValueError('Decoded recordings exceed this set’s duration budget. Exclude recordings and retry.')
    anchor = choose_anchor(usable)
    ref_features = np.load(directory / f'{anchor["id"]}.npy', mmap_mode='r', allow_pickle=False)
    for index, clip in enumerate(usable):
        progress(f'Matching recording {index + 1} of {len(usable)}…')
        cache = directory / f'{clip["id"]}.alignment.json'
        cached = json.loads(cache.read_text()) if cache.exists() else {}
        if cached.get('version') == 1 and cached.get('anchor_id') == anchor['id']:
            clip['alignment'] = cached['alignment']
        else:
            clip['alignment'] = ({'status': 'matched', 'offset_seconds': 0, 'windows': []} if clip is anchor else
                                 align(ref_features, np.load(directory / f'{clip["id"]}.npy', mmap_mode='r', allow_pickle=False)))
            write_json(cache, {'version': 1, 'anchor_id': anchor['id'], 'alignment': clip['alignment']})
    timeline = plan_timeline(clips)
    timeline['anchor_id'] = anchor['id']
    sources = {c['id']: directory / f'{c["id"]}.wav' for c in usable if c['alignment']['status'] == 'matched'}
    match_levels(timeline, sources, {c['id']: c['measurement'] for c in usable})
    playable = render(timeline, sources, directory / 'pending.wav')
    if playable:
        peak = loudness(directory / 'pending.wav')['true_peak_dbfs']
        if peak > -2:
            reduction = peak + 2.1
            for level in timeline['levels'].values():
                level['gain_db'] -= reduction
                level['estimated_true_peak_dbfs'] -= reduction
            timeline['common_attenuation_db'] += reduction
            render(timeline, sources, directory / 'pending.wav')
            peak = loudness(directory / 'pending.wav')['true_peak_dbfs']
        if peak > -1.9:
            raise ValueError('Output peak headroom could not be verified. Try different sources.')
        timeline['output_true_peak_dbfs'] = peak
    write_json(directory / 'result.json', {'clips': clips, 'timeline': timeline, 'playable': playable})


if __name__ == '__main__':
    if os.getpgrp() != os.getpid():
        raise RuntimeError('Workers must be launched by the Crowd Set API in a dedicated process group.')
    # A parent crash must not remove the deadline or release storage while this job writes.
    signal.signal(signal.SIGALRM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL))
    signal.alarm(Limits.environment().job_seconds)
    folder = Path(sys.argv[1])
    try:
        process(folder)
    except Exception as exc:
        write_json(folder / 'failure.json', {'error': str(exc) if isinstance(exc, ValueError) else 'Processing failed. Check available disk space and decoder installation, then retry.'})
        sys.exit(1)
