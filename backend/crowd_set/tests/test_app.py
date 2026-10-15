from contextlib import contextmanager
import json
import time
import wave

from fastapi.testclient import TestClient
import numpy as np
import pytest

from crowd_set.app import create_app
from crowd_set.store import Store
from crowd_set.tests.test_audio import music, write_wav


@contextmanager
def client(root):
    with TestClient(create_app(root), base_url='http://127.0.0.1') as api:
        yield api


def create(api):
    result = api.post('/crowd-set/sets', json={'name': 'Test performance'})
    assert result.status_code == 201
    return '/crowd-set/sets/' + result.json()['id']


def upload(api, path, name, data, role='crowd'):
    return api.put(path + '/clips', params={'name': name, 'role': role}, content=data)


def wait(api, path):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        data = api.get(path).json()
        if data['status'] != 'processing':
            return data
        time.sleep(.05)
    pytest.fail('Worker did not finish within 40 seconds')


def test_local_validation_and_safe_uploads(tmp_path, monkeypatch):
    with client(tmp_path) as api:
        assert api.get('/crowd-set/sets', headers={'host': 'evil.example'}).status_code == 403
        assert api.get('/crowd-set/sets', headers={'origin': 'https://evil.example'}).status_code == 403
        assert api.get('/crowd-set/sets', headers={'origin': 'http://127.0.0.1:8083'}).status_code == 200
        assert api.post('/crowd-set/sets', json={'name': '   '}).status_code == 422
        path = create(api)
        assert api.post(path + '/process').status_code == 400
        assert upload(api, path, 'playlist.m3u', b'bad').status_code == 415
        assert upload(api, path, 'empty.wav', b'').status_code == 400
        assert upload(api, path, 'x.wav', b'x', 'unknown').status_code == 422
        monkeypatch.setattr('crowd_set.app.MAX_BYTES', 20)
        assert upload(api, path, 'big.wav', b'a' * 21).status_code == 413
        chunked = api.put(path + '/clips', params={'name': 'chunked.wav', 'role': 'crowd'}, content=iter([b'a' * 10, b'b' * 11]))
        assert chunked.status_code == 413
        assert api.get(path).json()['status'] == 'idle'
        assert not list(tmp_path.rglob('*.part'))
        result = upload(api, path, '../../outside.wav', b'bad audio', 'reference')
        assert result.status_code == 201
        reference = result.json()['clips'][0]
        assert reference['name'] == 'outside.wav'
        assert '/' not in reference['file']
        assert not (tmp_path.parent / 'outside.wav').exists()
        assert upload(api, path, 'ref.wav', b'abc', 'reference').status_code == 409
        assert api.patch(path + '/clips/' + reference['id'], json={'included': True}).status_code == 400
        assert api.get(path + '/audio').status_code == 404
        assert api.get('/crowd-set/sets/not-a-uuid').status_code == 404


def test_upload_process_playback_invalidation_and_restart(tmp_path):
    raw = music(100)
    reference = write_wav(tmp_path / 'reference.wav', raw).read_bytes()
    a = write_wav(tmp_path / 'a.wav', raw[20 * 16000:70 * 16000]).read_bytes()
    b = write_wav(tmp_path / 'b.wav', raw[50 * 16000:95 * 16000]).read_bytes()
    root = tmp_path / 'store'
    with client(root) as api:
        path = create(api)
        upload(api, path, 'reference.wav', reference, 'reference')
        upload(api, path, 'a.wav', a)
        upload(api, path, 'b.wav', b)
        assert api.post(path + '/process').status_code == 202
        assert api.post(path + '/process').status_code == 409
        assert upload(api, path, 'during.wav', b).status_code == 409
        assert api.delete(path).status_code == 409
        result = wait(api, path)
        assert result['status'] == 'ready', result
        assert result['playable']
        assert result['timeline']['output_true_peak_dbfs'] <= -1.9
        assert result['timeline']['covered_seconds'] == pytest.approx(75, abs=.1)
        assert all(c['alignment']['status'] == 'matched' for c in result['clips'][1:])
        output = api.get(path + '/audio?download=true')
        assert output.status_code == 200
        assert 'attachment' in output.headers['content-disposition']
        assert output.content[:4] == b'RIFF'
        assert api.get(path + '/audio', headers={'Range': 'bytes=0-99'}).status_code == 206
        (tmp_path / 'result.wav').write_bytes(output.content)
        with wave.open(str(tmp_path / 'result.wav')) as audio:
            assert audio.getnframes() / audio.getframerate() == 100
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')
        assert not samples[:19 * 32000].any()
        assert not samples[96 * 32000:].any()
    with client(root) as api:
        assert api.get(path).json()['playable']
        clip = api.get(path).json()['clips'][1]
        changed = api.patch(path + '/clips/' + clip['id'], json={'included': False}).json()
        assert changed['timeline'] is None
        assert not changed['playable']
        assert api.get(path + '/audio').status_code == 404
        assert api.delete(path).status_code == 204
        assert api.get(path).status_code == 404


