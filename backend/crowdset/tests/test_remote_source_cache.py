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
