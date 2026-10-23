"""Bound a trusted handler and its descendants independently of control-plane I/O."""
import os
import signal
import subprocess
import threading
import time


def run(command, log, timeout, heartbeat, *, env=None, interval=15):
    stopped = threading.Event()
    failures = []

    def keep_alive():
        while not stopped.wait(interval):
            try:
                heartbeat()
            except Exception as exc:
                failures.append(exc)
                return

    process = subprocess.Popen(command, stdout=log, stderr=log, env=env, start_new_session=True)
    thread = threading.Thread(target=keep_alive, daemon=True)
    deadline = time.monotonic() + timeout
    thread.start()
    try:
        while True:
            if failures:
                raise failures[0]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Job exceeded its time limit')
            try:
                process.wait(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                pass
        if failures:
            raise failures[0]
        if process.returncode:
            raise RuntimeError(f'Handler exited with status {process.returncode}; inspect worker.log')
    finally:
        stopped.set()
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        # A stalled HTTP heartbeat must not hold the execution slot or deadline.
        thread.join(timeout=0)
