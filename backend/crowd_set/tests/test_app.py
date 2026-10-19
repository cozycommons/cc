from contextlib import contextmanager
import json
import time
import wave

from fastapi import HTTPException
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
        if data['status'] not in ('processing', 'queued'):
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


def test_auto_mix_original_video_publication_cache_and_restart(tmp_path):
    import subprocess
    import imageio_ffmpeg
    raw = music(100)
    source = write_wav(tmp_path / 'source.wav', raw[:80 * 16000])
    video = tmp_path / 'video.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=green:s=160x90:r=1', '-i', str(source), '-shortest', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(video)], check=True, timeout=30)
    original = video.read_bytes()
    root = tmp_path / 'store'
    with client(root) as api:
        path = create(api)
        uploaded = upload(api, path, 'stage.mp4', original).json()
        assert uploaded['status'] == 'queued'
        clip_id = uploaded['clips'][0]['id']
        media = path + '/clips/' + clip_id + '/media'
        assert api.get(media).headers['content-type'] == 'video/mp4'
        partial = api.get(media, headers={'Range': 'bytes=0-99'})
        assert partial.status_code == 206
        assert partial.content == original[:100]
        assert 'attachment' in api.get(media + '?download=true').headers['content-disposition']
        first = wait(api, path)  # Upload alone triggers the build.
        assert first['status'] == 'ready', first
        assert first['timeline']['anchor_id'] == clip_id
        assert first['timeline']['segments'][0]['clip_id'] == clip_id
        assert first['timeline']['output_true_peak_dbfs'] <= -1.9
        old = api.get(path + '/audio').content
        cached = root / first['id'] / (clip_id + '.wav')
        cache_time = cached.stat().st_mtime_ns
        second_audio = write_wav(tmp_path / 'b.wav', raw[20 * 16000:90 * 16000]).read_bytes()
        queued = upload(api, path, 'b.wav', second_audio).json()
        assert queued['playable'] and queued['mix_revision'] == first['mix_revision']
        assert api.get(path + '/audio').content == old
        assert api.post(path + '/process').status_code == 202
        assert api.get(path + '/audio', headers={'Range': 'bytes=0-99'}).content == old[:100]
        assert upload(api, path, 'during.wav', second_audio).status_code == 409
        assert api.delete(path).status_code == 409
        second = wait(api, path)
        assert second['status'] == 'ready', second
        assert second['mix_revision'] != first['mix_revision']
        assert second['timeline']['duration'] == pytest.approx(90, abs=.1)
        assert cached.stat().st_mtime_ns == cache_time
        assert not second['dirty']
        current = api.get(path + '/audio').content
        # A failed rebuild must not overwrite the current result.
        for clip in second['clips']:
            api.patch(path + '/clips/' + clip['id'], json={'included': False})
        upload(api, path, 'broken.wav', b'bad media')
        api.post(path + '/process')
        failed = wait(api, path)
        assert failed['status'] == 'failed'
        assert failed['playable'] and failed['mix_revision'] == second['mix_revision']
        assert api.get(path + '/audio').content == current
    with client(root) as api:
        assert api.get(path).json()['playable']
        assert api.get(path + '/audio').content == current
        assert api.get(media).content == original


def test_legacy_reference_excluded_and_automatic_uploads_coalesced(tmp_path):
    root = tmp_path / 'store'
    raw = music(80)
    recording = write_wav(tmp_path / 'recording.wav', raw[:40 * 16000]).read_bytes()
    with client(root) as api:
        path = create(api)
        legacy = upload(api, path, 'legacy.wav', write_wav(tmp_path / 'legacy.wav', raw).read_bytes(), 'reference').json()['clips'][0]
        upload(api, path, 'first.wav', recording)
        upload(api, path, 'second.wav', recording)
        assert len(api.app.state.store.pending) == 1
        result = wait(api, path)
        assert result['status'] == 'ready', result
        assert result['timeline']['duration'] == pytest.approx(40)
        assert result['timeline']['anchor_id'] != legacy['id']
        assert all(s['clip_id'] != legacy['id'] for s in result['timeline']['segments'])
        assert api.get(path + '/clips/' + legacy['id'] + '/media').status_code == 200


