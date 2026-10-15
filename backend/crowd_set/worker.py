import json
import os
import signal
from pathlib import Path
import sys

from .audio import align, decode, features, plan_timeline, render, match_levels, loudness


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, allow_nan=False))
    temporary.replace(path)


def process(directory):
    data = json.loads((directory / 'job.json').read_text())
    clips = data['clips']
    reference = next(c for c in clips if c['role'] == 'reference')

    def progress(stage):
        write_json(directory / 'progress.json', {'stage': stage})

    progress('Converting timing reference')
    reference['duration'] = decode(directory / reference['file'], directory / 'reference.wav', reference=True)
    progress('Analyzing reference timing')
    ref_features = features(directory / 'reference.wav')
    for index, clip in enumerate(clips):
        if clip['role'] != 'crowd' or not clip['included']:
            continue
        progress(f'Converting and aligning {clip["name"]} ({index + 1}/{len(clips)})')
        path = directory / f'{clip["id"]}.wav'
        try:
            clip['duration'] = decode(directory / clip['file'], path)
            clip['alignment'] = align(ref_features, features(path))
        except ValueError as exc:
            clip['alignment'] = {'status': 'error', 'reason': str(exc), 'windows': []}
            path.unlink(missing_ok=True)
    timeline = plan_timeline(clips, reference['duration'])
    progress('Rendering crowd-only reconstruction')
    sources = {c['id']: directory / f'{c["id"]}.wav' for c in clips if c.get('alignment', {}).get('status') == 'matched' and c['role'] == 'crowd' and c['included']}
    progress('Measuring source levels for steady transitions')
    match_levels(timeline, sources)
    progress('Rendering crowd-only reconstruction')
    playable = render(timeline, sources, directory / 'reconstruction.wav')
    if playable:
        peak = loudness(directory / 'reconstruction.wav')['true_peak_dbfs']
        if peak > -2:
            reduction = peak + 2.1
            for level in timeline['levels'].values():
                level['gain_db'] -= reduction
                level['estimated_true_peak_dbfs'] -= reduction
            timeline['common_attenuation_db'] += reduction
            render(timeline, sources, directory / 'reconstruction.wav')
            peak = loudness(directory / 'reconstruction.wav')['true_peak_dbfs']
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
