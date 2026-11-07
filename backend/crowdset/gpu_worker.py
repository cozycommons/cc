"""Single-job, local-spool renderer for normalized Crowdset picture edits."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import threading
import subprocess
import sys
import time

FPS = 24
WIDTH, HEIGHT = 1920, 1080
MAX_SECONDS = 14400
MAX_DISK = 60 * 1024 ** 3
FREE_DISK = 8 * 1024 ** 3


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as output:
        json.dump(value, output, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 ** 2), b''):
            result.update(chunk)
    return result.hexdigest()


def manifest(value, *, allow_gaps=False):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('Unsupported edit manifest')
    sources, segments = value.get('sources'), value.get('segments')
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 128:
        raise ValueError('Expected 1–128 normalized sources')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 512:
        raise ValueError('Expected 1–512 picture segments')
    for key, source in sources.items():
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', key) or not isinstance(source, dict):
            raise ValueError('Invalid source ID')
        if not re.fullmatch(r'[a-f0-9]{64}', str(source.get('sha256', ''))):
            raise ValueError('Every source requires a SHA256')
        if type(source.get('bytes')) is not int or not 0 < source['bytes'] <= 16 * 1024 ** 3:
            raise ValueError('Invalid source size')
    if not isinstance(value.get('audio_source'), str) or value['audio_source'] not in sources:
        raise ValueError('Official audio source is missing')
    total = 0
    for segment in segments:
        if not isinstance(segment, dict) or not (allow_gaps and 'source' in segment and segment['source'] is None or
                isinstance(segment.get('source'), str) and segment['source'] in sources):
            raise ValueError('Unknown picture source')
        if (type(segment.get('start_frame')) is not int or type(segment.get('frames')) is not int
                or segment['start_frame'] < 0 or segment['frames'] <= 0
                or segment['start_frame'] + segment['frames'] > MAX_SECONDS * FPS):
            raise ValueError('Invalid frame interval')
        total += segment['frames']
    if total > MAX_SECONDS * FPS:
        raise ValueError('Edit exceeds four hours')
    return value


def probe(binary, path, *, count=False, formats='mov'):
    args = [binary, '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist', formats]
    if count:
        args += ['-count_packets']
    result = subprocess.run(args + ['-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('Cannot inspect the normalized MP4')
    metadata = json.loads(result.stdout)
    for stream in metadata['streams']:
        if not stream.get('duration') and metadata.get('format', {}).get('duration'):
            stream['duration'] = str(max(0, float(metadata['format']['duration']) - float(stream.get('start_time') or 0)))
    return metadata['streams']


def check_video(streams, *, allow_normalization=False):
    pictures = [s for s in streams if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic')]
    if len(pictures) != 1:
        raise ValueError('Expected one picture stream')
    stream = pictures[0]
    if allow_normalization:
        if (stream.get('codec_name') not in ('h264', 'hevc', 'mpeg4', 'mjpeg', 'vp8', 'vp9', 'av1')
                or not 0 < stream.get('width', 0) <= 3840 or not 0 < stream.get('height', 0) <= 3840
                or stream['width'] * stream['height'] > 3840 * 2160):
            raise ValueError('Worker picture inputs must use a supported codec and fit within 4K')
        return stream
    if (stream['codec_name'] != 'h264' or stream['width'] != WIDTH or stream['height'] != HEIGHT
            or stream['pix_fmt'] != 'yuv420p' or stream['r_frame_rate'] != '24/1'
            or stream.get('avg_frame_rate', '24/1') != '24/1' or abs(float(stream.get('start_time', 0))) > 1e-6
            or stream.get('sample_aspect_ratio', '1:1') != '1:1'
            or any(item.get('rotation', 0) for item in stream.get('side_data_list', []))):
        raise ValueError('Sources must be normalized H.264 1080p24 SDR with square pixels')
    if stream.get('color_transfer') in ('smpte2084', 'arib-std-b67') or stream.get('color_primaries') == 'bt2020':
        raise ValueError('Normalize HDR before rendering')
    return stream


def bound(frames):
    return math.ceil(frames / FPS * 500000) + 2 * 1024 ** 2


def disk_admission(root, needed):
    used = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    if used + needed > MAX_DISK or shutil.disk_usage(root).free < needed + FREE_DISK:
        raise ValueError('Worker disk budget is full; existing sources and outputs are retained')


def render(root, job, value, ffmpeg, ffprobe, encoder='h264_nvenc', *, normalize_sources=False, progress_directory=None):
    value = manifest(value, allow_gaps=normalize_sources)
    started = time.time()
    folder = root / 'work' / job
    output = root / 'outputs' / f'{job}.mp4'
    if output.exists():
        raise ValueError('This job already has a rendered output')
    folder.mkdir(mode=0o700, parents=True)
    frames = sum(s['frames'] for s in value['segments'])
    disk_admission(root, 2 * bound(frames) + len(value['segments']) * 2 * 1024 ** 2)
    paths, metadata = {}, {}
    picture_sources = {s['source'] for s in value['segments'] if s['source'] is not None}
    formats = 'mov,matroska,webm' if normalize_sources else 'mov'
    for key, source in value['sources'].items():
        write_json(root / 'status.json', {'state': 'rendering', 'job': job, 'phase': 'validating',
                   'updated_at': time.time(), 'pid': os.getpid()})
        path = root / 'sources' / f'{source["sha256"]}.mp4'
        if path.is_symlink() or not path.is_file() or path.stat().st_size != source['bytes'] or digest(path) != source['sha256']:
            raise ValueError('Source is missing or its SHA256/size changed')
        paths[key] = path
        metadata[key] = probe(ffprobe, path, formats=formats)
        if not normalize_sources or key in picture_sources:
            check_video(metadata[key], allow_normalization=normalize_sources)
    audio = [s for s in metadata[value['audio_source']] if s['codec_type'] == 'audio']
    if (len(audio) != 1 or audio[0]['codec_name'] != 'aac'
            or abs(float(audio[0].get('start_time', 0))) > 1e-6
            or float(audio[0].get('duration', 0)) + 0.1 < frames / FPS):
        raise ValueError('The official source needs one AAC soundtrack covering the full edit')
    completed = 0
    parts = []
    def run(arguments, duration, progress=None):
        with (folder / 'ffmpeg.log').open('ab') as log:
            process = subprocess.Popen([ffmpeg, '-nostdin', '-hide_banner', '-y', '-threads', '2', *arguments],
                                       stdout=subprocess.DEVNULL, stderr=log)
            deadline = time.monotonic() + max(120, duration * 2)
            try:
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise ValueError('Rendering exceeded its deadline')
                    disk_admission(root, 0)
                    done = 0
                    if progress and progress.exists():
                        matches = re.findall(r'^frame=(\d+)$', progress.read_text(), re.MULTILINE)
                        done = int(matches[-1]) if matches else 0
                    write_json(root / 'status.json', {'state': 'rendering', 'job': job, 'pid': os.getpid(), 'updated_at': time.time(),
                               'completed_frames': min(frames, completed + done), 'total_frames': frames})
                    time.sleep(0.5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if process.returncode:
                raise ValueError('FFmpeg failed; see the job ffmpeg.log')
    for index, segment in enumerate(value['segments']):
        info = check_video(metadata[segment['source']], allow_normalization=normalize_sources) if segment['source'] else None
        if info and float(info.get('duration') or 0) * FPS + 1 < segment['start_frame'] + segment['frames']:
            raise ValueError('Picture interval exceeds source duration')
        part = folder / f'{index}.mp4'
        progress = folder / f'{index}.progress'
        gpu = (['-hwaccel', 'cuda'] + ([] if normalize_sources else ['-hwaccel_output_format', 'cuda'])) if encoder == 'h264_nvenc' and (not normalize_sources or info and info['codec_name'] in ('h264', 'hevc', 'vp8', 'vp9')) else []
        settings = (['-preset', 'p4', '-tune', 'hq', '-rc', 'vbr', '-cq', '23'] if encoder == 'h264_nvenc'
                    else ['-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p'])
        timestamp = segment['start_frame'] / FPS
        if info:
            inputs = ['-ss', str(timestamp), *gpu, '-protocol_whitelist', 'file', '-format_whitelist', formats,
                      '-i', str(paths[segment['source']])]
            if normalize_sources:
                inputs = ['-copyts', '-seek_timestamp', '1', *inputs]
        else:
            inputs = ['-f', 'lavfi', '-i', f'color=c=0x243027:s={WIDTH}x{HEIGHT}:r={FPS}']
        filters = []
        if normalize_sources and info:
            tone = ('zscale=t=linear:npl=100,format=gbrpf32le,tonemap=hable:desat=0,'
                    'zscale=p=bt709:t=bt709:m=bt709:r=tv,' if info.get('color_transfer') in ('smpte2084', 'arib-std-b67') else '')
            filters = ['-vf', tone + f'trim=start={timestamp},setpts=PTS-({timestamp})/TB,'
                       f"scale=w='if(gt(dar,{WIDTH}/{HEIGHT}),{WIDTH},max(2,trunc({HEIGHT}*dar/2)*2))':"
                       f"h='if(gt(dar,{WIDTH}/{HEIGHT}),max(2,trunc({WIDTH}/dar/2)*2),{HEIGHT})':out_range=tv,setsar=1,"
                       f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x243027,'
                       f'fps={FPS}:start_time=0,tpad=stop_mode=add:stop_duration={segment["frames"] / FPS},format=yuv420p']
        colors = ['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv'] if normalize_sources else []
        if progress_directory is not None:
            write_json(progress_directory / 'progress.json', {
                'stage': 'Rendering video on the PC GPU…' if encoder == 'h264_nvenc' else 'Rendering video on the PC CPU…',
                'processing': {'phase': 'render', 'started_at': started, 'engine': encoder},
                'render': {'file': str(progress.relative_to(progress_directory)), 'completed_frames': completed,
                           'segment_frames': segment['frames'], 'total_frames': frames},
            })
        run(['-v', 'error', *inputs,
             '-map', '0:v:0', '-an', '-sn', '-dn', '-frames:v', str(segment['frames']),
             *filters, '-c:v', encoder, *settings, *colors, '-profile:v', 'high', '-b:v', '3000k', '-maxrate', '3000k',
             '-bufsize', '6000k', '-g', '48', '-bf', '0' if normalize_sources else '2', '-r', '24', '-fps_mode', 'cfr',
             '-map_metadata', '-1', '-fs', str(bound(segment['frames'])), '-progress', str(progress), str(part)],
            segment['frames'] / FPS, progress)
        info = check_video(probe(ffprobe, part, count=True))
        if int(info['nb_read_packets']) != segment['frames'] or part.stat().st_size >= bound(segment['frames']):
            raise ValueError('Encoded segment failed its frame/byte bounds')
        parts.append(part)
        completed += segment['frames']
    if progress_directory is not None:
        write_json(progress_directory / 'progress.json', {'stage': 'Combining video and official audio…',
                   'processing': {'phase': 'finalize', 'started_at': started, 'updated_at': time.time(), 'engine': encoder}})
    listing = folder / 'segments.txt'
    listing.write_text(''.join(f"file '{p.name}'\nduration {segment['frames'] / FPS:.9f}\n"
                               for p, segment in zip(parts, value['segments'])))
    pending = folder / 'output.mp4'
    run(['-v', 'error', '-protocol_whitelist', 'file', '-f', 'concat', '-safe', '1', '-i', str(listing),
         '-protocol_whitelist', 'file', '-format_whitelist', 'mov', '-i', str(paths[value['audio_source']]),
         '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', '-t', str(frames / FPS), '-map_metadata', '-1',
         '-movflags', '+faststart', '-fs', str(bound(frames)), str(pending)], frames / FPS)
    streams = probe(ffprobe, pending, count=True)
    info = check_video(streams)
    if (int(info['nb_read_packets']) != frames or abs(float(info['duration']) - frames / FPS) > 1 / FPS
            or pending.stat().st_size >= bound(frames)
            or len([s for s in streams if s['codec_type'] == 'audio' and s['codec_name'] == 'aac']) != 1):
        raise ValueError('Combined MP4 failed validation')
    result = {'job': job, 'encoder': encoder, 'frames': frames, 'duration': frames / FPS,
              'bytes': pending.stat().st_size, 'sha256': digest(pending), 'elapsed_seconds': time.time() - started}
    pending.replace(output)
    write_json(root / 'completed' / f'{job}.json', result)
    shutil.rmtree(folder)
    return result


@contextmanager
def single_worker(root):
    with (root / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another worker already owns this spool') from exc
        yield


def serve(root, ffmpeg, ffprobe, encoder, stop=None):
    stop = stop or threading.Event()
    try:
        from compute.reservation import pause_requested
    except ModuleNotFoundError as exc:
        if exc.name not in {'compute', 'compute.reservation'}:
            raise
        while not stop.is_set():
            write_json(root / 'status.json', {'state': 'idle', 'updated_at': time.time(), 'pid': os.getpid(), 'encoder': encoder})
            stop.wait(1)
        return
    with single_worker(root):
        for abandoned in (root / 'running').glob('*.json'):
            write_json(root / 'failed' / abandoned.name, {'error': 'Interrupted job; source manifest and work retained'})
            abandoned.replace(root / 'failed' / f'{abandoned.stem}.manifest.json')
        while not stop.is_set():
            if pause_requested(root) or (root / 'update-requested').exists():
                write_json(root / 'status.json', {'state': 'paused', 'updated_at': time.time(), 'pid': os.getpid(), 'encoder': encoder})
                stop.wait(1)
                continue
            write_json(root / 'status.json', {'state': 'idle', 'updated_at': time.time(), 'pid': os.getpid(), 'encoder': encoder})
            jobs = sorted((root / 'inbox').glob('*.json'))
            if not jobs:
                stop.wait(2)
                continue
            queued = jobs[0]
            job = queued.stem
            if not re.fullmatch(r'[a-f0-9]{32}', job):
                queued.replace(root / 'failed' / queued.name)
                continue
            running = root / 'running' / queued.name
            queued.replace(running)
            try:
                if running.stat().st_size > 512 * 1024:
                    raise ValueError('Manifest too large')
                render(root, job, json.loads(running.read_text()), ffmpeg, ffprobe, encoder)
                running.replace(root / 'completed' / f'{job}.manifest.json')
            except Exception as exc:
                write_json(root / 'failed' / f'{job}.json', {'job': job, 'error': str(exc), 'updated_at': time.time()})
                running.replace(root / 'failed' / f'{job}.manifest.json')


def main():
    runtime = os.environ.get('CROWDSET_WORKER_PYTHON')
    if runtime and os.environ.get('CROWDSET_WORKER_URL') and '--help' not in sys.argv and os.path.realpath(runtime) != os.path.realpath(sys.executable):
        os.execv(runtime, [runtime, __file__, *sys.argv[1:]])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--ffprobe', required=True)
    parser.add_argument('--encoder', choices=['h264_nvenc', 'libx264'], default='h264_nvenc')
    args = parser.parse_args()
    os.umask(0o077)
    root = args.root.resolve()
    for name in ('inbox', 'running', 'completed', 'failed', 'work', 'sources', 'outputs'):
        (root / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    if os.environ.get('CROWDSET_WORKER_URL'):
        from crowdset.remote_agent import serve as remote_serve
        remote_serve(root, args.ffmpeg, args.ffprobe, args.encoder, stop)
    else:
        serve(root, args.ffmpeg, args.ffprobe, args.encoder, stop)
    write_json(root / 'status.json', {'state': 'stopped', 'updated_at': time.time(), 'pid': os.getpid()})


if __name__ == '__main__':
    main()
