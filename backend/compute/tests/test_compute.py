from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading

from fastapi.testclient import TestClient
import httpx
import pytest

from compute.api import create_app
from compute.client import Client
from compute.jobs import Registry, Resources
from compute.queue import Conflict, Queue
from compute.runner import serve
from compute.worker import Source

MODULES = ['compute.tests.jobs_fixture']


@pytest.fixture
def queue(tmp_path):
    return Queue(tmp_path / 'jobs.sqlite3', Registry.load(MODULES))


def claim(queue, **kwargs):
    return queue.claim('pc', list(queue.registry.jobs), kwargs.get('capacity', Resources(cpu=4, memory_mb=8192, gpu=1)))


def test_restart_dedup_and_project_isolation(queue):
    job = queue.submit('alpha', 'alpha.uppercase@1', {'text': 'hi'}, 'request-1')
    reopened = Queue(queue.path, queue.registry)
    assert reopened.submit('alpha', job['type'], job['payload'], 'request-1')['id'] == job['id']
    with pytest.raises(Conflict):
        queue.submit('alpha', job['type'], {'text': 'other'}, 'request-1')
    with pytest.raises(PermissionError):
        queue.submit('beta', job['type'], job['payload'])
    with pytest.raises(KeyError):
        queue.status('beta', job['id'])
    with pytest.raises(ValueError):
        queue.submit('alpha', 'os.system@1', {})
    with pytest.raises(ValueError):
        queue.submit('alpha', job['type'], {'extra': True})


def test_concurrent_claim_and_capacity(queue):
    gpu = queue.submit('alpha', 'alpha.gpu@1', {'text': 'gpu'})
    cpu = queue.submit('beta', 'beta.uppercase@1', {'text': 'cpu'})
    assert claim(queue, capacity=Resources())['id'] == cpu['id']
    assert claim(queue) is None
    queue = Queue(queue.path + '.parallel', queue.registry)
    queue.submit('alpha', 'alpha.uppercase@1', {'text': 'hi'})
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim(queue), range(4)))
    assert sum(job is not None for job in claims) == 1


def test_expiry_fences_old_claim_and_exhausts_retries(queue):
    now = [1000.0]
    queue.clock = lambda: now[0]
    original = queue.submit('alpha', 'alpha.uppercase@1', {'text': 'hi'})
    first = claim(queue)
    now[0] += 121
    second = claim(queue)
    assert second['claim'] != first['claim']
    assert second['attempts'] == 2
    with pytest.raises(Conflict):
        queue.finish(first['id'], first['claim'], {'text': 'OLD'})
    now[0] += 121
    assert claim(queue) is None
    assert queue.status('alpha', original['id'])['state'] == 'failed'


def test_heartbeat_deadline_and_publication_replay(queue):
    now = [1000.0]
    queue.clock = lambda: now[0]
    queue.submit('alpha', 'alpha.uppercase@1', {'text': 'hi'})
    job = claim(queue)
    for delta in (100, 100, 99):
        now[0] += delta
        queue.heartbeat(job['id'], job['claim'], {'stage': 'working'})
    now[0] += 1
    with pytest.raises(Conflict):
        queue.heartbeat(job['id'], job['claim'], {})
    job = claim(queue)
    with pytest.raises(ValueError):
        queue.finish(job['id'], job['claim'], {'wrong': 'output'})
    queue.finish(job['id'], job['claim'], {'text': 'HI'})
    assert queue.finish(job['id'], job['claim'], {'text': 'HI'}) == {'ok': True}
    with pytest.raises(Conflict):
        queue.finish(job['id'], job['claim'], {'text': 'different'})
    result = queue.status('alpha', job['id'])
    assert result['result'] == {'text': 'HI'}
    assert 'claim' not in result


def test_api_authorization_validation_and_bounds(queue):
    client = TestClient(create_app(queue, {'alpha': 'a', 'beta': 'b'}, 'worker'))
    body = {'type': 'alpha.uppercase@1', 'payload': {'text': 'hi'}}
    assert client.post('/compute/jobs', json=body).status_code == 401
    assert client.post('/compute/jobs', json=body, headers={'Authorization': 'Bearer worker'}).status_code == 401
    headers = {'Authorization': 'Bearer a'}
    job = client.post('/compute/jobs', json=body, headers=headers).json()
    assert client.get('/compute/jobs/' + job['id'], headers={'Authorization': 'Bearer b'}).status_code == 404
    assert client.post('/compute/jobs', json=body, headers={'Authorization': 'Bearer b'}).status_code == 403
    assert client.post('/compute/worker/claim', json={'worker': 'pc', 'types': [body['type']], 'capacity': {}}, headers=headers).status_code == 401
    body['payload'] = {'wrong': 'input'}
    assert client.post('/compute/jobs', json=body, headers=headers).status_code == 422
    assert client.post('/compute/jobs', content=b'x' * (301 * 1024), headers=headers).status_code == 413


class LocalControl:
    def __init__(self, queue):
        self.queue = queue

    def call(self, path, body):
        if path == 'worker/claim':
            return self.queue.claim(body['worker'], body['types'], Resources(**body['capacity']))
        if path == 'worker/heartbeat':
            return self.queue.heartbeat(body['job'], body['claim'], body['progress'])
        return self.queue.finish(body['job'], body['claim'], body.get('result'), body.get('error'))


