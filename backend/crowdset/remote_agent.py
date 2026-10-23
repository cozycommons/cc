"""Outbound media runner. Bucket credentials never leave the control plane."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

import httpx

from . import gpu_worker, video
from .audio import probe
from .blobs import digest
from .limits import Limits
from .progress import snapshot
from .storage import OriginalStore
from .worker import process, write_json

SOURCE_CACHE_BYTES = 16 * 1024 ** 3


class Control:
    def __init__(self, url, token, job=None):
        if not url.startswith('https://') and not url.startswith('http://127.0.0.1:'):
            raise ValueError('Worker control requires HTTPS.')
        self.url, self.token, self.job = url.rstrip('/'), token, job
        self.transport = None

    def call(self, operation, **body):
        if self.job:
            body = {'job': self.job['id'], 'claim': self.job['claim'], **body}
        with httpx.Client(timeout=120, follow_redirects=False, transport=self.transport) as client:
            response = client.post(self.url + '/crowdset/worker/' + operation, json=body,
                                   headers={'Authorization': 'Bearer ' + self.token})
            response.raise_for_status()
            return response.json()

    def download(self, key, destination, size, checksum=None):
        destination = Path(destination)
        if destination.is_file() and destination.stat().st_size == size and (not checksum or digest(destination) == checksum):
            return destination
        url = self.call('read', key=key)['url']
        partial = destination.with_suffix('.download')
        try:
            written = 0
            with httpx.Client(timeout=120, follow_redirects=False) as client, client.stream('GET', url) as response:
                response.raise_for_status()
                with partial.open('wb') as output:
                    for chunk in response.iter_bytes(1024 ** 2):
                        written += len(chunk)
                        if written > size:
                            raise ValueError('Source exceeded its reserved size.')
                        output.write(chunk)
            if written != size or (checksum and digest(partial) != checksum):
                raise ValueError('Source failed its size or hash check.')
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
        return destination

    def upload(self, path, name=None, mime='application/octet-stream'):
        path = Path(path)
        name = name or path.name
        value = self.call('reserve', name=name, bytes=path.stat().st_size, sha256=digest(path), mime=mime)
        if value.get('complete'):
            return value
        with path.open('rb') as source, httpx.Client(timeout=120, follow_redirects=False) as client:
            number = 1
            while True:
                chunk = source.read(8 * 1024 ** 2)
                if not chunk:
                    break
                part = self.call('part', name=name, part=number)
                if part['bytes'] != len(chunk):
                    raise ValueError('Transfer part length changed.')
                response = client.put(part['url'], content=chunk)
                response.raise_for_status()
                number += 1
        return self.call('complete', name=name)


class WorkerOriginals(OriginalStore):
    def __init__(self, root, control):
        super().__init__(root)
        self.control = control
        self.spool = root.parents[2]
        self.blobs = True

    def materialize(self, set_id, clip, directory):
        target = directory / (clip['id'] + '.original')
        cache = self.spool / 'source-cache'
        cache.mkdir(exist_ok=True, mode=0o700)
        cached = cache / (clip['sha256'] + '.original')
        entries = sorted((p for p in cache.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime)
        used = sum(p.stat().st_size for p in entries)
        incoming = max(0, clip['bytes'] - (cached.stat().st_size if cached.exists() else 0))
        for entry in entries:
            if used + incoming <= SOURCE_CACHE_BYTES:
                break
            if entry != cached and entry.stat().st_nlink == 1:
                used -= entry.stat().st_size
                entry.unlink()
        if used + incoming > SOURCE_CACHE_BYTES:
            return self.control.download(clip['object_key'], target, clip['bytes'], clip['sha256'])
        source = self.control.download(clip['object_key'], cached, clip['bytes'], clip['sha256'])
        source.touch()
        target.unlink(missing_ok=True)
        os.link(source, target)
        return target

    def admit(self, limits, incoming=0, work_needed=0, **kwargs):
        gpu_worker.disk_admission(self.spool, work_needed)


def flatten(directory, result, originals, data, limits, ffmpeg, ffprobe, encoder):
    if not result.get('video_playable'):
        return
    visual = result['video_timeline']
    root = directory / 'gpu'
    for name in ('sources', 'work', 'outputs', 'completed'):
        (root / name).mkdir(parents=True, exist_ok=True)
    sources = {}
    def add(key, path):
        checksum = digest(path)
        target = root / 'sources' / (checksum + '.mp4')
        if not target.exists():
            os.link(path, target)
        sources[key] = {'sha256': checksum, 'bytes': path.stat().st_size}
    clips = {clip['id']: clip for clip in result['clips']}
    materialized = []
    def original(clip_id):
        path = originals.materialize(data['id'], clips[clip_id], directory)
        materialized.append(path)
        if clip_id not in sources:
            add(clip_id, path)
        return path
    segments = []
    for segment in sorted(visual['segments'] + visual['gaps'], key=lambda s: s['first_frame']):
        clip_id = segment.get('clip_id')
        timestamp = 0
        if clip_id:
            original(clip_id)
            timestamp = segment['start'] - segment['offset'] + clips[clip_id]['video']['audio_start']
        segments.append({'source': clip_id,
                         'start_frame': round(max(0, timestamp) * gpu_worker.FPS),
                         'frames': segment['last_frame'] - segment['first_frame']})
    audio_source = None
    official = data.get('soundtrack_clip_id')
    if official:
        path = original(official)
        audio = [s for s in gpu_worker.probe(ffprobe, path, formats=video.FORMATS) if s['codec_type'] == 'audio']
        if (len(audio) == 1 and audio[0]['codec_name'] == 'aac'
                and abs(float(audio[0].get('start_time', 0))) < 1e-6
                and float(audio[0].get('duration') or 0) + .1 >= sum(s['frames'] for s in segments) / gpu_worker.FPS
                and 0 < int(audio[0].get('bit_rate') or 0) <= 512000):
            audio_source = official
    if audio_source is None:
        audio_file = directory / 'audio-source.mp4'
        video.run(['-v', 'error', '-protocol_whitelist', 'file', '-i', str(directory / 'pending.wav'),
                   '-vn', '-c:a', 'aac', '-b:a', '192k', str(audio_file)], limits.media_seconds)
        audio_source = 'mixed_audio'
        add(audio_source, audio_file)
    job = uuid4().hex
    try:
        gpu_worker.render(root, job, {'version': 1, 'audio_source': audio_source, 'sources': sources, 'segments': segments},
                          ffmpeg, ffprobe, encoder, normalize_sources=True, progress_directory=directory)
    finally:
        for path in materialized:
            path.unlink(missing_ok=True)
    (root / 'outputs' / (job + '.mp4')).replace(directory / 'pending.mp4')
    result['composition'] = None
    for segment in visual['segments']:
        segment.pop('asset_id', None)


def execute(root, control, job, ffmpeg, ffprobe, encoder):
    control.job = job
    directory = root / 'remote' / job['id'] / job['claim'] / job['set_id']
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    limits = replace(Limits(**job['limits']), work_bytes=60 * 1024 ** 3, free_bytes=8 * 1024 ** 3)
    gpu_worker.disk_admission(root, 3 * limits.file_bytes)
    if job['kind'] in ('youtube', 'ingest'):
        if job['kind'] == 'youtube':
            source = directory / 'source.mp4'
            code = [sys.executable, '-m', 'crowdset.youtube', str(directory), job['url'], str(limits.file_bytes),
                    str(limits.recording_seconds), str(limits.media_seconds)]
            try:
                subprocess.run(code, check=True, timeout=limits.media_seconds + 10,
                               stdout=subprocess.DEVNULL, stderr=(directory / 'youtube.log').open('wb'))
            except subprocess.CalledProcessError:
                failure = directory / 'failure.json'
                raise ValueError(json.loads(failure.read_text())['error'] if failure.exists() else 'YouTube download failed on the PC.') from None
            result = json.loads((directory / 'result.json').read_text())
            control.upload(source, mime='video/mp4')
        else:
            source = control.download(job['input']['key'], directory / 'source.original', job['input']['bytes'])
            result = {}
        result.update(sha256=digest(source), duration=probe(source, limits=limits))
        if job['kind'] == 'youtube' or job['input']['clip']['kind'] == 'video':
            thumbnail = directory / 'thumbnail.jpg'
            video.thumbnail(source, thumbnail)
            if thumbnail.is_file():
                control.upload(thumbnail, mime='image/jpeg')
                result['thumbnail'] = thumbnail.name
        control.call('publish', result=result)
        return
    data = dict(job['snapshot'])
    # Full rebuild on the worker avoids relying on production's old local audio cache.
    data.update(playable=False, composition=None, previous_revision={}, mix_file=None, video_timeline=None, video_object=None)
    previous = sorted(root.glob('remote/*/*/' + job['set_id'] + '/job.json'), key=lambda p: p.stat().st_mtime)
    for clip in data['clips']:
        for manifest_path in reversed(previous):
            if manifest_path.parent == directory:
                continue
            cached_clips = json.loads(manifest_path.read_text()).get('clips', [])
            if not any(c['id'] == clip['id'] and c.get('sha256') == clip.get('sha256') for c in cached_clips):
                continue
            required = [manifest_path.parent / (clip['id'] + suffix) for suffix in ('.wav', '.npy', '.analysis.json')]
            if not all(p.is_file() for p in required):
                continue
            for cached in required + [manifest_path.parent / (clip['id'] + '.alignment.json')]:
                if cached.is_file():
                    shutil.copyfile(cached, directory / cached.name)
            break
    write_json(directory / 'job.json', data)
    originals = WorkerOriginals(directory.parent, control)
    process(directory, originals=originals, limits=limits, render_video=False)
    result = json.loads((directory / 'result.json').read_text())
    flatten(directory, result, originals, data, limits, ffmpeg, ffprobe, encoder)
    write_json(directory / 'progress.json', {'stage': 'Saving the finished cut to cloud storage…',
               'processing': {'phase': 'save', 'updated_at': time.time()}})
    for name in ('pending.wav', 'pending.mp4'):
        if (directory / name).is_file():
            control.upload(directory / name, mime='video/mp4' if name.endswith('.mp4') else 'audio/wav')
    for preview in (result.get('scrub_previews') or {}).values():
        for name in preview['sheets']:
            control.upload(directory / name, mime='image/jpeg')
    control.call('publish', result=result)


class Source:
    """Keep Crowdset's fenced media protocol behind the shared runner interface."""
    def __init__(self, root, ffmpeg, ffprobe, encoder, capacity=None):
        from compute.jobs import Resources
        self.capacity = capacity or Resources.environment(default_gpu=int(encoder == 'h264_nvenc'))
        self.root, self.ffmpeg, self.ffprobe, self.encoder = root, ffmpeg, ffprobe, encoder
        self.control = Control(os.environ['CROWDSET_WORKER_URL'], os.environ['CROWDSET_WORKER_TOKEN'])

    def claim(self):
        return self.control.call('claim-v2', capacity=self.capacity.model_dump(), encoder=self.encoder)

    def run(self, job):
        root = self.root
        control = Control(self.control.url, self.control.token, job)
        control.transport = self.control.transport
        ffmpeg, ffprobe, encoder = self.ffmpeg, self.ffprobe, self.encoder
        from compute.process import run as run_process
        from compute.runner import write_status
        from .compute_jobs import resources
        directory = root / 'remote' / job['id'] / job['claim'] / job['set_id']
        def heartbeat():
            value = snapshot(directory)
            write_status(root, 'rendering', job['id'])
            control.call('heartbeat', stage=value.get('stage') or 'Processing on the PC…',
                         processing=value.get('processing'))
        try:
            write_status(root, 'rendering', job['id'])
            if not resources(job['kind'], encoder).fits(self.capacity):
                raise ValueError('Crowdset job exceeds worker capacity')
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            request = directory / 'request.json'
            write_json(request, job)
            with (directory / 'worker.log').open('wb') as log:
                run_process([sys.executable, '-m', 'crowdset.remote_agent', '--root', str(root),
                             '--job', str(request), '--ffmpeg', ffmpeg, '--ffprobe', ffprobe,
                             '--encoder', encoder], log, job['limits']['job_seconds'], heartbeat)
            directory = root / 'remote' / job['id'] / job['claim'] / job['set_id']
            write_json(directory / 'published.json', {'job': job['id'], 'published_at': time.time()})
            # Cloud publication has committed; these are reconstructible worker staging files.
            for pattern in ('pending.*', 'source.*', 'overlay-*.mp4', 'audio-source.mp4'):
                for staged in directory.glob(pattern):
                    staged.unlink(missing_ok=True)
            shutil.rmtree(directory / 'gpu', ignore_errors=True)
            older = sorted(root.glob('remote/*/*/' + job['set_id'] + '/published.json'), key=lambda p: p.stat().st_mtime)
            for marker in older[:-1]:
                shutil.rmtree(marker.parent)
        except Exception as exc:
            message = 'A worker transfer failed. Original recordings are retained; retry shortly.' if isinstance(exc, httpx.HTTPError) else str(exc)[:500]
            write_json(root / 'failed' / (job['id'] + '.remote.json'), {'error': message, 'job': job['id']})
            try:
                control.call('fail', error=message)
            except Exception:
                pass


