"""One deterministic visual cut on the compiled audio's clock."""
import math
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

FORMATS = 'wav,mov,mp3,aac,flac,ogg,matroska,webm'
FRAME_RATE = 24
WIDTH, HEIGHT = 1920, 1080
PROBE_BYTES = 128 * 1024 ** 2
BYTES_PER_SECOND = 420_000  # 3 Mbps video + 96 kbps audio, container/headroom.


def byte_bound(duration):
    return math.ceil(duration * BYTES_PER_SECOND) + 2 * 1024 ** 2


def command():
    return [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner', '-y',
            '-max_alloc', '67108864', '-threads', '1', '-filter_threads', '1']


def run(args, timeout, *, progress=None):
    with tempfile.TemporaryFile() as log:
        try:
            result = subprocess.run(command() + args, stdout=subprocess.DEVNULL, stderr=log, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('Video rendering exceeded its time limit. The previous cut is retained.') from exc
        log.seek(0)
        report = log.read(65536).decode('utf-8', errors='replace')
    if result.returncode:
        raise ValueError('Could not render the video cut. Try another export of the recordings.')
    if progress is not None:
        frames = re.findall(r'^frame=(\d+)$', progress.read_text(), re.MULTILINE)
        return int(frames[-1]) if frames else 0
    return report


def probe(source, limits, workdir=None):
    report = run(['-v', 'info', '-copyts', '-protocol_whitelist', 'file',
                  '-format_whitelist', FORMATS, '-i', str(source),
                  '-map', '0:V:0?', '-map', '0:a:0', '-vf', 'showinfo', '-af', 'ashowinfo',
                  '-frames:v', '1', '-frames:a', '1', '-f', 'null', '-'], min(30, limits.media_seconds))
    picture = re.search(r'\[Parsed_showinfo_\d+[^\n]*?pts_time:([\d.e+-]+)', report)
    if not picture:
        return None
    audio = re.search(r'\[Parsed_ashowinfo_\d+[^\n]*?pts_time:([\d.e+-]+)', report)
    if not audio:
        raise ValueError('Cannot establish this video’s audio clock.')
    start, audio_start = float(picture[1]), float(audio[1])
    if not all(math.isfinite(n) for n in (start, audio_start)):
        raise ValueError('Invalid media timestamps.')
    with tempfile.TemporaryDirectory(prefix='video-probe-', dir=workdir or source.parent) as temporary:
        packets = Path(temporary) / 'packets.txt'
        run(['-v', 'error', '-copyts', '-protocol_whitelist', 'file',
             '-format_whitelist', FORMATS, '-i', str(source), '-map', '0:V:0',
             '-c', 'copy', '-f', 'framecrc', '-fs', str(PROBE_BYTES), str(packets)], limits.media_seconds)
        if packets.stat().st_size >= PROBE_BYTES:
            raise ValueError('Video timing metadata exceeds its processing limit. Try a shorter export.')
        scale, end = None, None
        with packets.open() as rows:
            for row in rows:
                if row.startswith('#tb 0:'):
                    numerator, denominator = row.split(':')[1].strip().split('/')
                    scale = int(numerator) / int(denominator)
                elif not row.startswith('#') and row.strip() and scale is not None:
                    fields = row.split(',')
                    timestamp = (int(fields[2]) + int(fields[3])) * scale
                    end = max(end if end is not None else timestamp, timestamp)
        if end is None or not math.isfinite(end) or end <= start:
            raise ValueError('Cannot establish this video’s duration.')
    return {'start': start - audio_start, 'end': end - audio_start, 'audio_start': audio_start}


def plan_video(clips, timeline):
    duration = timeline['duration']
    frames = math.ceil(duration * FRAME_RATE)
    candidates = []
    for clip in clips:
        media = clip.get('video')
        if not media or clip.get('role') == 'reference' or not clip.get('included', True) or clip.get('alignment', {}).get('status') != 'matched':
            continue
        offset = clip['alignment']['offset_seconds'] - timeline['origin_seconds']
        start = max(0, math.ceil((offset + max(0, media['start'])) * FRAME_RATE - 1e-7))
        end = min(frames, math.ceil((offset + min(clip['duration'], media['end'])) * FRAME_RATE - 1e-7))
        if end > start:
            candidates.append({'clip_id': clip['id'], 'first_frame': start, 'last_frame': end, 'offset': offset})
    segments, gaps = [], []
    position = 0
    while position < frames:
        active = [c for c in candidates if c['first_frame'] <= position < c['last_frame']]
        if active:
            chosen = min(active, key=lambda c: (-c['last_frame'], c['clip_id']))
            end = chosen['last_frame']
            segments.append({**chosen, 'first_frame': position, 'start': position / FRAME_RATE, 'end': end / FRAME_RATE, 'fade_in': 0})
        else:
            end = min((c['first_frame'] for c in candidates if c['first_frame'] > position), default=frames)
            gaps.append({'first_frame': position, 'last_frame': end, 'start': position / FRAME_RATE, 'end': end / FRAME_RATE})
        position = end
    return {'duration': duration, 'origin_seconds': timeline['origin_seconds'], 'fps': FRAME_RATE,
            'width': WIDTH, 'height': HEIGHT, 'segments': segments, 'gaps': gaps}


def render(timeline, clips, originals, set_id, directory, limits):
    if not timeline['segments']:
        return False
    by_id = {c['id']: c for c in clips}
    destination = directory / 'pending.mp4'
    with tempfile.TemporaryDirectory(prefix='video-', dir=directory) as temporary:
        folder = Path(temporary)
        paths = []
        for index, segment in enumerate(sorted(timeline['segments'] + timeline['gaps'], key=lambda s: s['first_frame'])):
            count = segment['last_frame'] - segment['first_frame']
            duration = count / FRAME_RATE
            clip = by_id.get(segment.get('clip_id'))
            source = None
            if clip:
                source = originals.materialize(set_id, clip, directory)
                timestamp = segment['start'] - segment['offset'] + clip['video']['audio_start']
                inputs = ['-copyts', '-seek_timestamp', '1', '-ss', str(max(0, timestamp)),
                          '-protocol_whitelist', 'file', '-format_whitelist', FORMATS, '-i', str(source), '-map', '0:V:0']
                filters = (f'trim=start={timestamp},setpts=PTS-({timestamp})/TB,'
                           f"scale=w='if(gt(dar,{WIDTH}/{HEIGHT}),{WIDTH},max(2,trunc({HEIGHT}*dar/2)*2))':"
                           f"h='if(gt(dar,{WIDTH}/{HEIGHT}),max(2,trunc({WIDTH}/dar/2)*2),{HEIGHT})',setsar=1,"
                           f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x243027,setsar=1,'
                           f'fps={FRAME_RATE}:start_time=0,tpad=stop_mode=add:stop_duration={duration}:color=0x243027')
            else:
                inputs = ['-f', 'lavfi', '-i', f'color=c=0x243027:s={WIDTH}x{HEIGHT}:r={FRAME_RATE}']
                filters = 'null'
            path = folder / f'{index}.mp4'
            progress = folder / 'progress.txt'
            try:
                actual = run(['-v', 'error', *inputs, '-an', '-sn', '-dn', '-vf', filters,
                              '-frames:v', str(count), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
                              '-maxrate', '3000k', '-bufsize', '6000k', '-pix_fmt', 'yuv420p', '-threads', '1',
                              '-fs', str(byte_bound(duration)), '-progress', str(progress), str(path)],
                             max(limits.media_seconds, min(limits.job_seconds, math.ceil(duration * 2))), progress=progress)
                if actual != count or path.stat().st_size >= byte_bound(duration):
                    raise ValueError('The video rendition exceeded its frame or storage bounds.')
            finally:
                if source and clip.get('object_key'):
                    source.unlink(missing_ok=True)
            paths.append(path)
        listing = folder / 'segments.txt'
        listing.write_text(''.join(f"file '{path.name}'\n" for path in paths))
        run(['-v', 'error', '-protocol_whitelist', 'file', '-f', 'concat', '-safe', '1', '-i', str(listing),
             '-i', str(directory / 'pending.wav'), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
             '-c:a', 'aac', '-b:a', '96k', '-threads', '1', '-movflags', '+faststart',
             '-fs', str(byte_bound(timeline['duration'])), str(destination)], limits.media_seconds)
        if destination.stat().st_size >= byte_bound(timeline['duration']):
            raise ValueError('The video rendition exceeded its storage bound.')
    return True
