from pathlib import Path
import math
import re
import subprocess
import tempfile
import wave

import imageio_ffmpeg
import numpy as np
from scipy.io import wavfile
from scipy.ndimage import uniform_filter1d
from scipy.signal import correlate, resample_poly

from .limits import Limits

FPS = 25
RATE = 32000


def probe(source: Path, *, limits=None):
    limits = limits or Limits.environment()
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-v', 'info',
               '-max_alloc', '67108864', '-threads', '1', '-protocol_whitelist', 'file',
               '-format_whitelist', 'wav,mov,mp3,aac,flac,ogg,matroska,webm',
               '-i', str(source), '-map', '0:a:0', '-t', '0', '-f', 'null', '-']
    try:
        with tempfile.TemporaryFile() as log:
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=log, timeout=30)
            log.seek(0)
            report = log.read(65536).decode('utf-8', errors='replace')
        match = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', report)
        if result.returncode or not match:
            raise ValueError('Cannot read this recording’s duration and audio. Export it as MP4, M4A or WAV and retry.')
        hours, minutes, seconds = map(float, match.groups())
        duration = hours * 3600 + minutes * 60 + seconds
        if not 1 <= duration <= limits.recording_seconds:
            raise ValueError(f'Recordings must be between 1 second and {limits.recording_seconds // 60} minutes.')
        return duration
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Reading the recording timed out. Try another export.') from exc


def decode(source: Path, destination: Path, *, reference=False, expected_duration=None, limits=None):
    limits = limits or Limits.environment()
    limit = limits.recording_seconds
    if expected_duration is not None:
        limit = min(limit, math.ceil(expected_duration) + 1)
    rate = 16000 if reference else RATE
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error', '-y',
        '-max_alloc', '67108864', '-threads', '1', '-xerror', '-err_detect', 'explode',
        '-protocol_whitelist', 'file',
        '-format_whitelist', 'wav,mov,mp3,aac,flac,ogg,matroska,webm',
        '-i', str(source), '-map', '0:a:0', '-vn', '-sn', '-dn',
        '-t', str(limit + 1), '-ac', '1', '-ar', str(rate),
        '-c:a', 'pcm_f32le', '-threads', '1', str(destination),
    ]
    try:
        # stderr goes to a file so malformed media cannot grow a captured pipe in RAM.
        with destination.with_suffix('.log').open('wb') as log:
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=log, timeout=limits.media_seconds)
        if result.returncode:
            raise ValueError('Cannot decode this file. Use a supported audio/video file with an audio track.')
        rate, samples = wavfile.read(destination, mmap=True)
        duration = len(samples) / rate
        if not 1 <= duration <= limit:
            raise ValueError(f'Audio must be between 1 second and {limit // 60} minutes.')
        return duration
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Audio conversion exceeded its time limit. Try another export.') from exc
    finally:
        destination.with_suffix('.log').unlink(missing_ok=True)


def float_samples(samples):
    values = samples.astype(np.float64)
    if samples.dtype == np.int16:
        values /= 32768
    return values


def recording_quality(path):
    rate, samples = wavfile.read(path, mmap=True)
    clipped = silent = blocks = 0
    energy = 0.0
    for start in range(0, len(samples), rate):
        values = float_samples(samples[start:start + rate])
        if not np.isfinite(values).all():
            raise ValueError('This recording contains invalid audio. Upload another copy.')
        power = float(np.sum(values * values))
        energy += power
        clipped += int(np.count_nonzero(np.abs(values) >= 1))
        silent += power / len(values) < 1e-8
        blocks += 1
    if not len(samples) or energy / len(samples) < 1e-8:
        raise ValueError('No audible audio found. Upload a recording with sound.')
    return {'clipped_fraction': clipped / len(samples), 'silent_fraction': silent / blocks}


def choose_anchor(clips):
    return min(clips, key=lambda c: (-c['duration'], c['quality']['clipped_fraction'],
                                    c['quality']['silent_fraction'], c['id']))


