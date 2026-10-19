"""Small, reusable storyboards on the original video's clock."""
import hashlib
import json
import math
import tempfile
from pathlib import Path

import httpx
from fastapi import HTTPException

from . import video

INTERVAL = 10
WIDTH, HEIGHT = 160, 90
COLUMNS, ROWS = 5, 10
SHEET_BYTES = 2 * 1024 ** 2


def prepare(clips, timeline, data, originals, directory, limits, progress):
    from .worker import write_json

    previews = {}
    selected = {segment['clip_id'] for segment in timeline['segments']}
    for clip in clips:
        if clip['id'] not in selected or not clip.get('video'):
            continue
        picture = clip['video']
        duration = picture['end'] - picture['start']
        count = math.ceil(duration / INTERVAL)
        if not 0 < duration <= limits.recording_seconds + 2:
            continue
        columns = min(COLUMNS, count)
        rows = min(ROWS, math.ceil(count / columns))
        identity = [1, clip['id'], clip.get('sha256'), picture, INTERVAL, WIDTH, HEIGHT, COLUMNS, ROWS]
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:32]
        cache = directory / f'scrub-{key}.json'
        sheets = [f'scrub-{key}-{index:03d}.jpg' for index in range(math.ceil(count / (columns * rows)))]
        if cache.exists() and all((directory / name).is_file() for name in sheets):
            previews[clip['id']] = json.loads(cache.read_text())
            continue
        source = None
        try:
            originals.admit(limits, work_needed=len(sheets) * SHEET_BYTES + (clip['bytes'] if clip.get('object_key') else 0))
            progress('Preparing scrub previews…', 'prepare')
            source = originals.materialize(data['id'], clip, directory)
            with tempfile.TemporaryDirectory(prefix='video-preview-', dir=directory) as temporary:
                target = Path(temporary)
                # Keyframes avoid decoding every frame of a full concert just for tiny previews.
                video.run(['-v', 'error', '-skip_frame', 'nokey', '-protocol_whitelist', 'file',
                           '-format_whitelist', video.FORMATS, '-i', str(source), '-map', '0:V:0', '-an', '-sn', '-dn',
                           '-vf', f'setpts=PTS-STARTPTS,fps=1/{INTERVAL}:start_time=0:round=up,'
                           f'tpad=stop_mode=clone:stop_duration={INTERVAL},trim=end_frame={count},'
                           f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
                           f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x243027,setsar=1,'
                           f'tile={columns}x{rows}', '-frames:v', str(len(sheets)), '-q:v', '6',
                           '-start_number', '0', str(target / f'scrub-{key}-%03d.jpg')], limits.media_seconds)
                if any(not (target / name).is_file() or not 0 < (target / name).stat().st_size <= SHEET_BYTES for name in sheets):
                    raise ValueError('Scrub previews exceeded their storage bounds.')
                for name in sheets:
                    (target / name).replace(directory / name)
            manifest = {'interval': INTERVAL, 'start': picture['start'], 'count': count,
                        'width': WIDTH, 'height': HEIGHT, 'columns': columns, 'rows': rows, 'sheets': sheets}
            write_json(cache, manifest)
            previews[clip['id']] = manifest
        except (ValueError, OSError, HTTPException, httpx.HTTPError):
            # Optional previews must not prevent publication of an otherwise playable cut.
            cache.unlink(missing_ok=True)
            for name in sheets:
                (directory / name).unlink(missing_ok=True)
        finally:
            if source is not None and clip.get('object_key'):
                source.unlink(missing_ok=True)
    return previews
