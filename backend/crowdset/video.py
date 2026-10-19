"""One deterministic visual cut on the compiled audio's clock."""
import math
import re
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from .timestamps import capture_metadata

FORMATS = 'wav,mov,mp3,aac,flac,ogg,matroska,webm'
FRAME_RATE = 24
WIDTH, HEIGHT = 1920, 1080
PROBE_BYTES = 128 * 1024 ** 2
BYTES_PER_SECOND = 420_000  # 3 Mbps video + 96 kbps audio, container/headroom.


def byte_bound(duration):
    return math.ceil(duration * BYTES_PER_SECOND) + 2 * 1024 ** 2


def copy_bound(clip, duration):
    return clip['bytes'] + math.ceil(duration * 16_000) + 16 * 1024 ** 2


def copy_candidate(timeline, clips):
    included = [c for c in clips if c.get('included', True) and c.get('role') != 'reference']
    if len(included) != 1 or len(timeline['segments']) != 1 or abs(timeline['origin_seconds']) > 1e-6:
        return None
    clip, segment = included[0], timeline['segments'][0]
    media = clip.get('video', {})
    if (segment['clip_id'] != clip['id'] or segment['first_frame'] != 0 or abs(segment['offset']) > 1e-6
            or segment.get('fade_in', 0) != 0 or abs(media.get('start', 1)) > 1e-6 or abs(media.get('audio_start', 1)) > 1e-6
            or abs(clip['duration'] - timeline['duration']) > 1e-6 or not clip.get('bytes')):
        return None
    # AAC padding can leave a fraction of a second after the last video picture.
    tail = timeline['duration'] - media['end']
    if not 0 <= tail <= .1 or any(g['first_frame'] < segment['last_frame'] for g in timeline['gaps']):
        return None
    return clip


def output_bound(timeline, clips):
    candidate = copy_candidate(timeline, clips)
    return max(byte_bound(timeline['duration']), copy_bound(candidate, timeline['duration'])) if candidate else byte_bound(timeline['duration'])


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


def capture(source, limits):
    report = run(['-v', 'info', '-protocol_whitelist', 'file', '-format_whitelist', FORMATS,
                  '-i', str(source), '-t', '0', '-f', 'null', '-'], min(30, limits.media_seconds))
    return capture_metadata(report)


def probe(source, limits, workdir=None):
    report = run(['-v', 'info', '-copyts', '-protocol_whitelist', 'file',
                  '-format_whitelist', FORMATS, '-i', str(source),
                  '-map', '0:V:0?', '-map', '0:a:0', '-vf', 'showinfo', '-af', 'ashowinfo',
                  '-frames:v', '1', '-frames:a', '1', '-f', 'null', '-'], min(30, limits.media_seconds))
    input_report = report.split('Output #', 1)[0]
    streams = re.findall(r'Stream #0:[^\n]*Video:[^\n]*', input_report)
    compatible = (len(streams) == 1 and 'Video: h264 ' in streams[0]
                  and re.search(r'\byuv420p(?:\(|,)', streams[0]) is not None
                  and f'{WIDTH}x{HEIGHT} ' in streams[0] and 'SAR 1:1' in streams[0]
                  and 'progressive' in streams[0] and '24 fps' in streams[0]
                  and not re.search(r'rotation|displaymatrix|bt2020|smpte2084|arib-std-b67', input_report, re.IGNORECASE))
    picture = re.search(r'\[Parsed_showinfo_\d+[^\n]*?pts_time:([\d.e+-]+)', report)
    if not picture:
        return None
    audio = re.search(r'\[Parsed_ashowinfo_\d+[^\n]*?pts_time:([\d.e+-]+)', report)
    if not audio:
        # FFmpeg can stop the combined probe after video before logging any audio frame.
        report = run(['-v', 'info', '-copyts', '-protocol_whitelist', 'file',
                      '-format_whitelist', FORMATS, '-i', str(source), '-map', '0:a:0',
                      '-vn', '-af', 'ashowinfo', '-frames:a', '1', '-f', 'null', '-'], min(30, limits.media_seconds))
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
        frame_numbers = set()
        with packets.open() as rows:
            for row in rows:
                if row.startswith('#tb 0:'):
                    numerator, denominator = row.split(':')[1].strip().split('/')
                    scale = int(numerator) / int(denominator)
                elif not row.startswith('#') and row.strip() and scale is not None:
                    fields = row.split(',')
                    timestamp = (int(fields[2]) + int(fields[3])) * scale
                    end = max(end if end is not None else timestamp, timestamp)
                    if compatible:
                        frame = (int(fields[2]) * scale - start) * FRAME_RATE
                        number = round(frame)
                        if (abs(frame - number) > 1e-4 or abs(int(fields[3]) * scale * FRAME_RATE - 1) > 1e-4
                                or number < 0 or number in frame_numbers):
                            compatible = False
                            frame_numbers.clear()
                        else:
                            frame_numbers.add(number)
        if end is None or not math.isfinite(end) or end <= start:
            raise ValueError('Cannot establish this video’s duration.')
    compatible = bool(compatible and frame_numbers and min(frame_numbers) == 0
                      and max(frame_numbers) + 1 == len(frame_numbers)
                      and abs(start) < 1e-6 and abs(audio_start) < 1e-6)
    return {'start': start - audio_start, 'end': end - audio_start, 'audio_start': audio_start,
            'copy_compatible': compatible}


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


