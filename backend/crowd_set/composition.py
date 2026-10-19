"""An official soundtrack with independently published, silent picture inserts."""
import hashlib
import json
import math

from . import video


def plan(clips, timeline, anchor):
    base = video.plan_video([anchor], timeline)
    friends = []
    for clip in clips:
        if clip['id'] != anchor['id'] and clip.get('duration', math.inf) < anchor['duration']:
            friends.extend(video.plan_video([clip], timeline)['segments'])
    segments, gaps = [], []
    position, frames = 0, math.ceil(timeline['duration'] * video.FRAME_RATE)
    while position < frames:
        active = [s for s in friends if s['first_frame'] <= position < s['last_frame']
                  and (s['first_frame'] == position or s['last_frame'] - position >= 3 * video.FRAME_RATE)]
        if active:
            chosen = min(active, key=lambda s: (s['first_frame'], s['clip_id']))
            end = chosen['last_frame']
        else:
            upcoming = min((s['first_frame'] for s in friends if s['first_frame'] > position), default=frames)
            chosen = next((s for s in base['segments'] if s['first_frame'] <= position < s['last_frame']), None)
            base_end = chosen['last_frame'] if chosen else min(
                (s['first_frame'] for s in base['segments'] if s['first_frame'] > position), default=frames)
            end = min(upcoming, base_end)
        item = {'first_frame': position, 'last_frame': end,
                'start': position / video.FRAME_RATE, 'end': end / video.FRAME_RATE}
        if chosen:
            item = {**chosen, **item}
            if chosen['clip_id'] != anchor['id']:
                clip = next(c for c in clips if c['id'] == chosen['clip_id'])
                identity = [1, clip['id'], clip.get('sha256'), item['first_frame'], end,
                            item['offset'], clip['video']]
                item['asset_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:32]
            segments.append(item)
        else:
            gaps.append(item)
        position = end
    return {**base, 'segments': segments, 'gaps': gaps}, base


def prepare(visual, clips, data, originals, directory, limits, progress):
    cached = {}
    for revision in (data.get('previous_revision', {}), data):
        cached.update((revision.get('composition') or {}).get('assets', {}))
    assets = {}
    for segment in visual['segments']:
        asset_id = segment.get('asset_id')
        if not asset_id:
            continue
        old = cached.get(asset_id)
        if old and (old.get('object') if originals.blobs else (directory / old['file']).is_file()):
            assets[asset_id] = old
            continue
        clip = next(c for c in clips if c['id'] == segment['clip_id'])
        duration = segment['end'] - segment['start']
        bound = video.byte_bound(duration)
        originals.admit(limits, work_needed=bound + (clip.get('bytes', 0) if clip.get('object_key') else 0),
                        incoming=bound if originals.blobs else 0)
        name = f'overlay-{asset_id}.mp4'
        path = directory / name
        source = originals.materialize(data['id'], clip, directory)
        timestamp = segment['start'] - segment['offset'] + clip['video']['audio_start']
        count = segment['last_frame'] - segment['first_frame']
        report = directory / f'overlay-{asset_id}.progress'
        progress('Preparing a friend’s video…', 'render', render={'file': report.name,
                 'completed_frames': 0, 'segment_frames': count, 'total_frames': count})
        try:
            actual = video.run(['-v', 'error', '-copyts', '-seek_timestamp', '1', '-ss', str(max(0, timestamp)),
                '-protocol_whitelist', 'file', '-format_whitelist', video.FORMATS, '-i', str(source),
                '-map', '0:V:0', '-an', '-sn', '-dn', '-vf', video.picture_filters(timestamp, duration),
                '-frames:v', str(count), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                '-maxrate', '3000k', '-bufsize', '6000k', '-pix_fmt', 'yuv420p', '-threads', '1',
                '-map_metadata', '-1', '-movflags', '+faststart', '-fs', str(bound),
                '-progress', str(report), str(path)],
                max(limits.media_seconds, min(limits.job_seconds, math.ceil(duration * 2))), progress=report)
            if actual != count or path.stat().st_size >= bound:
                raise ValueError('The friend’s video exceeded its frame or storage bounds.')
            assets[asset_id] = {'file': name, 'object': None, 'bytes': path.stat().st_size}
        finally:
            report.unlink(missing_ok=True)
            if clip.get('object_key'):
                source.unlink(missing_ok=True)
    return assets
