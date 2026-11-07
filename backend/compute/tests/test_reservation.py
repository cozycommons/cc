import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from compute import runner
from compute.gpu_session import serve as session
from compute.reservation import ACK, REQUEST, Reservation, atomic, locked, pause_requested, read_request


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError('Timed out waiting for test transition')
        time.sleep(0.01)


def test_reservation_ownership_fresh_ack_and_no_implicit_expiry(tmp_path):
    owner = Reservation(tmp_path)
    owner.request()
    assert not owner.acknowledged(os.getpid())
    assert pause_requested(tmp_path)
    assert owner.acknowledged(os.getpid())
    assert not owner.acknowledged(os.getpid() + 1)
    other = Reservation(tmp_path)
    with pytest.raises(RuntimeError):
        other.request()
    with pytest.raises(RuntimeError):
        other.release()
    value = json.loads((tmp_path / ACK).read_text())
    value['updated_at'] -= 60
    atomic(tmp_path / ACK, value)
    assert not owner.acknowledged(os.getpid())
    assert read_request(tmp_path)['token'] == owner.token
    owner.phase = 'serving'
    with pytest.raises(RuntimeError):
        owner.release()
    owner.phase = 'stopped'
    owner.release()
    assert not pause_requested(tmp_path)


def test_malformed_request_pauses_and_updater_marker_is_independent(tmp_path):
    (tmp_path / REQUEST).write_text('broken')
    assert pause_requested(tmp_path)
    assert json.loads((tmp_path / ACK).read_text())['token'] is None
    (tmp_path / REQUEST).unlink()
    (tmp_path / 'update-requested').touch()
    owner = Reservation(tmp_path)
    owner.request()
    pause_requested(tmp_path)
    owner.release()
    assert (tmp_path / 'update-requested').exists()


def test_worker_drains_claimed_job_before_acknowledging_and_never_claims_next(tmp_path):
    started, finish, stop = threading.Event(), threading.Event(), threading.Event()
    calls = []

    class Source:
        def claim(self):
            calls.append('claim')
            return {'id': 'render'}
        def run(self, job):
            started.set()
            assert finish.wait(4)
            calls.append('finished-and-published')

    thread = threading.Thread(target=runner.serve, args=(tmp_path, [Source()], stop))
    thread.start()
    owner = Reservation(tmp_path)
    try:
        assert started.wait(4)
        owner.request()
        assert not owner.acknowledged(os.getpid())
        assert calls == ['claim']
        finish.set()
        wait_for(lambda: owner.acknowledged(os.getpid()))
        assert calls == ['claim', 'finished-and-published']
        assert json.loads((tmp_path / 'status.json').read_text())['state'] == 'paused'
    finally:
        finish.set()
        stop.set()
        thread.join(4)
    assert not thread.is_alive()
    assert read_request(tmp_path)['token'] == owner.token


def test_request_during_claim_waits_for_accepted_job_lifetime(tmp_path):
    owner = Reservation(tmp_path)
    calls = []

    class Stop:
        done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            self.done = True

    class Source:
        def claim(self):
            owner.request()
            calls.append('accepted')
            return {'id': 'inflight'}
        def run(self, job):
            assert not owner.acknowledged(os.getpid())
            calls.append('published')

    runner.serve(tmp_path, [Source()], Stop())
    assert calls == ['accepted', 'published']
    assert owner.acknowledged(os.getpid())


def test_preexisting_reservation_survives_worker_restart(tmp_path):
    owner = Reservation(tmp_path)
    owner.request()
    class Stop:
        done = False
        def is_set(self): return self.done
        def wait(self, seconds): self.done = True
    class Source:
        def claim(self): raise AssertionError('reserved worker cannot claim')
    for _ in range(2):
        runner.serve(tmp_path, [Source()], Stop())
        assert owner.acknowledged(os.getpid())


def test_session_loads_only_after_ack_and_releases_after_owned_model_exits(tmp_path):
    launched = tmp_path / 'model-launched'
    stop = threading.Event()
    done = threading.Event()
    errors = []

    def supervise():
        try:
            assert session(tmp_path, [sys.executable, '-c',
                           f'from pathlib import Path; Path({str(launched)!r}).touch()'],
                           lambda: os.getpid(), stop, drain_timeout=3) == 0
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=supervise)
    thread.start()
    wait_for(lambda: read_request(tmp_path) is not None)
    assert not launched.exists()
    while not done.wait(0.02):
        pause_requested(tmp_path)
    thread.join(4)
    assert not errors and launched.exists()
    assert not (tmp_path / REQUEST).exists()


def test_model_failure_cleanup_and_drain_timeout(tmp_path):
    stop = threading.Event()
    def acknowledge():
        pause_requested(tmp_path)
        return os.getpid()
    assert session(tmp_path, [sys.executable, '-c', 'raise SystemExit(7)'], acknowledge, stop) == 7
    assert not (tmp_path / REQUEST).exists()
    with pytest.raises(TimeoutError):
        session(tmp_path, [sys.executable, '-c', 'raise AssertionError()'], lambda: 0,
                stop, drain_timeout=0.1)
    assert not (tmp_path / REQUEST).exists()