def test_interrupted_recovery_and_single_server_lock(tmp_path):
    store = Store(tmp_path)
    data = store.create('Interrupted')
    data.update(status='processing', playable=True, mix_file='mix-saved.wav')
    (store.directory(data['id']) / 'mix-saved.wav').write_bytes(b'previous audio')
    store.save(data)
    with pytest.raises(RuntimeError, match='already open'):
        Store(tmp_path)
    store.close()
    with client(tmp_path) as api:
        result = api.get('/crowd-set/sets/' + data['id']).json()
        assert result['status'] == 'queued'
        assert result['playable']
        assert api.get('/crowd-set/sets/' + data['id'] + '/audio').content == b'previous audio'


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
        assert recovered.list()[0]['status'] == 'queued'
        recovered.close()
    finally:
        if parent.poll() is None:
            parent.kill(); parent.wait()
        if worker_pid:
            try:
                os.killpg(worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_failed_publication_retains_pointer_and_queued_sets_are_serial(tmp_path, monkeypatch):
    raw = write_wav(tmp_path / 'source.wav', music(40)).read_bytes()
    with client(tmp_path / 'store') as api:
        first = create(api)
        second = create(api)
        upload(api, first, 'one.wav', raw)
        upload(api, second, 'two.wav', raw)
        assert len(api.app.state.store.pending) == 2
        assert wait(api, first)['status'] == 'ready'
        assert wait(api, second)['status'] == 'ready'
        saved = api.get(first).json()
        old = api.get(first + '/audio').content
        store = api.app.state.store
        real_save = store.save
        def fail_publish_once(data):
            if data.get('mix_revision') != saved['mix_revision'] and data['id'] == saved['id'] and data['status'] == 'ready':
                monkeypatch.setattr(store, 'save', real_save)
                raise OSError('Injected disk write failure')
            return real_save(data)
        monkeypatch.setattr(store, 'save', fail_publish_once)
        api.post(first + '/process')
        result = wait(api, first)
        assert result['status'] == 'failed'
        assert result['mix_revision'] == saved['mix_revision']
        assert api.get(first + '/audio').content == old
        assert store.active is None


def test_batch_completion_gates_one_build_and_retains_successes(tmp_path, monkeypatch):
    raw = write_wav(tmp_path / 'source.wav', music(40)).read_bytes()
    with client(tmp_path / 'store') as api:
        path = create(api)
        upload(api, path, 'first.wav', raw)
        previous = wait(api, path)
        old = api.get(path + '/audio').content
        store = api.app.state.store
        starts = []
        real_submit = store.pool.submit
        def counted_submit(function, set_id):
            starts.append(set_id)
            return real_submit(function, set_id)
        monkeypatch.setattr(store.pool, 'submit', counted_submit)
        batch = api.post(path + '/batches').json()['id']
        assert api.put(path + '/clips', params={'name': 'second.wav', 'batch_id': batch}, content=raw).status_code == 201
        time.sleep(4.1)  # Longer than the ordinary debounce: a slow batch must stay held.
        assert starts == [] and not store.pending and store.active is None
        assert api.get(path).json()['status'] == 'uploading'
        assert api.get(path + '/audio').content == old
        assert api.post(path + '/process').status_code == 409
        assert api.put(path + '/clips', params={'name': 'outside.wav'}, content=raw).status_code == 409
        assert api.put(path + '/clips', params={'name': 'empty.wav', 'batch_id': batch}, content=b'').status_code == 400
        assert api.put(path + '/clips', params={'name': 'third.wav', 'batch_id': batch}, content=raw).status_code == 201
        assert starts == []
        finished = api.post(path + '/batches/' + batch + '/finish')
        assert finished.status_code == 200 and finished.json()['status'] == 'queued'
        result = wait(api, path)
        assert result['status'] == 'ready' and len(result['clips']) == 3
        assert result['mix_revision'] != previous['mix_revision']
        assert starts == [result['id']]
        assert not list((tmp_path / 'store').rglob('*.part'))


def test_abandoned_batch_settles_successful_uploads(tmp_path):
    store = Store(tmp_path)
    try:
        data = store.create('Abandoned batch')
        batch = store.begin_batch(data['id'], 'alice')['id']
        with pytest.raises(HTTPException) as denied:
            store.finish_batch(data['id'], batch, 'bob')
        assert denied.value.status_code == 403
        clip, partial = store.begin_upload(data['id'], 'recording.wav', uploader='alice', batch_id=batch)
        partial.write_bytes(b'original bytes')
        store.batches[data['id']]['deadline'] = 0
        store.dispatch()
        assert data['id'] in store.batches  # An active upload never expires between chunks.
        store.finish_upload(data['id'], clip, partial, True)
        store.batches[data['id']]['deadline'] = 0
        store.dispatch()
        recovered = store.get(data['id'])
        assert recovered['status'] == 'queued' and len(recovered['clips']) == 1
        assert 'upload missing files again' in recovered['upload_notice']
        assert data['id'] not in store.batches and len(store.pending) == 1
    finally:
        store.close()
