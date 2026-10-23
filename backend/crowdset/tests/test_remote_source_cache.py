import hashlib

import httpx
import pytest

from crowdset import remote_agent


@pytest.fixture
def sources(tmp_path, monkeypatch):
    directory = tmp_path / 'remote' / 'job' / 'claim' / 'set'
    directory.mkdir(parents=True)
    calls = []
    values = {'first': b'a' * 10, 'second': b'b' * 10}
    client = httpx.Client
    def handler(request):
        key = request.url.path.strip('/')
        calls.append(key)
        return httpx.Response(200, content=values[key])
    monkeypatch.setattr(remote_agent.httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    control = remote_agent.Control('http://127.0.0.1:9', 'synthetic')
    monkeypatch.setattr(control, 'call', lambda operation, key: {'url': 'https://media.example/' + key})
    originals = remote_agent.WorkerOriginals(directory.parent, control)
    def clip(key):
        return {'id': key, 'object_key': key, 'bytes': len(values[key]), 'sha256': hashlib.sha256(values[key]).hexdigest()}
    return originals, directory, calls, clip


def test_pipeline_stage_cleanup_does_not_download_the_original_again(sources):
    originals, directory, calls, clip = sources
    for _ in range(3):
        source = originals.materialize('set', clip('first'), directory)
        assert source.read_bytes() == b'a' * 10
        source.unlink()
    assert calls == ['first']


def test_corrupt_cache_is_verified_and_replaced_before_reuse(sources):
    originals, directory, calls, clip = sources
    source = originals.materialize('set', clip('first'), directory)
    source.write_bytes(b'corruption')
    source.unlink()
    repaired = originals.materialize('set', clip('first'), directory)
    assert repaired.read_bytes() == b'a' * 10
    assert calls == ['first', 'first']


def test_cache_evicts_unused_bytes_but_retains_active_stage_files(sources, monkeypatch):
    originals, directory, calls, clip = sources
    monkeypatch.setattr(remote_agent, 'SOURCE_CACHE_BYTES', 10)
    active = originals.materialize('set', clip('first'), directory)
    second = originals.materialize('set', clip('second'), directory)
    assert active.read_bytes() == b'a' * 10
    assert second.read_bytes() == b'b' * 10
    cache = originals.spool / 'source-cache'
    assert sum(p.stat().st_size for p in cache.iterdir()) == 10
    active.unlink()
    second.unlink()
    originals.materialize('set', clip('second'), directory).unlink()
    assert not (cache / (clip('first')['sha256'] + '.original')).exists()
    assert sum(p.stat().st_size for p in cache.iterdir()) == 10
    assert calls == ['first', 'second', 'second']


def test_old_updater_waits_for_shared_runtime_without_claiming(tmp_path, monkeypatch):
    import builtins
    import json
    real_import = builtins.__import__
    def missing_runtime(name, *args, **kwargs):
        if name == 'compute.runner':
            raise ModuleNotFoundError("No module named 'compute'", name='compute')
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', missing_runtime)
    class Stop:
        done = False
        def is_set(self):
            return self.done
        def wait(self, _seconds):
            assert json.loads((tmp_path / 'status.json').read_text())['state'] == 'paused'
            self.done = True
    (tmp_path / 'update-requested').touch()
    remote_agent.serve(tmp_path, '/ffmpeg', '/ffprobe', 'libx264', Stop())


def test_adapter_advertises_capacity_and_bounds_execution(tmp_path, monkeypatch):
    from compute import process
    from compute.jobs import Resources
    monkeypatch.setenv('CROWDSET_WORKER_URL', 'http://127.0.0.1:9')
    monkeypatch.setenv('CROWDSET_WORKER_TOKEN', 'synthetic')
    calls = []
    def call(self, operation, **body):
        calls.append((operation, body))
        return None
    monkeypatch.setattr(remote_agent.Control, 'call', call)
    source = remote_agent.Source(tmp_path, '/ffmpeg', '/ffprobe', 'h264_nvenc', Resources(cpu=4, memory_mb=8192, gpu=1))
    source.claim()
    assert calls == [('claim-v2', {'capacity': {'cpu': 4, 'memory_mb': 8192, 'gpu': 1}, 'encoder': 'h264_nvenc'})]
    (tmp_path / 'failed').mkdir()
    def timed_out(command, log, timeout, heartbeat):
        assert command[1:3] == ['-m', 'crowdset.remote_agent']
        assert timeout == 14400
        heartbeat()
        raise TimeoutError('Job exceeded its time limit')
    monkeypatch.setattr(process, 'run', timed_out)
    source.run({'id': 'a' * 32, 'claim': 'b' * 32, 'set_id': 'c' * 32, 'kind': 'process', 'limits': {'job_seconds': 14400}})
    assert calls[-1] == ('fail', {'error': 'Job exceeded its time limit'})
    assert not list(tmp_path.rglob('published.json'))