def render(timeline, clips, originals, set_id, directory, limits, *, on_progress=None):
    if not timeline['segments']:
        return False
    by_id = {c['id']: c for c in clips}
    destination = directory / 'pending.mp4'
    candidate = copy_candidate(timeline, clips)
    if candidate:
        if on_progress:
            on_progress('Checking whether the original video can be reused…', 'render')
        source = originals.materialize(set_id, candidate, directory)
        media = candidate['video']
        if 'copy_compatible' not in media:
            media = probe(source, limits, directory)
            candidate['video'] = media
        if media and media.get('copy_compatible') and copy_candidate(timeline, clips):
            bound = copy_bound(candidate, timeline['duration'])
            if on_progress:
                on_progress('Combining original video with the finished audio…', 'finalize')
            try:
                run(['-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', FORMATS, '-i', str(source),
                     '-i', str(directory / 'pending.wav'), '-map', '0:V:0', '-map', '1:a:0',
                     '-c:v', 'copy', '-c:a', 'aac', '-b:a', '96k', '-threads', '1',
                     '-map_metadata', '-1', '-movflags', '+faststart', '-fs', str(bound), str(destination)], limits.media_seconds)
                if destination.stat().st_size >= bound:
                    raise ValueError('The copied video exceeded its storage bound.')
                return True
            finally:
                if candidate.get('object_key'):
                    source.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='video-', dir=directory) as temporary:
        folder = Path(temporary)
        paths = []
        completed_frames = 0
        total_frames = sum(s['last_frame'] - s['first_frame'] for s in timeline['segments'] + timeline['gaps'])
        for index, segment in enumerate(sorted(timeline['segments'] + timeline['gaps'], key=lambda s: s['first_frame'])):
            count = segment['last_frame'] - segment['first_frame']
            duration = count / FRAME_RATE
            clip = by_id.get(segment.get('clip_id'))
            source = None
            if clip:
                if on_progress:
                    on_progress('Loading recording for the video cut…', 'render')
                source = originals.materialize(set_id, clip, directory)
                timestamp = segment['start'] - segment['offset'] + clip['video']['audio_start']
                inputs = ['-copyts', '-seek_timestamp', '1', '-ss', str(max(0, timestamp)),
                          '-protocol_whitelist', 'file', '-format_whitelist', FORMATS, '-i', str(source), '-map', '0:V:0']
                filters = picture_filters(timestamp, duration)
            else:
                inputs = ['-f', 'lavfi', '-i', f'color=c=0x243027:s={WIDTH}x{HEIGHT}:r={FRAME_RATE}']
                filters = 'null'
            path = folder / f'{index}.mp4'
            progress = folder / f'{index}-progress.txt'
            if on_progress:
                on_progress('Rendering video…', 'render', render={'file': str(progress.relative_to(directory)),
                            'completed_frames': completed_frames, 'segment_frames': count, 'total_frames': total_frames})
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
            completed_frames += count
        listing = folder / 'segments.txt'
        listing.write_text(''.join(f"file '{path.name}'\n" for path in paths))
        if on_progress:
            on_progress('Combining video and audio…', 'finalize')
        run(['-v', 'error', '-protocol_whitelist', 'file', '-f', 'concat', '-safe', '1', '-i', str(listing),
             '-i', str(directory / 'pending.wav'), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
             '-c:a', 'aac', '-b:a', '96k', '-threads', '1', '-movflags', '+faststart',
             '-fs', str(byte_bound(timeline['duration'])), str(destination)], limits.media_seconds)
        if destination.stat().st_size >= byte_bound(timeline['duration']):
            raise ValueError('The video rendition exceeded its storage bound.')
    return True


def picture_filters(timestamp, duration):
    return (f'trim=start={timestamp},setpts=PTS-({timestamp})/TB,'
            f"scale=w='if(gt(dar,{WIDTH}/{HEIGHT}),{WIDTH},max(2,trunc({HEIGHT}*dar/2)*2))':"
            f"h='if(gt(dar,{WIDTH}/{HEIGHT}),max(2,trunc({WIDTH}/dar/2)*2),{HEIGHT})',setsar=1,"
            f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x243027,setsar=1,'
            f'fps={FRAME_RATE}:start_time=0,tpad=stop_mode=add:stop_duration={duration}:color=0x243027')
