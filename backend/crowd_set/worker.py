import json
import os
import signal
from pathlib import Path
import sys
import time

import numpy as np
from fastapi import HTTPException

from .audio import align, decode, features, plan_timeline, render, match_levels, loudness, recording_quality, choose_anchor, probe, RATE, FPS
from .limits import Limits
from .storage import OriginalStore
from .blobs import digest, environment
from . import video, composition


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as output:
        json.dump(value, output, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def process(directory):
    data = json.loads((directory / 'job.json').read_text())
    clips = data['clips']
    limits = Limits.environment()
    originals = OriginalStore(directory.parent, environment(directory.parent))
    started = data.get('processing_started_at', time.time())
    def progress(stage, phase='prepare', **details):
        render = details.pop('render', None)
        write_json(directory / 'progress.json', {'stage': stage, 'render': render,
                   'processing': {'phase': phase, 'started_at': started, 'updated_at': time.time(), **details}})

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
    needed = int(total * RATE * 2) + video.PROBE_BYTES + 32 * 1024 ** 2
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
            if analysis.get('version') != 2 or not path.exists() or not feature_path.exists():
                source = originals.materialize(data['id'], clip, directory)
                try:
                    progress(f'Reading audio from recording {index + 1} of {len(candidates)}…')
                    duration = decode(source, path, expected_duration=clip['expected_duration'], limits=limits)
                    progress(f'Checking video timing for recording {index + 1} of {len(candidates)}…')
                    picture = video.probe(source, limits, directory)
                finally:
                    if clip.get('object_key'):
                        source.unlink(missing_ok=True)
                progress(f'Analyzing sound in recording {index + 1} of {len(candidates)}…')
                quality = recording_quality(path)
                measurement = loudness(path)
                np.save(feature_path, features(path), allow_pickle=False)
                analysis = {'version': 2, 'duration': duration, 'quality': quality, 'measurement': measurement, 'video': picture}
                write_json(cache, analysis)
            clip.update({key: analysis[key] for key in ('duration', 'quality', 'measurement', 'video')})
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
    soundtrack = data.get('soundtrack_clip_id')
    anchor = next((c for c in usable if c['id'] == soundtrack), None) if soundtrack else choose_anchor(usable)
    if anchor is None or (soundtrack and not anchor.get('video')):
        raise ValueError('The selected full set is missing, excluded or unusable. Choose another full set recording.')
    ref_features = np.load(directory / f'{anchor["id"]}.npy', mmap_mode='r', allow_pickle=False)
    for index, clip in enumerate(usable):
        progress(f'Matching recording {index + 1} of {len(usable)}…', 'align')
        cache = directory / f'{clip["id"]}.alignment.json'
        cached = json.loads(cache.read_text()) if cache.exists() else {}
        if cached.get('version') == 1 and cached.get('anchor_id') == anchor['id']:
            clip['alignment'] = cached['alignment']
        else:
            clip['alignment'] = ({'status': 'matched', 'offset_seconds': 0, 'windows': []} if clip is anchor else
                                 align(ref_features, np.load(directory / f'{clip["id"]}.npy', mmap_mode='r', allow_pickle=False)))
            write_json(cache, {'version': 1, 'anchor_id': anchor['id'], 'alignment': clip['alignment']})
    timeline = plan_timeline([anchor] if soundtrack else clips)
    timeline['anchor_id'] = anchor['id']
    sources = {c['id']: directory / f'{c["id"]}.wav' for c in usable if c['alignment']['status'] == 'matched'}
    match_levels(timeline, sources, {c['id']: c['measurement'] for c in usable})
    progress('Mixing audio…', 'audio')
    playable = render(timeline, sources, directory / 'pending.wav')
    if playable:
        progress('Checking audio levels…', 'audio')
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
    visual = video.plan_video(clips, timeline)
    base = visual
    if soundtrack:
        visual, base = composition.plan(clips, timeline, anchor)
    previous_audio = directory / (data.get('mix_file') or 'reconstruction.wav')
    previous_video_available = data.get('video_object') if originals.blobs else (directory / (data.get('video_file') or 'missing')).is_file()
    same_audio = (playable and data.get('playable') and data.get('mix_revision') and previous_audio.is_file()
            and digest(directory / 'pending.wav') == digest(previous_audio))
    same_video = (bool(visual['segments']) == bool(data.get('video_playable'))
                  and (not visual['segments'] or (previous_video_available and visual == data.get('video_timeline'))))
    if same_audio and same_video and bool(soundtrack) == bool(data.get('composition')):
        progress('Keeping the unchanged cut…', 'finalize')
        write_json(directory / 'result.json', {'clips': clips, 'timeline': timeline, 'playable': True,
                   'video_playable': bool(visual['segments']), 'video_timeline': visual if visual['segments'] else None,
                   'composition': data.get('composition'), 'reuse_revision': data['mix_revision']})
        return
    base_reused = (soundtrack and same_audio and previous_video_available
                   and base == ((data.get('composition') or {}).get('base_timeline') or data.get('video_timeline')))
    result = {'clips': clips, 'timeline': timeline, 'playable': playable,
              'video_playable': bool(visual['segments']), 'video_timeline': visual if visual['segments'] else None,
              'composition': None}
    if soundtrack:
        assets = composition.prepare(visual, clips, data, originals, directory, limits, progress)
        result['composition'] = {'soundtrack_clip_id': soundtrack, 'base_timeline': base, 'assets': assets}
    if base_reused:
        result['reuse_base_revision'] = data['mix_revision']
    else:
        video_clips = [anchor] if soundtrack else clips
        if base['segments']:
            originals.admit(limits, work_needed=2 * video.output_bound(base, video_clips) +
                            len(base['segments'] + base['gaps']) * 2 * 1024 ** 2 +
                            max((c.get('bytes', 0) for c in video_clips if c.get('object_key')), default=0))
        progress('Preparing video…', 'render')
        result['video_playable'] = playable and video.render(base, video_clips, originals, data['id'], directory, limits, on_progress=progress)
    write_json(directory / 'result.json', result)


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
        write_json(folder / 'failure.json', {'error': exc.detail if isinstance(exc, HTTPException) else str(exc) if isinstance(exc, ValueError) else 'Processing failed. Check available disk space and decoder installation, then retry.'})
        sys.exit(1)
