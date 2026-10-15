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
        for path in self.root.glob('*/set.json'):
            data = json.loads(path.read_text())
            if data['status'] in ('processing', 'uploading'):
                data.update(status='failed', error='Previous operation was interrupted. Retry processing or upload the file again.', playable=False)
                write_json(path, data)
            for partial in path.parent.glob('*.part'):
                partial.unlink()

    def close(self):
        with self.lock:
            self.closed = True
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
            data = {'id': uuid4().hex, 'name': name, 'owner': owner, 'status': 'idle', 'clips': [], 'timeline': None, 'playable': False, 'error': None}
            self.directory(data['id']).mkdir(mode=0o700)
            return self.save(data)

    def editable(self, set_id):
        data = self.get(set_id)
        if data['status'] in ('processing', 'uploading'):
            raise HTTPException(409, 'Wait for the current operation to finish.')
        return data

    def invalidate(self, data):
        data.update(status='idle', error=None, timeline=None, playable=False)
        data.pop('stage', None)
        for clip in data['clips']:
            clip.pop('alignment', None)
        directory = self.directory(data['id'])
        for pattern in ('*.wav', 'result.json', 'failure.json', 'progress.json', 'job.json'):
            for path in directory.glob(pattern):
                # Originals use a .upload suffix, including uploaded WAV files.
                path.unlink(missing_ok=True)

    def begin_upload(self, set_id, name, role):
        with self.lock:
            data = self.editable(set_id)
            if self.upload:
                raise HTTPException(409, 'Another upload is active. Try again when it finishes.')
            suffix = Path(name).suffix.lower()
            if suffix not in EXTENSIONS:
                raise HTTPException(415, 'Supported files: WAV, MP3, M4A, MP4, MOV, AAC, FLAC, OGG, WEBM.')
            if role == 'reference' and any(c['role'] == role for c in data['clips']):
                raise HTTPException(409, 'Remove the existing reference before replacing it.')
            if role == 'crowd' and sum(c['role'] == role for c in data['clips']) >= 8:
                raise HTTPException(409, 'Local limit: 8 crowd clips per performance.')
            used = sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
            if used + MAX_BYTES + 3 * 1024 ** 3 > DISK_BUDGET or shutil.disk_usage(self.root).free < MAX_BYTES + 3 * 1024 ** 3:
                raise HTTPException(507, 'Not enough local storage. Delete an old performance to free space.')
            clip = {'id': uuid4().hex, 'name': Path(name).name[:180], 'role': role, 'included': True}
            clip['file'] = f'{clip["id"]}{suffix}.upload'
            self.upload = (set_id, clip['id'])
            data['status'] = 'uploading'
            self.save(data)
            return clip, self.directory(set_id) / (clip['id'] + '.part')

    def finish_upload(self, set_id, clip, partial, success):
        with self.lock:
            self.upload = None
            data = self.get(set_id)
            if success:
                self.invalidate(data)
                partial.replace(self.directory(set_id) / clip['file'])
                data['clips'].append(clip)
            else:
                partial.unlink(missing_ok=True)
                data['status'] = 'ready' if data['timeline'] else 'idle'
            return self.save(data)

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
                (self.directory(set_id) / clip['file']).unlink(missing_ok=True)
                data['clips'].remove(clip)
            else:
                clip['included'] = included
            return self.save(data)

    def delete(self, set_id):
        with self.lock:
            self.editable(set_id)
            shutil.rmtree(self.directory(set_id))

    def start(self, set_id):
        with self.lock:
            data = self.editable(set_id)
            if self.active:
                raise HTTPException(409, 'Another reconstruction is processing. Try again when it finishes.')
            if not any(c['role'] == 'reference' for c in data['clips']):
                raise HTTPException(400, 'Add a timing reference. Reference-free alignment is not supported yet.')
            if not any(c['role'] == 'crowd' and c['included'] for c in data['clips']):
                raise HTTPException(400, 'Add and include at least one crowd clip.')
            self.invalidate(data)
            data.update(status='processing', stage='Starting processing')
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
            if error:
                data.update(status='failed', error=error, playable=False)
            else:
                data.update(result, status='ready', error=None)
            data.pop('stage', None)
            self.save(data)
            self.active = None
            self.process = None