@pytest.mark.parametrize('kind,expected', [('alpha.uppercase@1', 'succeeded'), ('alpha.fail@1', 'failed'), ('alpha.hang@1', 'failed')])
def test_real_handler_subprocess(queue, tmp_path, kind, expected):
    job = queue.submit('alpha', kind, {'text': 'hello'})
    source = Source(tmp_path, LocalControl(queue), MODULES, Resources())
    source.run(source.claim())
    result = queue.status('alpha', job['id'])
    assert result['state'] == expected
    if kind == 'alpha.hang@1':
        pid = int(next(tmp_path.glob('jobs/*/*/handler.pid')).read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    if expected == 'succeeded':
        assert result['result'] == {'text': 'HELLO'}


def test_runner_rotates_sources_and_honors_update_pause(tmp_path):
    stop = threading.Event()
    calls = []
    class Source:
        def __init__(self, name):
            self.name = name
        def claim(self):
            return {'id': self.name}
        def run(self, job):
            calls.append(job['id'])
            if len(calls) == 4:
                stop.set()
    serve(tmp_path, [Source('crowdset'), Source('other')], stop)
    assert calls == ['crowdset', 'other', 'crowdset', 'other']
    (tmp_path / 'update-requested').touch()
    class StopAfterWait:
        done = False
        def is_set(self):
            return self.done
        def wait(self, seconds):
            assert json.loads((tmp_path / 'status.json').read_text())['state'] == 'paused'
            self.done = True
    serve(tmp_path, [Source('should-not-run')], StopAfterWait())
    assert len(calls) == 4


def test_client_requires_secure_transport():
    with pytest.raises(ValueError):
        Client('http://example.com', 'token')
    assert Client('http://127.0.0.1:8011', 'token')


def test_producer_to_worker_http_contract(queue, tmp_path):
    server = TestClient(create_app(queue, {'alpha': 'a', 'beta': 'b'}, 'worker'))
    def forward(request):
        return server.request(request.method, request.url.path, content=request.content, headers=dict(request.headers))
    transport = httpx.MockTransport(forward)
    producer = Client('http://127.0.0.1:8011', 'b', transport)
    worker = Client('http://127.0.0.1:8011', 'worker', transport)
    job = producer.submit('beta.uppercase@1', {'text': 'second project'})
    source = Source(tmp_path, worker, MODULES, Resources())
    source.run(source.claim())
    assert producer.status(job['id'])['result'] == {'text': 'SECOND PROJECT'}


def test_heartbeat_failure_kills_handler_before_releasing_slot(queue, tmp_path, monkeypatch):
    from compute import worker
    monkeypatch.setattr(worker, 'HEARTBEAT_SECONDS', 0.3)
    class Offline(LocalControl):
        def call(self, path, body):
            if path == 'worker/heartbeat':
                raise ConnectionError('control plane offline')
            if path == 'worker/finish':
                pid = int(next(tmp_path.glob('jobs/*/*/handler.pid')).read_text())
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
                assert 'result' not in body
            return super().call(path, body)
    job = queue.submit('alpha', 'alpha.hang@1', {'text': 'hello'})
    source = Source(tmp_path, Offline(queue), MODULES, Resources())
    source.run(source.claim())
    assert queue.status('alpha', job['id'])['state'] == 'failed'


def test_explicit_failure_retries_to_declared_limit(queue):
    job = queue.submit('alpha', 'alpha.uppercase@1', {'text': 'hi'})
    for attempt in (1, 2):
        leased = claim(queue)
        assert leased['attempts'] == attempt
        queue.finish(job['id'], leased['claim'], error='failed')
    assert claim(queue) is None
    assert queue.status('alpha', job['id'])['state'] == 'failed'


def test_registry_rejects_duplicate_and_unknown_versions():
    registry = Registry.load(MODULES)
    with pytest.raises(ValueError, match='Duplicate'):
        Registry([*registry.jobs.values(), *registry.jobs.values()])
    with pytest.raises(ValueError, match='Unknown'):
        registry.get('alpha.uppercase@2')


def test_shared_lock_prevents_second_runner(tmp_path):
    import fcntl
    with (tmp_path / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match='Another worker'):
            serve(tmp_path, [], threading.Event())


def test_timeout_is_independent_of_blocked_heartbeat(tmp_path):
    import sys
    import time
    from compute.process import run
    entered = threading.Event()
    release = threading.Event()
    def heartbeat():
        entered.set()
        release.wait(5)
    started = time.monotonic()
    try:
        with (tmp_path / 'worker.log').open('wb') as log, pytest.raises(TimeoutError):
            run([sys.executable, '-c', 'import time; time.sleep(60)'], log,
                0.4, heartbeat, interval=0.01)
        assert entered.is_set()
        assert time.monotonic() - started < 2
    finally:
        release.set()


def test_process_supervisor_kills_descendants(tmp_path):
    import sys
    import time
    from compute.process import run
    ticks = tmp_path / 'ticks'
    child = 'import time; f=open(' + repr(str(ticks)) + ', "w", buffering=1)\nwhile True: f.write("x\\n"); time.sleep(.02)'
    parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(child) + ']); time.sleep(60)'
    with (tmp_path / 'worker.log').open('wb') as log, pytest.raises(TimeoutError):
        run([sys.executable, '-c', parent], log, 1, lambda: None)
    before = ticks.read_bytes()
    time.sleep(.2)
    assert before and ticks.read_bytes() == before


def test_status_writes_do_not_share_temporary_files(tmp_path):
    from compute.runner import write_status
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: write_status(tmp_path, 'rendering', str(n)), range(100)))
    assert json.loads((tmp_path / 'status.json').read_text())['state'] == 'rendering'
    assert list(tmp_path.iterdir()) == [tmp_path / 'status.json']
