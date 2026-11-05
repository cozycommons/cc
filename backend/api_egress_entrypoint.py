"""Gate and supervise API commands using proof in their own network namespace.

Scheduled commands invoke this module too: docker exec does not inherit the
runtime secrets loaded by PID 1. No application module is imported by this gate.
"""
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time

RUNTIME_FILE = Path('/run/secrets/api-runtime')
GUARD = ('127.0.0.1', 8001)


def load_runtime(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, separator, value = line.partition('=')
        if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            raise ValueError('expected raw NAME=value lines')
        if key in values:
            raise ValueError('duplicate runtime setting')
        values[key] = value
    return values


def guard_ready(address=GUARD) -> bool:
    try:
        with socket.create_connection(address, timeout=.5):
            return True
    except OSError:
        return False


def wait_for_guard(timeout=30.0, address=GUARD) -> None:
    deadline = time.monotonic() + timeout
    while not guard_ready(address):
        if time.monotonic() >= deadline:
            raise RuntimeError('Namespace firewall readiness timed out')
        time.sleep(.2)
    # Ignore HTTPS_PROXY deliberately. A successful raw socket is a failed gate.
    try:
        connection = socket.create_connection(('1.1.1.1', 443), timeout=.5)
    except OSError:
        return
    connection.close()
    raise RuntimeError('Namespace permits direct internet traffic')


def stop_child(child: subprocess.Popen) -> None:
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def supervise(command: list[str], address=GUARD, interval=5.0) -> int:
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    child = None
    try:
        print(json.dumps({'event': 'egress_app_start', 'time_ns': time.time_ns()}), flush=True)
        child = subprocess.Popen(command, start_new_session=True)
        next_check = time.monotonic() + interval
        while child.poll() is None:
            if stopping:
                stop_child(child)
                return 143
            if time.monotonic() >= next_check:
                if not guard_ready(address):
                    print('Namespace firewall proof disappeared; stopping application', file=sys.stderr, flush=True)
                    stop_child(child)
                    return 1
                next_check = time.monotonic() + interval
            try:
                child.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                pass
        return child.returncode if child.returncode >= 0 else 128 - child.returncode
    finally:
        if child is not None and child.poll() is None:
            stop_child(child)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    # PID 1 must respond to a stop even while it is waiting for the first proof.
    def stop_gate(signum, _frame):
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop_gate)
    try:
        wait_for_guard()
        values = load_runtime(RUNTIME_FILE)
    except (OSError, ValueError, RuntimeError) as exc:
        # File errors may contain secret input; only gate errors are public.
        message = str(exc) if isinstance(exc, RuntimeError) else 'Cannot load API runtime settings'
        raise SystemExit(message) from None
    os.environ.update(values)
    command = sys.argv[1:] or [sys.executable, '-m', 'release']
    raise SystemExit(supervise(command))


if __name__ == '__main__':
    main()
