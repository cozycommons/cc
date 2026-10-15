from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

from fastapi import HTTPException

from .worker import write_json

ROOT = Path(__file__).resolve().parents[2] / '.crowd-set'
EXTENSIONS = {'.wav', '.mp3', '.m4a', '.mp4', '.mov', '.aac', '.flac', '.ogg', '.webm'}
MAX_BYTES = 512 * 1024 * 1024
DISK_BUDGET = 8 * 1024 ** 3


class Store:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lockfile = (self.root / '.lock').open('a')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lockfile.close()
            raise RuntimeError('Crowd Set storage is already open. Stop the other API or wait for its worker (up to 15 minutes), then retry.')
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.active = None
        self.upload = None
        self.process = None
        self.closed = False
        self.pending = {}
        self.batches = {}
        self.timer = None
        for path in self.root.glob('*/set.json'):
            data = json.loads(path.read_text())
            if data['status'] in ('processing', 'uploading', 'queued'):
                data.update(status='failed', error='Update interrupted. Retry to update the mix.', dirty=True)
                write_json(path, data)
            for partial in path.parent.glob('*.part'):
                partial.unlink()

    def close(self):
        with self.lock:
            self.closed = True
            if self.timer:
                self.timer.cancel()
            if self.process and self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGKILL)
        self.pool.shutdown(wait=True)
        self.lockfile.close()

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
            if data['status'] == 'processing' and (directory / 'progress.json').exists():
                data.update(json.loads((directory / 'progress.json').read_text()))
            return data

    def save(self, data):
        write_json(self.directory(data['id']) / 'set.json', data)
        return deepcopy(data)

    def list(self):
        with self.lock:
            return [self.get(p.parent.name) for p in sorted(self.root.glob('*/set.json'), key=lambda p: p.stat().st_mtime, reverse=True)]

    def create(self, name, owner=None):
        with self.lock:
            if len(self.list()) >= 20:
                raise HTTPException(409, 'Local limit: 20 performances. Delete an old performance first.')
            data = {'id': uuid4().hex, 'schema_version': 2, 'visibility': 'shared', 'dirty': False, 'name': name, 'owner': owner, 'status': 'idle', 'clips': [], 'timeline': None, 'playable': False, 'error': None}
            self.directory(data['id']).mkdir(mode=0o700)
            return self.save(data)

    def editable(self, set_id, batch_id=None):
        data = self.get(set_id)
        batch = self.batches.get(set_id)
        if data['status'] == 'processing' or (data['status'] == 'uploading' and (not batch or batch['id'] != batch_id)):
            raise HTTPException(409, 'Wait for the current operation to finish.')
        return data

    def invalidate(self, data):
        data.update(status='idle', error=None, dirty=True)
        data.pop('stage', None)

    def queue(self, data):
        self.pending.pop(data['id'], None)
        if data['id'] in self.batches:
            data['status'] = 'uploading'
            return self.save(data)
        if any(c['role'] != 'reference' and c['included'] for c in data['clips']):
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
            data = self.editable(set_id)
            batch = {'id': uuid4().hex, 'owner': owner, 'deadline': time.monotonic() + 60}
            self.batches[set_id] = batch
            self.pending.pop(set_id, None)
            data.update(status='uploading', upload_notice=None)
            self.save(data)
            self.schedule()
            return {'id': batch['id']}

    def finish_batch(self, set_id, batch_id, owner=None):
        with self.lock:
            batch = self.batches.get(set_id)
            if not batch or batch['id'] != batch_id:
                raise HTTPException(409, 'Upload batch expired. Added recordings are retained; retry missing files.')
            if batch['owner'] != owner:
                raise HTTPException(403, 'Only the uploader can finish this batch.')
            if self.upload and self.upload[0] == set_id:
                raise HTTPException(409, 'Wait for the current upload to finish.')
            self.batches.pop(set_id)
            data = self.get(set_id)
            data['status'] = 'ready' if data['playable'] else 'idle'
            return self.queue(data) if data.get('dirty') else self.save(data)

    def begin_upload(self, set_id, name, role='recording', uploader=None, batch_id=None):
        with self.lock:
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
            if role != 'reference' and sum(c['role'] != 'reference' for c in data['clips']) >= 8:
                raise HTTPException(409, 'This set has 8 recordings. Remove one before adding another.')
            used = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
            if used + MAX_BYTES + 3 * 1024 ** 3 > DISK_BUDGET or shutil.disk_usage(self.root).free < MAX_BYTES + 3 * 1024 ** 3:
                raise HTTPException(507, 'Not enough local storage. Delete an old performance to free space.')
            clip = {'id': uuid4().hex, 'name': Path(name).name[:180], 'role': role, 'included': True, 'uploader': uploader,
                    'kind': 'video' if suffix in ('.mp4', '.mov', '.webm') else 'audio'}
            clip['file'] = f'{clip["id"]}{suffix}.upload'
            self.pending.pop(set_id, None)
            self.upload = (set_id, clip['id'])
            data.update(status='uploading', upload_notice=None)
            self.save(data)
            return clip, self.directory(set_id) / (clip['id'] + '.part')

    def finish_upload(self, set_id, clip, partial, success):
        with self.lock:
            self.upload = None
            if set_id in self.batches:
                self.batches[set_id]['deadline'] = time.monotonic() + 60
            data = self.get(set_id)
            if success:
                self.invalidate(data)
                partial.replace(self.directory(set_id) / clip['file'])
                data['clips'].append(clip)
            else:
                partial.unlink(missing_ok=True)
                data['status'] = 'ready' if data['timeline'] else 'idle'
            return self.queue(data) if data.get('dirty') or set_id in self.batches else self.save(data)

    def edit_clip(self, set_id, clip_id, included=None, delete=False):
        with self.lock:
            data = self.editable(set_id)
            clip = next((c for c in data['clips'] if c['id'] == clip_id), None)
            if not clip:
                raise HTTPException(404, 'Clip not found')
            if clip['role'] == 'reference' and not delete:
                raise HTTPException(400, 'The reference is timing-only and cannot be included in the mix.')
            self.invalidate(data)
            if delete:
                directory = self.directory(set_id)
                for name in (clip['file'], clip['id'] + '.wav', clip['id'] + '.npy', clip['id'] + '.analysis.json'):
                    (directory / name).unlink(missing_ok=True)
                data['clips'].remove(clip)
            else:
                clip['included'] = included
            return self.queue(data)

    def delete(self, set_id):
        with self.lock:
            self.editable(set_id)
            self.pending.pop(set_id, None)
            shutil.rmtree(self.directory(set_id))

    def start(self, set_id):
        with self.lock:
            data = self.editable(set_id)
            if not any(c['role'] != 'reference' and c['included'] for c in data['clips']):
                raise HTTPException(400, 'Add a recording to update the mix.')
            if self.active or self.upload:
                return self.queue(data)
            self.pending.pop(set_id, None)
            self.invalidate(data)
            directory = self.directory(set_id)
            published = data.get('mix_file', 'reconstruction.wav')
            for pattern in ('mix-*.wav', 'reconstruction.wav', 'pending.wav', 'reference.wav', 'result.json', 'failure.json', 'progress.json'):
                for path in directory.glob(pattern):
                    if path.name != published:
                        path.unlink(missing_ok=True)
            data.update(status='processing', stage='Updating mix')
            self.save(data)
            write_json(self.directory(set_id) / 'job.json', data)
            self.active = set_id
            self.pool.submit(self.run, set_id)
            return data

    def run(self, set_id):
        directory = self.directory(set_id)
        error = None
        try:
            with self.lock:
                if self.closed:
                    raise RuntimeError('Server stopped. Retry processing.')
                self.process = subprocess.Popen([sys.executable, '-m', 'crowd_set.worker', str(directory)], cwd=Path(__file__).resolve().parents[1],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, pass_fds=(self.lockfile.fileno(),),
                                                env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
            try:
                code = self.process.wait(timeout=900)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
                raise RuntimeError('Processing exceeded 15 minutes. Try shorter recordings.')
            if code:
                failure = directory / 'failure.json'
                raise RuntimeError(json.loads(failure.read_text())['error'] if failure.exists() else 'Processing stopped unexpectedly. Retry with shorter recordings.')
            result = json.loads((directory / 'result.json').read_text())
        except Exception as exc:
            error = str(exc)
        with self.lock:
            data = self.get(set_id)
            try:
                if error:
                    data.update(status='failed', error=error, dirty=True)
                else:
                    if not result['playable']:
                        raise ValueError('No mix was created. Add another recording and retry.')
                    revision = uuid4().hex
                    filename = f'mix-{revision}.wav'
                    (directory / 'pending.wav').replace(directory / filename)
                    data.update(result, status='ready', error=None, dirty=False, mix_file=filename, mix_revision=revision)
                data.pop('stage', None)
                self.save(data)
            except (OSError, ValueError):
                previous = self.get(set_id)
                previous.update(status='failed', dirty=True, error='Could not save the updated mix. Check storage and retry.')
                previous.pop('stage', None)
                self.save(previous)
            finally:
                self.active = None
                self.process = None
                self.schedule()
