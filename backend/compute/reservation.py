"""Durable GPU session ownership; a missing supervisor never expires ownership."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time
from uuid import uuid4

REQUEST = 'gpu-session.json'
ACK = 'gpu-session-ack.json'


def atomic(path, value):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '-' + uuid4().hex)
    try:
        with open(temporary, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
            json.dump(value, output, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_request(root):
    try:
        value = json.loads((Path(root) / REQUEST).read_text())
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}  # Malformed ownership must still block claims.


def pause_requested(root):
    request = read_request(root)
    if request is None:
        return False
    atomic(Path(root) / ACK, {'token': request.get('token'), 'worker_pid': os.getpid(),
                             'updated_at': time.time()})
    return True


@contextmanager
def locked(path):
    with open(path, 'a', opener=lambda name, flags: os.open(name, flags, 0o600)) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another owner holds ' + Path(path).name) from None
        yield


class Reservation:
    def __init__(self, root):
        self.root = Path(root)
        self.token = uuid4().hex
        self.phase = 'requested'
        self.model_pid = None

    def request(self):
        if read_request(self.root) is not None:
            raise RuntimeError('Existing GPU reservation requires its owner or operator recovery')
        self.write()

    def write(self):
        current = read_request(self.root)
        if current is not None and current.get('token') != self.token:
            raise RuntimeError('GPU reservation ownership changed')
        atomic(self.root / REQUEST, {'token': self.token, 'owner_pid': os.getpid(),
                                    'phase': self.phase, 'model_pid': self.model_pid,
                                    'updated_at': time.time()})

    def acknowledged(self, worker_pid):
        try:
            value = json.loads((self.root / ACK).read_text())
            return (worker_pid > 0 and value.get('token') == self.token
                    and value.get('worker_pid') == worker_pid
                    and 0 <= time.time() - value['updated_at'] < 5
                    and read_request(self.root).get('token') == self.token)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return False

    def release(self):
        current = read_request(self.root)
        if current is None or current.get('token') != self.token:
            raise RuntimeError('Cannot release another GPU reservation')
        if self.phase not in {'requested', 'stopped'}:
            raise RuntimeError('Model lifetime must end before releasing GPU ownership')
        (self.root / REQUEST).unlink()
        (self.root / ACK).unlink(missing_ok=True)