def serve(root, ffmpeg, ffprobe, encoder, stop):
    try:
        from compute.runner import serve as run_sources
    except ModuleNotFoundError as exc:
        if exc.name != 'compute':
            raise
        print('Waiting for the updater to install the shared compute runtime.', flush=True)
        with gpu_worker.single_worker(root):
            while not stop.is_set():
                state = 'paused' if (root / 'update-requested').exists() else 'idle'
                write_json(root / 'status.json', {'state': state, 'pid': os.getpid(), 'updated_at': time.time()})
                stop.wait(1)
        return
    sources = [Source(root, ffmpeg, ffprobe, encoder)]
    if os.environ.get('CC_COMPUTE_URL'):
        from compute.worker import configured_source
        sources.append(configured_source(root, sources[0].capacity))
    run_sources(root, sources, stop)


def main():
    parser = argparse.ArgumentParser(description='Execute one fenced Crowdset attempt')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--ffmpeg', required=True)
    parser.add_argument('--ffprobe', required=True)
    parser.add_argument('--encoder', choices=['h264_nvenc', 'libx264'], required=True)
    args = parser.parse_args()
    job = json.loads(args.job.read_text())
    control = Control(os.environ['CROWDSET_WORKER_URL'], os.environ['CROWDSET_WORKER_TOKEN'])
    execute(args.root, control, job, args.ffmpeg, args.ffprobe, args.encoder)


if __name__ == '__main__':
    main()
