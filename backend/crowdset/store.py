from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import unicodedata
from uuid import uuid4

from fastapi import HTTPException
import httpx

from .worker import write_json
from .config import env
from .limits import Limits
from .storage import OriginalStore
from .blobs import BlobError, environment, digest
from .audio import probe
from .youtube import canonical_url
from .progress import snapshot

ROOT = Path(__file__).resolve().parents[2] / '.crowdset'
if not ROOT.exists() and ROOT.with_name('.crowd-set').exists():
    ROOT = ROOT.with_name('.crowd-set')
EXTENSIONS = {'.wav', '.mp3', '.m4a', '.mp4', '.mov', '.aac', '.flac', '.ogg', '.webm'}
MAX_BYTES = 2 * 1024 ** 3
RESERVED_SLUGS = {'assets', 'health', 'session', 'sets'}


def set_slug(name, used):
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    base = re.sub(r'[^a-z0-9]+', '-', text).strip('-')[:100].rstrip('-') or 'set'
    slug = base
    suffix = 2
    while slug in used or slug in RESERVED_SLUGS:
        slug = f'{base}-{suffix}'
        suffix += 1
    return slug


class Store:
    def __init__(self, root=ROOT, *, limits=None, blobs=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.limits = limits or Limits.environment()
        self.blobs = blobs if blobs is not None else environment(self.root)
        if self.blobs:
            self.blobs.check_bucket(self.limits.file_bytes)
        self.originals = OriginalStore(self.root, self.blobs)
        self.lockfile = (self.root / '.lock').open('a')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lockfile.close()
            raise RuntimeError('Crowdset storage is already open. Stop the other API or wait for its worker deadline, then retry.')
        self.lock = threading.RLock()
        profiles = self.root / 'uploaders.json'
        self.uploaders = json.loads(profiles.read_text()) if profiles.exists() else {}
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.active = None
        self.upload = None
        self.process = None
        self.closed = False
        self.pending = {}
        self.batches = {}
        self.timer = None
        self.remote = None
        if env('CROWDSET_REMOTE_WORKER', '') == '1':
            from .remote import RemoteJobs
            if not self.blobs or not hasattr(self.blobs, 'signed') or not env('CROWDSET_WORKER_TOKEN'):
                raise ValueError('Remote processing requires R2 and a worker credential.')
            self.remote = RemoteJobs(self)
        paths = sorted(self.root.glob('*/set.json'))
        used_slugs = {json.loads(path.read_text()).get('slug') for path in paths}
        for path in paths:
            data = json.loads(path.read_text())
            if not data.get('slug'):
                data['slug'] = set_slug(data['name'], used_slugs)
                used_slugs.add(data['slug'])
                write_json(path, data)
            batch = data.get('batch')
            if batch:
                self.batches[data['id']] = {**batch, 'deadline': time.monotonic() + max(0, batch['expires_at'] - time.time())}
            if self.remote and data['status'] in ('importing', 'processing', 'queued'):
                continue
            if data['status'] == 'importing':
                saved = any(c.get('source_url') == data['youtube_import']['url'] for c in data['clips'])
                data.update(status='queued' if saved and data.get('dirty') else 'ready' if data.get('playable') else 'idle')
                data['youtube_import'].update(state='complete' if saved else 'failed', error=None if saved else 'YouTube import interrupted by a server restart. Paste the link again to retry.')
                write_json(path, data)
                self.cleanup_import(data)
            if data['status'] in ('processing', 'queued'):
                attempts = data.get('recovery_attempts', 0) + 1
                data.update(recovery_attempts=attempts, dirty=True)
                if attempts <= 2:
                    data.update(status='queued', error=None)
                    self.pending[data['id']] = time.monotonic() + 3
                else:
                    data.update(status='failed', error='Processing was interrupted repeatedly. Retry when the server is stable.')
                write_json(path, data)
            elif data['status'] == 'uploading' and not batch:
                data.update(status='ready' if data.get('playable') else 'idle', upload_notice='Upload interrupted. Reselect the same files to resume.', dirty=bool(data['clips']))
                write_json(path, data)
            for partial in path.parent.glob('*.part'):
                partial.unlink()
        if self.remote:
            self.remote.recover()
        self.expire_sessions()
        self.schedule()

    def close(self):
        with self.lock:
            self.closed = True
            if self.timer:
                self.timer.cancel()
            if self.process and self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGKILL)
        self.pool.shutdown(wait=True)
        self.lockfile.close()

    def remember_uploader(self, owner, name):
        with self.lock:
            if self.uploaders.get(owner) == name:
                return
            updated = {**self.uploaders, owner: name}
            write_json(self.root / 'uploaders.json', updated)
            self.uploaders = updated

    def directory(self, set_id):
        if len(set_id) != 32 or any(c not in '0123456789abcdef' for c in set_id):
            raise HTTPException(404, 'Performance not found')
        return self.root / set_id

    def get(self, set_id):
        with self.lock:
            directory = self.directory(set_id)
            if not (directory / 'set.json').exists():
                raise HTTPException(404, 'Performance not found')
            data = json.loads((directory / 'set.json').read_text())
            if not self.remote and data['status'] == 'processing' and (directory / 'progress.json').exists():
                data.update(snapshot(directory))
            if data['status'] == 'importing':
                progress = directory / 'youtube' / 'progress.json'
                if progress.exists():
                    data['youtube_import'].update(json.loads(progress.read_text()))
            return data

    def save(self, data):
        write_json(self.directory(data['id']) / 'set.json', data)
        return deepcopy(data)

    def list(self):
        with self.lock:
            return [self.get(p.parent.name) for p in sorted(self.root.glob('*/set.json'), key=lambda p: p.stat().st_mtime, reverse=True)]

    def create(self, name, owner=None, *, event=None):
        with self.lock:
            if len(self.list()) >= 20:
                raise HTTPException(409, 'Local limit: 20 performances. Delete an old performance first.')
            data = {'id': uuid4().hex, 'schema_version': 2, 'visibility': 'shared', 'dirty': False, 'name': name, 'owner': owner, 'status': 'idle', 'clips': [], 'timeline': None, 'playable': False, 'error': None}
            data.update(event or {})
            data['slug'] = set_slug(name, {item.get('slug') for item in self.list()})
            self.directory(data['id']).mkdir(mode=0o700)
            return self.save(data)

    def editable(self, set_id, batch_id=None):
        data = self.get(set_id)
        batch = self.batches.get(set_id)
        if data['status'] in ('processing', 'importing') or (data['status'] == 'uploading' and (not batch or batch['id'] != batch_id)):
            raise HTTPException(409, 'Wait for the current operation to finish.')
        return data

    def import_youtube(self, set_id, url, owner=None):
        try:
            url = canonical_url(url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with self.lock:
            data = self.get(set_id)
            if any(clip.get('source_url') == url for clip in data['clips']):
                return data
            if self.remote:
                self.remote.admit(self.limits.file_bytes)
                data['youtube_import'] = {'url': url, 'owner': owner, 'state': 'queued', 'error': None}
                self.remote.enqueue(data, 'youtube', url=url, owner=owner)
                return self.get(set_id)
            current = data.get('youtube_import', {})
            if data['status'] == 'importing' and current.get('url') == url and current.get('owner') == owner:
                return data
            self.editable(set_id)
            if self.active or self.upload or self.batches:
                raise HTTPException(409, 'Wait for the current upload or processing job before importing from YouTube.')
            if current:
                if not self.cleanup_import(data):
                    raise HTTPException(503, 'Previous import cleanup is waiting for media storage. Retry shortly.')
            self.originals.admit(self.limits, incoming=self.limits.file_bytes, work_needed=3 * self.limits.file_bytes + 1024 ** 2, reclaim=self.reclaim_deleted)
            session = self.prepare_session(set_id, 'YouTube video.mp4', self.limits.file_bytes,
                                           hashlib.sha256(uuid4().bytes).hexdigest(), owner)
            job = {'url': url, 'owner': owner, 'session_id': session['id'], 'state': 'downloading', 'stage': 'Checking YouTube video…', 'error': None}
            directory = self.directory(set_id) / 'youtube'
            directory.mkdir(mode=0o700)
            self.pending.pop(set_id, None)
            data = self.get(set_id)
            data.update(status='importing', youtube_import=job)
            self.save(data)
            self.active = set_id
            self.upload = (set_id, session['id'])
            self.pool.submit(self.run_import, set_id)
            return data

    def cleanup_import(self, data):
        job = data['youtube_import']
        manifest = self.originals.session_directory(data['id']) / f'{job["session_id"]}.json'
        if manifest.exists():
            session = json.loads(manifest.read_text())
            if session['state'] != 'complete':
                try:
                    self.remove_unpublished(session)
                except (OSError, ValueError, httpx.HTTPError):
                    # Keep the reservation and bytes until remote cleanup is acknowledged.
                    session['expires_at'] = 0
                    self.save_session(session)
                    return False
                for suffix in ('.part', '.part.transfer.json', '.json'):
                    manifest.with_name(job['session_id'] + suffix).unlink(missing_ok=True)
        shutil.rmtree(self.directory(data['id']) / 'youtube', ignore_errors=True)
        return True

    def run_import(self, set_id):
        directory = self.directory(set_id) / 'youtube'
        job = self.get(set_id)['youtube_import']
        error = None
        try:
            with self.lock:
                if self.closed:
                    raise ValueError('YouTube import interrupted. Paste the link again to retry.')
                self.process = subprocess.Popen(
                    [sys.executable, '-m', 'crowdset.youtube', str(directory), job['url'], str(self.limits.file_bytes), str(self.limits.recording_seconds), str(self.limits.media_seconds)],
                    cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True, pass_fds=(self.lockfile.fileno(),),
                    env={'PATH': os.environ.get('PATH', ''), 'HOME': str(directory), 'LANG': 'C.UTF-8', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
            deadline = time.monotonic() + self.limits.media_seconds
            while self.process.poll() is None:
                size = 0
                for path in directory.rglob('*'):
                    try:
                        if path.is_file():
                            size += path.stat().st_size
                    except FileNotFoundError:
                        pass
                if size > 2 * self.limits.file_bytes + 1024 ** 2 or time.monotonic() > deadline:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait()
                    raise ValueError('YouTube import exceeded its download time or storage limit. Try a smaller video or upload the file.')
                time.sleep(0.2)
            if self.process.returncode:
                failure = directory / 'failure.json'
                raise ValueError(json.loads(failure.read_text())['error'] if failure.exists() else 'YouTube import stopped. Try a smaller video or upload the file.')
            result = json.loads((directory / 'result.json').read_text())
            source = directory / 'source.mp4'
            size = source.stat().st_size
            if not 0 < size <= self.limits.file_bytes:
                raise ValueError('The YouTube video exceeds the recording size limit.')
            with self.lock:
                session = self.session(set_id, job['session_id'], job['owner'])
                session.update(size=size, offset=size)
                session['clip'].update(bytes=size, name=result['name'], source_url=job['url'])
                source.replace(self.originals.session_directory(set_id) / f'{session["id"]}.part')
                self.save_session(session)
                data = self.get(set_id)
                data['youtube_import'].update(stage='Saving YouTube recording…')
                self.save(data)
                (directory / 'progress.json').unlink(missing_ok=True)
            self.complete_session(set_id, session['id'], job['owner'], importing=True)
        except Exception as exc:
            error = exc.detail if isinstance(exc, HTTPException) else str(exc)
        finally:
            if self.process and self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
            with self.lock:
                try:
                    data = self.get(set_id)
                    data['youtube_import'].update(state='failed' if error else 'complete', error=error)
                    data.update(status='ready' if data.get('playable') else 'idle')
                    self.save(data)
                    self.cleanup_import(data)
                    if not error:
                        self.queue(data)
                finally:
                    if self.upload == (set_id, job['session_id']):
                        self.upload = None
                    self.active = self.process = None
                    self.schedule()

    def invalidate(self, data):
        data.update(status='idle', error=None, dirty=True)
        data.pop('stage', None)
        data.pop('processing', None)
        data.pop('processing_started_at', None)

    def queue(self, data):
        self.pending.pop(data['id'], None)
        if data['id'] in self.batches:
            data['status'] = 'uploading'
            return self.save(data)
        if any(c['role'] != 'reference' and c['included'] for c in data['clips']):
            if self.remote:
                self.remote.enqueue(data)
                return self.get(data['id'])
            data['status'] = 'queued'
            self.pending[data['id']] = time.monotonic() + 3
            self.schedule()
        return self.save(data)

    def schedule(self):
        if self.closed or self.timer or not (self.pending or self.batches):
            return
        self.timer = threading.Timer(1, self.dispatch)
        self.timer.daemon = True
        self.timer.start()

    def dispatch(self):
        with self.lock:
            self.timer = None
            if self.closed:
                return
            for set_id, batch in list(self.batches.items()):
                if batch['deadline'] <= time.monotonic() and (not self.upload or self.upload[0] != set_id):
                    data = self.get(set_id)
                    data['upload_notice'] = 'Upload batch interrupted. Added recordings will be mixed; upload missing files again.'
                    self.save(data)
                    self.finish_batch(set_id, batch['id'], batch['owner'])
            if not self.active and not self.upload:
                ready = next((key for key, due in self.pending.items() if due <= time.monotonic()), None)
                if ready:
                    self.start(ready)
            self.schedule()

    def begin_batch(self, set_id, owner=None):
        with self.lock:
            if set_id in self.batches:
                batch = self.batches[set_id]
                if batch['owner'] != owner:
                    raise HTTPException(409, 'Another uploader is adding recordings. Try again shortly.')
                return {'id': batch['id']}
            data = self.editable(set_id)
            batch = {'id': uuid4().hex, 'owner': owner, 'deadline': time.monotonic() + 60, 'expires_at': time.time() + 60}
            self.batches[set_id] = batch
            self.pending.pop(set_id, None)
            data.update(status='uploading', upload_notice=None, batch={key: value for key, value in batch.items() if key != 'deadline'})
            self.save(data)
            self.schedule()
            return {'id': batch['id']}

    def finish_batch(self, set_id, batch_id, owner=None):
        with self.lock:
            batch = self.batches.get(set_id)
            data = self.get(set_id)
            if data.get('completed_batch') == {'id': batch_id, 'owner': owner}:
                return data
            if not batch or batch['id'] != batch_id:
                raise HTTPException(409, 'Upload batch expired. Added recordings are retained; retry missing files.')
            if batch['owner'] != owner:
                raise HTTPException(403, 'Only the uploader can finish this batch.')
            if self.upload and self.upload[0] == set_id:
                raise HTTPException(409, 'Wait for the current upload to finish.')
            self.batches.pop(set_id)
            data = self.get(set_id)
            data.pop('batch', None)
            data['completed_batch'] = {'id': batch_id, 'owner': owner}
            data['status'] = 'ready' if data['playable'] else 'idle'
            return self.queue(data) if data.get('dirty') else self.save(data)

    def expire_sessions(self):
        now = time.time()
        for session in self.originals.sessions():
            # An archived set may retain sessions and originals outside the live catalog.
            # Without its metadata we cannot safely identify unpublished media.
            if not (self.directory(session['set_id']) / 'set.json').exists():
                continue
            folder = self.originals.session_directory(session['set_id'])
            if self.remote and session.get('direct') and session['state'] == 'validating':
                continue
            if session['expires_at'] <= now:
                if self.upload == (session['set_id'], session['id']):
                    continue
                try:
                    self.remove_unpublished(session)
                except (OSError, ValueError, httpx.HTTPError):
                    continue
                (folder / f'{session["id"]}.part').unlink(missing_ok=True)
                (folder / f'{session["id"]}.part.transfer.json').unlink(missing_ok=True)
                (folder / f'{session["id"]}.json').unlink(missing_ok=True)
            elif session['state'] == 'uploading':
                partial = folder / f'{session["id"]}.part'
                if partial.exists() and partial.stat().st_size > session['offset']:
                    with partial.open('r+b') as output:
                        output.truncate(session['offset'])

    def save_session(self, session):
        write_json(self.originals.session_directory(session['set_id']) / f'{session["id"]}.json', session)

    def session(self, set_id, upload_id, owner=None):
        self.directory(set_id)
        if len(upload_id) != 32 or any(c not in '0123456789abcdef' for c in upload_id):
            raise HTTPException(404, 'Upload not found.')
        path = self.originals.session_directory(set_id) / f'{upload_id}.json'
        if not path.exists():
            raise HTTPException(404, 'Upload expired. Reselect the file to start again.')
        session = json.loads(path.read_text())
        if session['owner'] != owner:
            raise HTTPException(403, 'Only the original uploader can resume this file.')
        if session['expires_at'] <= time.time() and not (self.remote and session.get('direct') and session['state'] == 'validating'):
            raise HTTPException(410, 'Upload expired. Reselect the file to start again.')
        return session

    def prepare_session(self, set_id, name, size, fingerprint, owner=None, batch_id=None):
        with self.lock:
            self.expire_sessions()
            data = self.editable(set_id, batch_id)
            batch = self.batches.get(set_id)
            if batch and (batch['id'] != batch_id or batch['owner'] != owner):
                raise HTTPException(409, 'Another upload batch is active. Wait for it to finish.')
            if batch_id and not batch:
                raise HTTPException(409, 'Upload batch expired. Reselect the remaining files.')
            if self.upload:
                raise HTTPException(409, 'Another upload is being saved. Retry shortly.')
            if not 1 <= size <= self.limits.file_bytes:
                raise HTTPException(413, f'Each file must be nonempty and at most {self.limits.file_bytes // 1024 ** 2} MiB.')
            suffix = Path(name).suffix.lower()
            if suffix not in EXTENSIONS:
                raise HTTPException(415, 'Use a supported audio or video file.')
            deleted_ids = {c['id'] for c in data.get('deleted_clips', [])}
            for existing in self.originals.sessions():
                if existing['set_id'] == set_id and existing['owner'] == owner and existing['fingerprint'] == fingerprint and existing['size'] == size:
                    if existing['clip']['id'] in deleted_ids:
                        continue
                    if existing['state'] == 'complete' and not any(c['id'] == existing['clip']['id'] for c in data['clips']):
                        continue
                    existing['batch_id'] = batch_id
                    existing['expires_at'] = time.time() + self.limits.upload_seconds
                    self.save_session(existing)
                    return self.public_session(existing)
            pending = [s for s in self.originals.sessions() if s['set_id'] == set_id and s['state'] == 'uploading' and s['clip']['id'] not in deleted_ids]
            if sum(c['role'] != 'reference' for c in data['clips']) + len(pending) >= self.limits.recordings:
                raise HTTPException(409, f'This set accepts at most {self.limits.recordings} recordings.')
            if self.remote:
                self.remote.admit(size)
            else:
                self.originals.admit(self.limits, incoming=size, reclaim=self.reclaim_deleted)
            clip = {'id': uuid4().hex, 'name': Path(name).name[:180], 'role': 'recording', 'included': True,
                    'uploader': owner, 'kind': 'video' if suffix in ('.mp4', '.mov', '.webm') else 'audio', 'bytes': size}
            clip['file'] = f'{clip["id"]}{suffix}.upload'
            session = {'id': uuid4().hex, 'set_id': set_id, 'owner': owner, 'fingerprint': fingerprint, 'size': size,
                       'offset': 0, 'state': 'uploading', 'clip': clip, 'batch_id': batch_id,
                       'expires_at': time.time() + self.limits.upload_seconds}
            self.save_session(session)
            return self.public_session(session)

    @staticmethod
    def public_session(session):
        return {key: session[key] for key in ('id', 'size', 'offset', 'state', 'expires_at')}

    def append_session(self, set_id, upload_id, owner, offset, chunk, checksum):
        with self.lock:
            session = self.session(set_id, upload_id, owner)
            self.editable(set_id, session['batch_id'])
            if (self.upload and self.upload != (set_id, upload_id)) or session['state'] != 'uploading':
                raise HTTPException(409, 'The recording is already being saved. Retry shortly.')
            if not chunk or len(chunk) > self.limits.chunk_bytes or offset + len(chunk) > session['size']:
                raise HTTPException(413, 'Upload chunk exceeds its reserved size.')
            if not hmac.compare_digest(hashlib.sha256(chunk).hexdigest(), checksum):
                raise HTTPException(422, 'Upload chunk failed its checksum. Retry this chunk.')
            partial = self.originals.session_directory(set_id) / f'{upload_id}.part'
            if offset < session['offset'] and offset + len(chunk) <= session['offset'] and partial.exists():
                with partial.open('rb') as source:
                    source.seek(offset)
                    if source.read(len(chunk)) == chunk:
                        return self.public_session(session)
            if offset != session['offset']:
                raise HTTPException(409, 'Upload offset changed. Read the saved offset and resume.')
            self.originals.admit(self.limits, reclaim=self.reclaim_deleted)
            with partial.open('r+b' if partial.exists() else 'w+b') as output:
                output.seek(offset)
                output.truncate(offset)
                output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            session['offset'] += len(chunk)
            self.save_session(session)
            batch = self.batches.get(set_id)
            if batch:
                batch.update(deadline=time.monotonic() + 60, expires_at=time.time() + 60)
                data = self.get(set_id)
                data['batch'] = {key: value for key, value in batch.items() if key != 'deadline'}
                self.save(data)
            return self.public_session(session)

    def begin_chunk(self, set_id, upload_id, owner=None):
        with self.lock:
            session = self.session(set_id, upload_id, owner)
            self.editable(set_id, session['batch_id'])
            if self.upload or session['state'] != 'uploading':
                raise HTTPException(409, 'Another upload is active. Retry shortly.')
            self.upload = (set_id, upload_id)

    def end_chunk(self, set_id, upload_id):
        with self.lock:
            if self.upload == (set_id, upload_id):
                self.upload = None
            batch = self.batches.get(set_id)
            if batch:
                batch.update(deadline=time.monotonic() + 60, expires_at=time.time() + 60)
                data = self.get(set_id)
                data['batch'] = {key: value for key, value in batch.items() if key != 'deadline'}
                self.save(data)

    def cancel_session(self, set_id, upload_id, owner=None):
        with self.lock:
            session = self.session(set_id, upload_id, owner)
            if self.upload:
                raise HTTPException(409, 'Wait for the recording being saved.')
            if session['state'] == 'complete':
                raise HTTPException(409, 'The recording is already saved. Remove it from the set instead.')
            try:
                self.remove_unpublished(session)
            except (ValueError, httpx.HTTPError) as exc:
                raise HTTPException(503, 'Media cleanup was interrupted. Retry cancellation shortly.') from exc
            directory = self.originals.session_directory(set_id)
            for suffix in ('.part', '.part.transfer.json', '.json'):
                (directory / f'{upload_id}{suffix}').unlink(missing_ok=True)

    def remove_unpublished(self, session):
        set_id, clip = session['set_id'], session['clip']
        data = self.get(set_id)
        if any(item['id'] == clip['id'] for item in data['clips'] + data.get('deleted_clips', [])):
            return
        if self.blobs:
            prefix = f'originals/{set_id}/{clip["id"]}/'
            keys = [json.loads(path.read_text())['key'] for path in (self.root / 'objects').glob('*.json')]
            self.originals.remove_blobs([key for key in keys if key.startswith(prefix)])
        self.originals.path(set_id, clip).unlink(missing_ok=True)
        (self.directory(set_id) / f'{clip["id"]}.jpg').unlink(missing_ok=True)

    def complete_session(self, set_id, upload_id, owner=None, *, importing=False):
        with self.lock:
            session = self.session(set_id, upload_id, owner)
            data = self.get(set_id)
            if session['state'] == 'complete' or any(c['id'] == session['clip']['id'] for c in data['clips'] + data.get('deleted_clips', [])):
                session['state'] = 'complete'
                self.save_session(session)
                return {**data, **({'duplicate_clip_id': session['duplicate_clip_id']} if session.get('duplicate_clip_id') else {})}
            if self.upload and not (importing and self.upload == (set_id, upload_id)):
                raise HTTPException(409, 'A recording is being saved. Retry shortly.')
            if not importing:
                self.editable(set_id, session['batch_id'])
            if session['offset'] != session['size']:
                raise HTTPException(409, 'Upload is incomplete. Resume from the saved offset.')
            self.upload = (set_id, upload_id)
            clip = session['clip']
            partial = self.originals.session_directory(set_id) / f'{upload_id}.part'
        try:
            source = partial if partial.exists() else self.originals.path(set_id, clip)
            checksum = digest(source)
            with self.lock:
                duplicate = next((c for c in self.get(set_id)['clips'] if c.get('sha256') == checksum and c['role'] != 'reference'), None)
                if duplicate:
                    self.remove_unpublished(session)
                    session.update(state='complete', clip=duplicate, duplicate_clip_id=duplicate['id'])
                    self.save_session(session)
                    partial.unlink(missing_ok=True)
                    return {**self.get(set_id), 'duplicate_clip_id': duplicate['id']}
            duration = probe(source, limits=self.limits)
            with self.lock:
                data = self.get(set_id)
                total = sum(c.get('expected_duration', c.get('duration', 0)) for c in data['clips'] if c['role'] != 'reference' and c['id'] != clip['id'])
                if total + duration > self.limits.set_seconds:
                    raise HTTPException(413, f'A set can contain at most {self.limits.set_seconds // 3600} hours of recordings in total.')
            clip['expected_duration'] = duration
            self.originals.publish(set_id, clip, partial)
            with self.lock:
                data = self.get(set_id)
                if not any(c['id'] == clip['id'] for c in data['clips']):
                    data['clips'].append(clip)
                data['recovery_attempts'] = 0
                self.invalidate(data)
                if importing:
                    data['status'] = 'importing'
                    result = self.save(data)
                else:
                    result = self.queue(data)
                session.update(state='complete', clip=clip)
                self.save_session(session)
                partial.unlink(missing_ok=True)
                return result
        except BlobError as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(503, 'Media storage is temporarily unavailable. Reselect the file to resume saving it.') from exc
        finally:
            with self.lock:
                if not importing:
                    self.upload = None

    def begin_upload(self, set_id, name, role='recording', uploader=None, batch_id=None):
        with self.lock:
            if self.blobs:
                raise HTTPException(409, 'Reload Crowdset to use resumable uploads with media storage.')
            batch = self.batches.get(set_id)
            if batch_id and (not batch or batch['id'] != batch_id):
                raise HTTPException(409, 'Upload batch expired. Retry the remaining files.')
            if batch and (batch['id'] != batch_id or batch['owner'] != uploader):
                raise HTTPException(409, 'Another upload batch is active. Wait for it to finish.')
            data = self.editable(set_id, batch_id)
            if self.upload:
                raise HTTPException(409, 'Another upload is active. Try again when it finishes.')
            suffix = Path(name).suffix.lower()
            if suffix not in EXTENSIONS:
                raise HTTPException(415, 'Supported files: WAV, MP3, M4A, MP4, MOV, AAC, FLAC, OGG, WEBM.')
            if role == 'reference' and any(c['role'] == role for c in data['clips']):
                raise HTTPException(409, 'Remove the existing reference before replacing it.')
            pending = sum(s['set_id'] == set_id and s['state'] == 'uploading' for s in self.originals.sessions())
            if role != 'reference' and sum(c['role'] != 'reference' for c in data['clips']) + pending >= self.limits.recordings:
                raise HTTPException(409, f'This set has {self.limits.recordings} recordings. Remove one before adding another.')
            self.expire_sessions()
            self.originals.admit(self.limits, incoming=self.limits.file_bytes, reclaim=self.reclaim_deleted)
            clip = {'id': uuid4().hex, 'name': Path(name).name[:180], 'role': role, 'included': True, 'uploader': uploader,
                    'kind': 'video' if suffix in ('.mp4', '.mov', '.webm') else 'audio'}
            clip['file'] = f'{clip["id"]}{suffix}.upload'
            self.pending.pop(set_id, None)
            self.upload = (set_id, clip['id'])
            data = self.get(set_id)
            data.update(status='uploading', upload_notice=None)
            self.save(data)
            return clip, self.directory(set_id) / (clip['id'] + '.part')

    def finish_upload(self, set_id, clip, partial, success):
        with self.lock:
            self.upload = None
            if set_id in self.batches:
                self.batches[set_id]['deadline'] = time.monotonic() + 60
                self.batches[set_id]['expires_at'] = time.time() + 60
            data = self.get(set_id)
            if set_id in self.batches:
                data['batch'] = {key: value for key, value in self.batches[set_id].items() if key != 'deadline'}
            checksum = digest(partial) if success else None
            duplicate = next((c for c in data['clips'] if checksum and c.get('sha256') == checksum and (c['role'] == 'reference') == (clip['role'] == 'reference')), None)
            if duplicate:
                partial.unlink(missing_ok=True)
                data['status'] = 'ready' if data['timeline'] else 'idle'
                result = self.queue(data) if data.get('dirty') or set_id in self.batches else self.save(data)
                return {**result, 'duplicate_clip_id': duplicate['id']}
            if success:
                data['recovery_attempts'] = 0
                self.invalidate(data)
                self.originals.publish(set_id, clip, partial)
                data['clips'].append(clip)
            else:
                partial.unlink(missing_ok=True)
                data['status'] = 'ready' if data['timeline'] else 'idle'
            return self.queue(data) if data.get('dirty') or set_id in self.batches else self.save(data)

    def select_soundtrack(self, set_id, clip_id, owner):
        with self.lock:
            data = self.editable(set_id)
            if data.get('owner') != owner:
                raise HTTPException(403, 'Only the set owner can choose the full set audio.')
            if clip_id is not None:
                clip = next((c for c in data['clips'] if c['id'] == clip_id), None)
                if not clip or clip['role'] == 'reference' or not clip['included']:
                    raise HTTPException(400, 'Choose an included recording as the full set.')
            if data.get('soundtrack_clip_id') == clip_id:
                return data
            data['soundtrack_clip_id'] = clip_id
            data['recovery_attempts'] = 0
            self.invalidate(data)
            return self.queue(data)

    def edit_clip(self, set_id, clip_id, included=None, delete=False):
        with self.lock:
            data = self.editable(set_id)
            clip = next((c for c in data['clips'] if c['id'] == clip_id), None)
            if not clip:
                raise HTTPException(404, 'Clip not found')
            if clip['role'] == 'reference' and not delete:
                raise HTTPException(400, 'The reference is timing-only and cannot be included in the mix.')
            data['recovery_attempts'] = 0
            self.invalidate(data)
            if delete:
                clip['deleted_at'] = time.time()
                data.setdefault('deleted_clips', []).append(clip)
                data['clips'].remove(clip)
                if data.get('soundtrack_clip_id') == clip_id:
                    data['soundtrack_clip_id'] = None
                if not any(c['role'] != 'reference' and c['included'] for c in data['clips']):
                    data.update(playable=False, video_playable=False, timeline=None, video_timeline=None,
                                composition=None, scrub_previews={}, previous_revision={})
            else:
                clip['included'] = included
            return self.queue(data)

    def reclaim_deleted(self, needed):
        with self.lock:
            candidates = sorted((clip['deleted_at'], data['id'], clip['id'])
                                for data in self.list() for clip in data.get('deleted_clips', [])
                                if not clip.get('purged_at'))
            before, _ = self.originals.usage()
            for _, set_id, clip_id in candidates:
                data = self.get(set_id)
                clip = next(c for c in data['deleted_clips'] if c['id'] == clip_id)
                try:
                    self.originals.remove(set_id, clip)
                    directory = self.directory(set_id)
                    for suffix in ('.wav', '.npy', '.analysis.json', '.alignment.json', '.original', '.original.download'):
                        (directory / (clip_id + suffix)).unlink(missing_ok=True)
                    clip['purged_at'] = time.time()
                    self.save(data)
                except (OSError, ValueError, httpx.HTTPError) as exc:
                    raise HTTPException(503, 'Could not reclaim removed recordings. Retry shortly; their storage remains reserved until cleanup succeeds.') from exc
                remaining, _ = self.originals.usage()
                if before - remaining >= needed:
                    break

    def delete(self, set_id):
        with self.lock:
            data = self.editable(set_id)
            for clip in data['clips'] + data.get('deleted_clips', []):
                if clip.get('purged_at'):
                    continue
                self.originals.remove(set_id, clip)
            if self.blobs:
                keys = [json.loads(path.read_text())['key'] for path in (self.root / 'objects').glob('*.json')
                        if f'/{set_id}/' in json.loads(path.read_text())['key']]
                self.originals.remove_blobs(keys)
            self.pending.pop(set_id, None)
            shutil.rmtree(self.directory(set_id))
            shutil.rmtree(self.originals.uploads / set_id, ignore_errors=True)
            shutil.rmtree(self.originals.originals / set_id, ignore_errors=True)

    def start(self, set_id):
        with self.lock:
            self.expire_sessions()
            data = self.editable(set_id)
            if not any(c['role'] != 'reference' and c['included'] for c in data['clips']):
                raise HTTPException(400, 'Add a recording to update the mix.')
            if self.remote:
                self.remote.enqueue(data)
                return self.get(set_id)
            if self.active or self.upload:
                return self.queue(data)
            if data['status'] != 'queued':
                data['recovery_attempts'] = 0
            self.pending.pop(set_id, None)
            self.invalidate(data)
            directory = self.directory(set_id)
            for temporary in directory.glob('video-*'):
                if temporary.is_dir():
                    shutil.rmtree(temporary)
            for temporary in directory.glob('*.original*'):
                temporary.unlink(missing_ok=True)
            published = {data.get('mix_file', 'reconstruction.wav'), data.get('video_file'),
                         data.get('previous_revision', {}).get('mix_file'), data.get('previous_revision', {}).get('video_file')}
            for pattern in ('mix-*.wav', 'mix-*.mp4', 'reconstruction.wav', 'pending.wav', 'pending.mp4', 'reference.wav', 'result.json', 'failure.json', 'progress.json'):
                for path in directory.glob(pattern):
                    if path.name not in published:
                        path.unlink(missing_ok=True)
            data.update(status='processing', stage='Starting processing…', processing_started_at=time.time())
            self.save(data)
            write_json(self.directory(set_id) / 'job.json', data)
            self.active = set_id
            self.pool.submit(self.run, set_id)
            return data

    def run(self, set_id):
        directory = self.directory(set_id)
        error = None
        try:
            self.collect_mixes(set_id)
            with self.lock:
                if self.closed:
                    raise RuntimeError('Server stopped. Retry processing.')
                self.process = subprocess.Popen([sys.executable, '-m', 'crowdset.worker', str(directory)], cwd=Path(__file__).resolve().parents[1],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=(self.lockfile.fileno(),),
                                                env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
            try:
                code = self.process.wait(timeout=self.limits.job_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
                raise RuntimeError('Processing exceeded its time limit. Completed preparation is cached; retry the mix.')
            if code:
                failure = directory / 'failure.json'
                raise RuntimeError(json.loads(failure.read_text())['error'] if failure.exists() else 'Processing stopped unexpectedly. Retry with shorter recordings.')
            result = json.loads((directory / 'result.json').read_text())
            write_json(directory / 'progress.json', {'stage': 'Saving the finished cut…',
                       'processing': {'phase': 'save', 'started_at': self.get(set_id).get('processing_started_at'),
                                      'updated_at': time.time()}})
            if not result['playable']:
                raise ValueError('No mix was created. Add another recording and retry.')
            reused = result.pop('reuse_revision', None)
            if reused:
                current = self.get(set_id)
                if reused != current.get('mix_revision') or not current.get('playable'):
                    raise ValueError('The published cut changed during processing. Retry the mix.')
                (directory / 'pending.wav').unlink(missing_ok=True)
            else:
                revision = uuid4().hex
                current = self.get(set_id)
                base_reused = result.pop('reuse_base_revision', None)
                artifacts = {}
                if base_reused:
                    if base_reused != current.get('mix_revision') or not current.get('video_playable'):
                        raise ValueError('The published full set changed during processing. Retry the mix.')
                    (directory / 'pending.wav').unlink(missing_ok=True)
                    publication = {key: current.get(key) for key in ('mix_file', 'mix_object', 'mix_bytes',
                                   'video_file', 'video_object', 'video_bytes')}
                else:
                    filename = f'mix-{revision}.wav'
                    (directory / 'pending.wav').replace(directory / filename)
                    artifacts['mix'] = (filename, 'audio/wav')
                    if result.get('video_playable'):
                        video_filename = f'mix-{revision}.mp4'
                        (directory / 'pending.mp4').replace(directory / video_filename)
                        artifacts['video'] = (video_filename, 'video/mp4')
                    publication = {'mix_object': None, 'mix_bytes': 0, 'video_file': None, 'video_object': None, 'video_bytes': 0}
                assets = (result.get('composition') or {}).get('assets', {})
                new_assets = {key: asset for key, asset in assets.items() if not asset.get('object')}
                if self.blobs:
                    with self.lock:
                        incoming = sum((directory / name).stat().st_size for name, _ in artifacts.values())
                        incoming += sum((directory / asset['file']).stat().st_size for asset in new_assets.values())
                        self.originals.admit(self.limits, incoming=incoming, reclaim=self.reclaim_deleted)
                        for kind, (name, _) in artifacts.items():
                            key = f'mixes/{set_id}/{revision}{Path(name).suffix}'
                            size = (directory / name).stat().st_size
                            self.originals.record_blob(key, size)
                            publication.update({f'{kind}_object': key, f'{kind}_bytes': size})
                        for asset in new_assets.values():
                            asset['object'] = f"mixes/{set_id}/{asset['file']}"
                            self.originals.record_blob(asset['object'], asset['bytes'])
                    for kind, (name, mime) in artifacts.items():
                        self.blobs.put(directory / name, publication[f'{kind}_object'], mime)
                    for asset in new_assets.values():
                        self.blobs.put(directory / asset['file'], asset['object'], 'video/mp4')
                publication.update({f'{kind}_file': name for kind, (name, _) in artifacts.items()})
        except Exception as exc:
            error = exc.detail if isinstance(exc, HTTPException) else str(exc)
        with self.lock:
            data = self.get(set_id)
            try:
                if error:
                    data.update(status='failed', error=error, dirty=True)
                else:
                    if reused:
                        data.update(result, status='ready', error=None, dirty=False, recovery_attempts=0)
                    else:
                        previous = {key: data.get(key) for key in ('mix_revision', 'mix_file', 'mix_object', 'mix_bytes',
                                    'video_file', 'video_object', 'video_bytes', 'video_playable', 'playable', 'composition', 'scrub_previews')}
                        previous['mix_file'] = data.get('mix_file') or 'reconstruction.wav'
                        data.update(previous_revision=previous, previous_mix_object=data.get('mix_object'), previous_mix_bytes=data.get('mix_bytes', 0))
                        data.update(result, **publication, status='ready', error=None, dirty=False, mix_revision=revision, recovery_attempts=0)
                data.pop('stage', None)
                data.pop('processing', None)
                data.pop('processing_started_at', None)
                self.save(data)
            except (OSError, ValueError, httpx.HTTPError):
                previous = self.get(set_id)
                previous.update(status='failed', dirty=True, error='Could not save the updated mix. Check storage and retry.')
                previous.pop('stage', None)
                previous.pop('processing', None)
                previous.pop('processing_started_at', None)
                self.save(previous)
        try:
            self.collect_mixes(set_id)
        finally:
            with self.lock:
                self.active = None
                self.process = None
                self.schedule()

    def collect_mixes(self, set_id):
        data = self.get(set_id)
        if self.remote:
            return
        previous = data.get('previous_revision', {})
        retained_files = {data.get('mix_file', 'reconstruction.wav'), data.get('video_file'), previous.get('mix_file'), previous.get('video_file')}
        assets = [asset for revision in (data, previous)
                  for asset in (revision.get('composition') or {}).get('assets', {}).values()]
        retained_files.update(asset['file'] for asset in assets)
        for revision in (data, previous):
            for preview in (revision.get('scrub_previews') or {}).values():
                retained_files.update(preview['sheets'])
                retained_files.update(name.rsplit('-', 1)[0] + '.json' for name in preview['sheets'])
        if self.blobs:
            retained = {data.get('mix_object'), data.get('previous_mix_object'), data.get('video_object'), previous.get('video_object')}
            retained.update(asset.get('object') for asset in assets)
            for asset in assets:
                if asset.get('object'):
                    (self.directory(set_id) / asset['file']).unlink(missing_ok=True)
            for revision in (data, previous):
                if revision.get('video_playable') and revision.get('video_object') and revision.get('video_file'):
                    # Published cloud video is streamed remotely; retain audio for rebuild comparison.
                    (self.directory(set_id) / revision['video_file']).unlink(missing_ok=True)
            keys = [json.loads(path.read_text())['key'] for path in (self.root / 'objects').glob('*.json')]
            obsolete = [key for key in keys if key.startswith(f'mixes/{set_id}/') and key not in retained]
            try:
                if obsolete:
                    self.originals.remove_blobs(obsolete)
            except (OSError, ValueError, httpx.HTTPError):
                # Retain reservations until remote deletion is acknowledged.
                return
        for pattern in ('mix-*.wav', 'mix-*.mp4', 'mix-*.transfer.json', 'overlay-*.mp4', 'overlay-*.transfer.json', 'overlay-*.progress', 'scrub-*.jpg', 'scrub-*.json'):
            for path in self.directory(set_id).glob(pattern):
                if path.name.removesuffix('.transfer.json') not in retained_files:
                    path.unlink(missing_ok=True)
