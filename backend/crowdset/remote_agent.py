"""Outbound media runner. Bucket credentials never leave the control plane."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

import httpx

from . import gpu_worker, video
from .audio import probe
from .blobs import digest
from .limits import Limits
from .storage import OriginalStore
from .worker import process, write_json


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
        return self.control.download(clip['object_key'], directory / (clip['id'] + '.original'), clip['bytes'], clip['sha256'])

    def admit(self, limits, incoming=0, work_needed=0, **kwargs):
        gpu_worker.disk_admission(self.spool, work_needed)


def flatten(directory, result, ffmpeg, ffprobe, encoder):
    composition = result.get('composition')
    if not composition:
        return
    visual = result['video_timeline']
    if visual['gaps']:
        raise ValueError('The full set has picture gaps. It cannot yet be flattened by the GPU worker.')
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
    add('official', directory / 'pending.mp4')
    segments = []
    for segment in visual['segments']:
        asset_id = segment.get('asset_id')
        if asset_id:
            add(asset_id, directory / composition['assets'][asset_id]['file'])
        segments.append({'source': asset_id or 'official',
                         'start_frame': 0 if asset_id else segment['first_frame'],
                         'frames': segment['last_frame'] - segment['first_frame']})
    job = uuid4().hex
    gpu_worker.render(root, job, {'version': 1, 'audio_source': 'official', 'sources': sources, 'segments': segments}, ffmpeg, ffprobe, encoder)
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
                subprocess.run(code, check=True, timeout=limits.media_seconds + 10, start_new_session=True,
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
    previous = sorted(root.glob('remote/*/*/' + job['set_id'] + '/published.json'), key=lambda p: p.stat().st_mtime)
    if previous:
        for clip in data['clips']:
            for suffix in ('.wav', '.npy', '.analysis.json', '.alignment.json'):
                cached = previous[-1].parent / (clip['id'] + suffix)
                if cached.is_file():
                    shutil.copyfile(cached, directory / cached.name)
    write_json(directory / 'job.json', data)
    process(directory, originals=WorkerOriginals(directory.parent, control), limits=limits)
    result = json.loads((directory / 'result.json').read_text())
    flatten(directory, result, ffmpeg, ffprobe, encoder)
    for name in ('pending.wav', 'pending.mp4'):
        if (directory / name).is_file():
            control.upload(directory / name, mime='video/mp4' if name.endswith('.mp4') else 'audio/wav')
    for preview in (result.get('scrub_previews') or {}).values():
        for name in preview['sheets']:
            control.upload(directory / name, mime='image/jpeg')
    control.call('publish', result=result)


def serve(root, ffmpeg, ffprobe, encoder, stop):
    control = Control(os.environ['CROWDSET_WORKER_URL'], os.environ['CROWDSET_WORKER_TOKEN'])
    with gpu_worker.single_worker(root):
        while not stop.is_set():
            status = {'pid': os.getpid(), 'updated_at': time.time()}
            if (root / 'update-requested').exists():
                gpu_worker.write_json(root / 'status.json', {**status, 'state': 'paused'})
                stop.wait(1)
                continue
            try:
                job = control.call('claim')
            except Exception:
                gpu_worker.write_json(root / 'status.json', {**status, 'state': 'offline'})
                stop.wait(10)
                continue
            if not job:
                gpu_worker.write_json(root / 'status.json', {**status, 'state': 'idle'})
                stop.wait(5)
                continue
            heartbeat_stop = threading.Event()
            control.job = job
            def heartbeat():
                while not heartbeat_stop.wait(15):
                    try:
                        directory = root / 'remote' / job['id'] / job['claim'] / job['set_id']
                        progress = directory / 'progress.json'
                        stage = json.loads(progress.read_text()).get('stage') if progress.exists() else None
                        control.call('heartbeat', stage=stage or ('Downloading YouTube on the PC…' if job['kind'] == 'youtube' else 'Processing on the PC…'))
                        gpu_worker.write_json(root / 'status.json', {'state': 'rendering', 'job': job['id'],
                                             'pid': os.getpid(), 'updated_at': time.time()})
                    except Exception:
                        pass  # Publication still requires a live lease; never publish offline.
            thread = threading.Thread(target=heartbeat, daemon=True)
            thread.start()
            try:
                gpu_worker.write_json(root / 'status.json', {**status, 'state': 'rendering', 'job': job['id']})
                execute(root, control, job, ffmpeg, ffprobe, encoder)
                directory = root / 'remote' / job['id'] / job['claim'] / job['set_id']
                write_json(directory / 'published.json', {'job': job['id'], 'published_at': time.time()})
                # Cloud publication has committed; these are reconstructible worker staging files.
                for pattern in ('pending.*', 'source.*', 'overlay-*.mp4'):
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
            finally:
                heartbeat_stop.set()
                thread.join(timeout=125)
                control.job = None