def test_bad_reference_failure_and_bad_clip_no_coverage(tmp_path):
    with client(tmp_path / 'store') as api:
        path = create(api)
        upload(api, path, 'bad.wav', b'bad', 'reference')
        upload(api, path, 'bad.wav', b'bad')
        api.post(path + '/process')
        result = wait(api, path)
        assert result['status'] == 'failed'
        assert 'Cannot decode' in result['error']
        api.delete(path + '/clips/' + result['clips'][0]['id'])
        reference = write_wav(tmp_path / 'ref.wav', music(40)).read_bytes()
        upload(api, path, 'ref.wav', reference, 'reference')
        api.post(path + '/process')
        result = wait(api, path)
        assert result['status'] == 'ready'
        assert not result['playable']
        assert result['timeline']['gaps'] == [{'start': 0, 'end': 40}]
        assert result['clips'][0]['alignment']['status'] == 'error'


def test_interrupted_recovery_and_single_server_lock(tmp_path):
    store = Store(tmp_path)
    data = store.create('Interrupted')
    data['status'] = 'processing'
    store.save(data)
    with pytest.raises(RuntimeError, match='already open'):
        Store(tmp_path)
    store.close()
    with client(tmp_path) as api:
        result = api.get('/crowd-set/sets/' + data['id']).json()
        assert result['status'] == 'failed'
        assert 'interrupted' in result['error']


def test_worker_retains_storage_ownership_after_parent_crash(tmp_path):
    import os
    from pathlib import Path
    import signal
    import subprocess
    import sys
    root = tmp_path / 'store'
    script = tmp_path / 'parent.py'
    # Delay the actual worker after exec to make the parent-crash window deterministic.
    script.write_text('''
import json, pathlib, subprocess, sys, time
from crowd_set.store import Store
root = pathlib.Path(sys.argv[1])
store = Store(root)
real_popen = subprocess.Popen
def paused_worker(command, **kwargs):
    replacement = [command[0], '-c', "import runpy,sys,time; time.sleep(2); sys.argv=['worker',sys.argv[1]]; runpy.run_module('crowd_set.worker',run_name='__main__')", command[-1]]
    process = real_popen(replacement, **kwargs)
    (root / 'worker-pid').write_text(str(process.pid))
    return process
subprocess.Popen = paused_worker
item = store.create('Crash test')
for role in ('reference', 'crowd'):
    clip, partial = store.begin_upload(item['id'], 'broken.wav', role)
    partial.write_bytes(b'bad media')
    store.finish_upload(item['id'], clip, partial, True)
store.start(item['id'])
while True: time.sleep(1)
''')
    parent = subprocess.Popen([sys.executable, str(script), str(root)], env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])})
    worker_pid = None
    try:
        deadline = time.monotonic() + 10
        while not (root / 'worker-pid').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        worker_pid = int((root / 'worker-pid').read_text())
        parent.kill(); parent.wait()
        with pytest.raises(RuntimeError, match='already open'):
            Store(root)
        recovered = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                recovered = Store(root)
                break
            except RuntimeError:
                time.sleep(.05)
        assert recovered is not None
        assert recovered.list()[0]['status'] == 'failed'
        recovered.close()
    finally:
        if parent.poll() is None:
            parent.kill(); parent.wait()
        if worker_pid:
            try:
                os.killpg(worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
