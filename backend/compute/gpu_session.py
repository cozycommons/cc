"""Linux/systemd CLI for GPU sessions; serve() accepts a portable PID reader."""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from .reservation import Reservation, locked


def worker_pid(service):
    value = subprocess.run(['systemctl', '--user', 'show', service, '--property=MainPID', '--value'],
                           capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    return int(value or '0')


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_model(process):
    # The process group was created by this supervisor, never recovered by PID.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if group_alive(process.pid):
            os.killpg(process.pid, sig)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            continue
        deadline = time.monotonic() + 3
        while group_alive(process.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if not group_alive(process.pid):
            return
    raise RuntimeError('Owned model descendants remain; GPU reservation retained')


def serve(root, command, pid_reader, stop, *, drain_timeout=14400):
    root = Path(root).resolve()
    if not root.is_dir() or not command or drain_timeout <= 0:
        raise ValueError('Existing worker data root, model command and positive drain timeout required')
    owner = Reservation(root)
    process = None
    with ExitStack() as stack:
        stack.enter_context(locked(root / 'gpu-session.lock'))
        # Pair request installation with the updater's existing mutation lock.
        with locked(root.parent / 'update.lock'):
            owner.request()
        try:
            deadline = time.monotonic() + drain_timeout
            while not owner.acknowledged(pid_reader()):
                if stop.wait(0.1):
                    return 130
                if time.monotonic() >= deadline:
                    raise TimeoutError('Worker did not acknowledge drained GPU reservation')
            if stop.is_set():
                return 130
            owner.phase = 'launching'
            owner.write()
            process = subprocess.Popen(command, start_new_session=True)
            owner.model_pid = process.pid
            owner.phase = 'serving'
            owner.write()
            while process.poll() is None and not stop.wait(0.5):
                if not owner.acknowledged(pid_reader()):
                    raise RuntimeError('Worker GPU reservation acknowledgment lost')
            return process.returncode if process.returncode is not None else 130
        finally:
            if process is not None:
                stop_model(process)
                owner.phase = 'stopped'
                owner.write()
            elif owner.phase == 'launching':
                # Popen failed before returning a process to this supervisor.
                owner.phase = 'stopped'
                owner.write()
            owner.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='Existing worker data directory')
    parser.add_argument('--service', default='crowdset-gpu-worker.service')
    parser.add_argument('--drain-timeout', type=float, default=14400)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    try:
        code = serve(args.root, command, lambda: worker_pid(args.service), stop, drain_timeout=args.drain_timeout)
    except (RuntimeError, OSError, ValueError, TimeoutError) as exc:
        parser.exit(1, str(exc) + '\n')
    raise SystemExit(code)


if __name__ == '__main__':
    main()