def features(path: Path):
    bands = np.geomspace(80, 7500, 25)
    frequencies = np.fft.rfftfreq(1024, 1 / 16000)
    masks = [(frequencies >= a) & (frequencies < b) for a, b in zip(bands, bands[1:])]
    chunks = []
    rate, samples = wavfile.read(path, mmap=True)
    factor = rate // 16000
    total = len(samples)
    frame = 0
    # Fixed-size blocks preserve a global 640-sample hop without full-recording FFT buffers.
    while frame * 640 * factor + 1024 * factor <= total:
        count = min(1500, (total // factor - 1024) // 640 + 1 - frame)
        start = frame * 640 * factor
        raw = float_samples(samples[start:start + ((count - 1) * 640 + 1024) * factor])
        if factor > 1:
            raw = resample_poly(raw, 1, factor)
        windows = np.lib.stride_tricks.sliding_window_view(raw, 1024)[::640][:count]
        power = np.abs(np.fft.rfft(windows * np.hanning(1024), axis=1)) ** 2
        chunks.append(np.stack([np.log(np.maximum(power[:, mask].mean(axis=1), 1e-10)) for mask in masks], axis=1))
        frame += count
    if not chunks:
        return np.empty((0, 24), dtype=np.float32)
    values = np.concatenate(chunks).astype(np.float32)
    values -= uniform_filter1d(values, size=25, axis=0, mode='nearest')
    values /= np.maximum(values.std(axis=0), 0.1)
    return np.clip(values, -4, 4)


def align(reference, source):
    window = 12 * FPS
    empty = {'status': 'unmatched', 'windows': [], 'reason': 'At least 37 seconds of usable crowd audio and reference are required.'}
    if min(len(source), len(reference)) < window * 3:
        return empty
    starts = np.unique(np.linspace(0, len(source) - window, min(9, len(source) // window)).astype(int))
    energy = np.sum(reference * reference, axis=1)
    sums = np.concatenate(([0], np.cumsum(energy, dtype=np.float64)))
    ref_norm = np.sqrt(np.maximum(sums[window:] - sums[:-window], 1e-12))
    evidence = []
    for start in starts:
        query = source[start:start + window]
        norm = np.linalg.norm(query)
        if norm < 1:
            continue
        dots = sum(correlate(reference[:, band], query[:, band], mode='valid', method='fft') for band in range(24))
        scores = dots / (ref_norm * norm)
        best = int(np.argmax(scores))
        competitors = scores.copy()
        competitors[max(0, best - 2 * FPS):best + 2 * FPS + 1] = -1
        score = float(scores[best])
        margin = score - float(np.max(competitors))
        evidence.append({'source_seconds': round(int(start) / FPS, 3), 'offset_seconds': round((best - int(start)) / FPS, 3),
                         'similarity': round(score, 4), 'peak_margin': round(margin, 4),
                         'strong': score >= 0.25 and margin >= 0.08})
    strong = [w for w in evidence if w['strong']]
    result = {'status': 'unmatched', 'windows': evidence, 'reason': 'Insufficient distinct, agreeing matches; clip may be unrelated, repetitive, silent, or only partly covered.'}
    if len(strong) < 3:
        return result
    offsets = np.array([w['offset_seconds'] for w in strong])
    offset = float(np.median(offsets))
    spread = float(np.max(np.abs(offsets - offset)))
    # Conflicting strong matches indicate edits/drift/repetition; do not select a convenient cluster.
    if spread > 0.16:
        result['reason'] = 'Timing changes across the clip (possible drift, edits, or repeated music). Manual review required.'
        return result
    overlap_start = max(0, -offset)
    overlap_end = min(len(source) / FPS, len(reference) / FPS - offset)
    eligible = [w for w in evidence if w['source_seconds'] >= overlap_start - 0.16 and w['source_seconds'] + 12 <= overlap_end + 0.16]
    if len(strong) < max(3, int(np.ceil(len(eligible) * 0.75))):
        return result
    return {'status': 'matched', 'offset_seconds': round(offset, 3),
            'uncertainty_seconds': round(max(0.04, spread + 0.04), 3),
            'similarity': round(float(np.median([w['similarity'] for w in strong])), 4),
            'agreement': len(strong), 'windows': evidence,
            'reason': 'Approximate timing from sampled windows; listen to verify. Similarity is not a probability.'}


def plan_timeline(clips, duration=None):
    matched = [c for c in clips if c.get('role') != 'reference' and c.get('included', True)
               and c.get('alignment', {}).get('status') == 'matched']
    origin = min((c['alignment']['offset_seconds'] for c in matched), default=0) if duration is None else 0
    if duration is None:
        duration = max((c['alignment']['offset_seconds'] + c['duration'] for c in matched), default=origin) - origin
    candidates = []
    for clip in matched:
        offset = clip['alignment']['offset_seconds'] - origin
        start, end = max(0.0, offset), min(duration, offset + clip['duration'])
        if end > start:
            candidates.append({'clip_id': clip['id'], 'start': start, 'end': end, 'offset': offset})
    segments, gaps = [], []
    position = 0.0
    while position < duration:
        active = [c for c in candidates if c['start'] <= position + 1e-8 and c['end'] > position + 1e-8]
        if not active:
            upcoming = [c['start'] for c in candidates if c['start'] > position]
            end = min(upcoming, default=duration)
            gaps.append({'start': position, 'end': end})
            position = end
            continue
        chosen = sorted(active, key=lambda c: (-c['end'], c['clip_id']))[0]
        fade = 0.0
        if segments and abs(segments[-1]['end'] - position) < 1e-8:
            fade = min(0.08, position - chosen['start'], (segments[-1]['end'] - segments[-1]['start']) / 2)
        segments.append({**chosen, 'start': position - fade, 'fade_in': fade})
        position = chosen['end']
    return {'duration': duration, 'origin_seconds': origin, 'segments': segments, 'gaps': gaps,
            'covered_seconds': duration - sum(g['end'] - g['start'] for g in gaps)}


def render(timeline, sources, destination):
    if not timeline['segments']:
        return False
    import contextlib
    with contextlib.ExitStack() as stack:
        readers = {key: wavfile.read(path, mmap=True)[1] for key, path in sources.items()}
        output = stack.enter_context(wave.open(str(destination), 'wb'))
        output.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
        segments = timeline['segments']
        frames = round(timeline['duration'] * RATE)
        for base in range(0, frames, RATE * 5):
            count = min(RATE * 5, frames - base)
            mix = np.zeros(count, dtype=np.float64)
            for index, segment in enumerate(segments):
                lo, hi = max(base, round(segment['start'] * RATE)), min(base + count, round(segment['end'] * RATE))
                if hi <= lo:
                    continue
                reader = readers[segment['clip_id']]
                source_start = lo - round(segment['offset'] * RATE)
                source_start = max(0, source_start)
                values = float_samples(reader[source_start:source_start + hi - lo]) * 32768
                times = np.arange(lo, lo + len(values)) / RATE
                gain = np.ones(len(values))
                if segment['fade_in'] > 0:
                    gain *= np.clip((times - segment['start']) / segment['fade_in'], 0, 1)
                if index + 1 < len(segments):
                    following = segments[index + 1]
                    if following['fade_in'] > 0:
                        gain *= np.clip((segment['end'] - times) / following['fade_in'], 0, 1)
                mix[lo - base:lo - base + len(values)] += values * gain * 10 ** (timeline.get('levels', {}).get(segment['clip_id'], {}).get('gain_db', 0) / 20)
            if np.any(mix > 32767) or np.any(mix < -32768):
                raise ValueError('Output would clip. Reduce source levels before retrying.')
            output.writeframes(np.rint(mix).astype('<i2').tobytes())
    return True


def loudness(path, start=0, duration=None):
    import json
    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-nostats', '-v', 'info',
               '-threads', '1', '-ss', str(start), '-i', str(path)]
    trim = f'atrim=duration={duration},asetpts=PTS-STARTPTS,' if duration is not None else ''
    command += ['-af', trim + 'loudnorm=I=-23:TP=-2:LRA=7:print_format=json', '-f', 'null', '-']
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=Limits.environment().media_seconds)
        report, _ = json.JSONDecoder().raw_decode('{' + result.stderr.decode('utf-8', errors='replace').rsplit('{', 1)[1])
        integrated, peak = float(report['input_i']), float(report['input_tp'])
        if result.returncode or not np.isfinite(integrated) or not np.isfinite(peak):
            raise ValueError('No measurable loudness')
        return {'integrated_lufs': integrated, 'true_peak_dbfs': peak}
    except (ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Could not measure source loudness. Try a clearer or shorter clip.') from exc


def match_levels(timeline, sources, measurements=None):
    """Measure same-passage overlap when possible; apply only static source gains."""
    selected = {segment['clip_id'] for segment in timeline['segments']}
    measurements = {key: measurements[key] if measurements and key in measurements else loudness(path)
                    for key, path in sources.items() if key in selected}
    levels = {}
    previous = None
    for segment in timeline['segments']:
        key = segment['clip_id']
        measured = measurements[key]
        gain = -23 - measured['integrated_lufs']
        basis = ('Whole-clip anchor at -23 LUFS before peak headroom' if previous is None else
                 'Whole-clip loudness fallback (no usable overlap of at least 8 seconds)')
        if previous:
            overlap_start = max(previous['offset'], segment['offset'], 0)
            overlap_end = min(previous['end'], segment['end'])
            overlap = min(30, overlap_end - overlap_start)
            if overlap >= 8:
                start = overlap_end - overlap
                outgoing = loudness(sources[previous['clip_id']], start - previous['offset'], overlap)
                incoming = loudness(sources[key], start - segment['offset'], overlap)
                gain = outgoing['integrated_lufs'] + levels[previous['clip_id']]['gain_db'] - incoming['integrated_lufs']
                basis = f'Same {overlap:.1f}s overlapping passage'
        applied = float(np.clip(gain, -60, 12))
        levels[key] = {**measured, 'gain_db': applied, 'basis': basis, 'gain_limited': abs(gain - applied) > .01}
        previous = segment
    # Common attenuation keeps relative matches while reserving true-peak headroom for the linear fades.
    attenuation = max(0, max((m['true_peak_dbfs'] + levels[key]['gain_db'] + 2 for key, m in measurements.items() if key in levels), default=0))
    for value in levels.values():
        value['gain_db'] = round(value['gain_db'] - attenuation, 4)
        value['estimated_true_peak_dbfs'] = round(value['true_peak_dbfs'] + value['gain_db'], 4)
    timeline['levels'] = levels
    timeline['common_attenuation_db'] = round(attenuation, 4)
    return levels
