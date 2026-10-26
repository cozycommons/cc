"""One shared execution slot, rotating sources after every job."""
import fcntl
import json
import os
from pathlib import Path
import time
from uuid import uuid4

try:
    from .reservation import pause_requested
except ModuleNotFoundError as exc:
    if exc.name != 'compute.reservation':
        raise
    pause_requested = None


def write_status(root, state, job=None):
    value = {'state': state, 'pid': os.getpid(), 'updated_at': time.time(), 'job': job}
    temporary = root / ('.status-' + uuid4().hex)
    try:
        temporary.write_text(json.dumps(value))
        temporary.replace(root / 'status.json')
    finally:
        temporary.unlink(missing_ok=True)


def serve(root, sources, stop):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another worker owns this compute root') from None
        write_status(root, 'idle')
        cursor = 0
        while not stop.is_set():
            if pause_requested is None:
                # Never claim work from an incomplete updater release bundle.
                write_status(root, 'idle')
                stop.wait(1)
                continue
            if pause_requested(root) or (root / 'update-requested').exists():
                write_status(root, 'paused')
                stop.wait(1)
                continue
            offline = False
            for offset in range(len(sources)):
                if pause_requested(root) or (root / 'update-requested').exists():
                    write_status(root, 'paused')
                    break
                index = (cursor + offset) % len(sources)
                source = sources[index]
                try:
                    job = source.claim()
                except Exception:
                    offline = True
                    continue
                if job is None:
                    continue
                write_status(root, 'rendering', job['id'])
                source.run(job)
                cursor = (index + 1) % len(sources)
                break
            else:
                write_status(root, 'offline' if offline else 'idle')
                stop.wait(5)
        write_status(root, 'stopped')
