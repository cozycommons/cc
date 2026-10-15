import json
import os
import signal
from pathlib import Path
import sys

import numpy as np

from .audio import align, decode, features, plan_timeline, render, match_levels, loudness, recording_quality, choose_anchor


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False))
    temporary.replace(path)


def process(directory):
    data = json.loads((directory / 'job.json').read_text())
    clips = data['clips']
    def progress(stage):
        write_json(directory / 'progress.json', {'stage': stage})

    usable = []
    for clip in clips:
        clip.pop('alignment', None)
        if clip['role'] == 'reference' or not clip['included']:
            continue
        progress('Preparing recordings')
        path = directory / f'{clip["id"]}.wav'
        cache = directory / f'{clip["id"]}.analysis.json'
        feature_path = directory / f'{clip["id"]}.npy'
        try:
            analysis = json.loads(cache.read_text()) if cache.exists() else {}
            if analysis.get('version') != 1 or not path.exists() or not feature_path.exists():
                duration = decode(directory / clip['file'], path)
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
    anchor = choose_anchor(usable)
    ref_features = np.load(directory / f'{anchor["id"]}.npy', mmap_mode='r', allow_pickle=False)
    for clip in usable:
        progress('Updating mix')
        clip['alignment'] = ({'status': 'matched', 'offset_seconds': 0, 'windows': []} if clip is anchor else
                             align(ref_features, np.load(directory / f'{clip["id"]}.npy', mmap_mode='r', allow_pickle=False)))
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
    signal.alarm(900)
    folder = Path(sys.argv[1])
    try:
        process(folder)
    except Exception as exc:
        write_json(folder / 'failure.json', {'error': str(exc) if isinstance(exc, ValueError) else 'Processing failed. Check available disk space and decoder installation, then retry.'})
        sys.exit(1)