def test_supervisor_crash_retains_ownership_until_operator_recovery(tmp_path):
    root = str(tmp_path)
    code = f'''
from pathlib import Path
import os, threading
from compute.gpu_session import serve
from compute.reservation import pause_requested
root=Path({root!r})
def acknowledge():
    pause_requested(root)
    return os.getpid()
serve(root, [{sys.executable!r}, '-c', 'import time; time.sleep(30)'], acknowledge, threading.Event())
'''
    supervisor = subprocess.Popen([sys.executable, '-c', code], start_new_session=True)
    model_pid = None
    try:
        wait_for(lambda: (read_request(tmp_path) or {}).get('phase') == 'serving')
        model_pid = read_request(tmp_path)['model_pid']
        supervisor.kill()
        supervisor.wait(timeout=4)
        os.kill(model_pid, 0)
        assert pause_requested(tmp_path)
        with pytest.raises(RuntimeError, match='operator recovery'):
            Reservation(tmp_path).request()
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=4)
        if model_pid:
            try:
                os.killpg(model_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    assert (tmp_path / REQUEST).exists()


def test_release_refuses_to_override_changed_ownership(tmp_path):
    owner = Reservation(tmp_path)
    owner.request()
    atomic(tmp_path / REQUEST, {'token': 'replacement'})
    with pytest.raises(RuntimeError):
        owner.release()
    assert read_request(tmp_path)['token'] == 'replacement'


def test_update_lock_blocks_session_request(tmp_path):
    with locked(tmp_path.parent / 'update.lock'):
        with pytest.raises(RuntimeError, match='update.lock'):
            session(tmp_path, [sys.executable, '-c', 'pass'], lambda: 0, threading.Event())
    assert read_request(tmp_path) is None


def test_incomplete_updater_bundle_cannot_claim_jobs(tmp_path):
    package = tmp_path / 'compute'
    package.mkdir()
    (package / '__init__.py').touch()
    (package / 'runner.py').write_text(Path(runner.__file__).read_text())
    code = '''
from pathlib import Path
from compute.runner import serve
class Stop:
    done=False
    def is_set(self): return self.done
    def wait(self, seconds): self.done=True
class Source:
    def claim(self): raise AssertionError('incomplete bundle claimed work')
serve(Path('data'), [Source()], Stop())
'''
    subprocess.run([sys.executable, '-c', code], cwd=tmp_path, check=True, timeout=4,
                   env={**os.environ, 'PYTHONPATH': str(tmp_path)})
    assert json.loads((tmp_path / 'data/status.json').read_text())['state'] == 'stopped'


def test_normal_stop_reaps_owned_model_before_release_and_leaves_other_process(tmp_path):
    stop = threading.Event()
    failures = []
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    def acknowledge():
        pause_requested(tmp_path)
        return os.getpid()
    def supervise():
        try:
            assert session(tmp_path, [sys.executable, '-c', 'import time; time.sleep(30)'], acknowledge, stop) == 130
        except BaseException as exc:
            failures.append(exc)
    thread = threading.Thread(target=supervise)
    thread.start()
    try:
        wait_for(lambda: (read_request(tmp_path) or {}).get('phase') == 'serving')
        pid = read_request(tmp_path)['model_pid']
        stop.set()
        thread.join(4)
        assert not thread.is_alive() and not failures
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert other.poll() is None
        assert read_request(tmp_path) is None
    finally:
        stop.set()
        thread.join(4)
        other.terminate()
        other.wait(timeout=4)


@pytest.mark.parametrize('when', ['before_popen', 'after_popen_before_record'])
def test_crash_during_launch_keeps_ambiguous_ownership_fail_closed(tmp_path, when):
    pid_file = tmp_path / 'test-owned-child.pid'
    code = f'''
from pathlib import Path
import os,signal,sys,threading
from compute import gpu_session
from compute.reservation import pause_requested
root=Path({str(tmp_path)!r})
original=gpu_session.subprocess.Popen
def crash(*args, **kwargs):
    if {when!r} == 'after_popen_before_record':
        process=original(*args, **kwargs)
        Path({str(pid_file)!r}).write_text(str(process.pid))
    os.kill(os.getpid(),signal.SIGKILL)
def acknowledge():
    pause_requested(root)
    return os.getpid()
gpu_session.subprocess.Popen=crash
gpu_session.serve(root,[sys.executable,'-c','import time; time.sleep(30)'],acknowledge,threading.Event())
'''
    supervisor = subprocess.Popen([sys.executable, '-c', code])
    try:
        supervisor.wait(timeout=4)
        assert supervisor.returncode == -signal.SIGKILL
        request = read_request(tmp_path)
        assert request['phase'] == 'launching' and request['model_pid'] is None
        assert pause_requested(tmp_path)
        if when == 'after_popen_before_record':
            os.kill(int(pid_file.read_text()), 0)
        with pytest.raises(RuntimeError, match='operator recovery'):
            Reservation(tmp_path).request()
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=4)
        if pid_file.exists():
            try:
                os.killpg(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
    assert (tmp_path / REQUEST).exists()
