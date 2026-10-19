from contextlib import contextmanager
import json
import time
import wave

from fastapi import HTTPException
from fastapi.testclient import TestClient
import numpy as np
import pytest

from crowdset.app import create_app
from crowdset.store import Store
from crowdset.tests.test_audio import music, write_wav


@contextmanager
def client(root):
    with TestClient(create_app(root), base_url='http://127.0.0.1') as api:
        yield api


def create(api):
    result = api.post('/crowdset/sets', json={'name': 'Test performance'})
    assert result.status_code == 201
    return '/crowdset/sets/' + result.json()['id']


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
        assert api.get('/crowdset/sets', headers={'host': 'evil.example'}).status_code == 403
        assert api.get('/crowdset/sets', headers={'origin': 'https://evil.example'}).status_code == 403
        assert api.get('/crowdset/sets', headers={'origin': 'http://127.0.0.1:8083'}).status_code == 200
        assert api.post('/crowdset/sets', json={'name': '   '}).status_code == 422
        path = create(api)
        assert api.post(path + '/process').status_code == 400
        assert upload(api, path, 'playlist.m3u', b'bad').status_code == 415
        assert upload(api, path, 'empty.wav', b'').status_code == 400
        assert upload(api, path, 'x.wav', b'x', 'unknown').status_code == 422
        monkeypatch.setattr('crowdset.app.MAX_BYTES', 20)
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
        assert api.get('/crowdset/sets/not-a-uuid').status_code == 404


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
        assert first['video_playable']
        old_video = api.get(path + '/video').content
        assert api.get(path + '/video', headers={'Range': 'bytes=0-99'}).content == old_video[:100]
        assert 'attachment' in api.get(path + '/video?download=true').headers['content-disposition']
        old = api.get(path + '/audio').content
        cached = root / first['id'] / (clip_id + '.wav')
        cache_time = cached.stat().st_mtime_ns
        second_audio = write_wav(tmp_path / 'b.wav', raw[20 * 16000:90 * 16000]).read_bytes()
        from crowdset.tests.test_video import make_video, frame
        red = make_video(tmp_path / 'portrait.mp4', tmp_path / 'b.wav')
        queued = upload(api, path, 'portrait.mp4', red.read_bytes()).json()
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
        assert second['video_playable']
        assert len(second['video_timeline']['segments']) == 2
        assert api.get(path + '/video?v=' + first['mix_revision']).content == old_video
        assert api.get(path + '/audio?v=' + first['mix_revision']).content == old
        assert api.get(path + '/video?v=expired').status_code == 404
        current_video = api.get(path + '/video').content
        cut = tmp_path / 'published.mp4'
        cut.write_bytes(current_video)
        assert frame(cut, 30)[24, 42, 1] > 90
        assert frame(cut, 85)[24, 42, 0] > 200
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
        assert api.get(path + '/video').content == current_video
    with client(root) as api:
        assert api.get(path).json()['playable']
        assert api.get(path + '/audio').content == current
        assert api.get(path + '/video').content == current_video
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
        result = api.get('/crowdset/sets/' + data['id']).json()
        assert result['status'] == 'queued'
        assert result['playable']
        assert api.get('/crowdset/sets/' + data['id'] + '/audio').content == b'previous audio'


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
from crowdset.store import Store
root = pathlib.Path(sys.argv[1])
store = Store(root)
real_popen = subprocess.Popen
def paused_worker(command, **kwargs):
    replacement = [command[0], '-c', "import runpy,sys,time; time.sleep(2); sys.argv=['worker',sys.argv[1]]; runpy.run_module('crowdset.worker',run_name='__main__')", command[-1]]
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
        upload(api, first, 'longer.wav', write_wav(tmp_path / 'longer.wav', music(45)).read_bytes())
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
        assert api.put(path + '/clips', params={'name': 'second.wav', 'batch_id': batch}, content=raw + b'JUNK\x04\x00\x00\x00two!').status_code == 201
        time.sleep(4.1)  # Longer than the ordinary debounce: a slow batch must stay held.
        assert starts == [] and not store.pending and store.active is None
        assert api.get(path).json()['status'] == 'uploading'
        assert api.get(path + '/audio').content == old
        assert api.post(path + '/process').status_code == 409
        assert api.put(path + '/clips', params={'name': 'outside.wav'}, content=raw).status_code == 409
        assert api.put(path + '/clips', params={'name': 'empty.wav', 'batch_id': batch}, content=b'').status_code == 400
        assert api.put(path + '/clips', params={'name': 'third.wav', 'batch_id': batch}, content=raw + b'JUNK\x04\x00\x00\x00tri!').status_code == 201
        assert starts == []
        finished = api.post(path + '/batches/' + batch + '/finish')
        assert finished.status_code == 200 and finished.json()['status'] == 'queued'
        result = wait(api, path)
        assert result['status'] == 'ready' and len(result['clips']) == 3
        assert result['mix_revision'] == previous['mix_revision']
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


def test_event_metadata_roundtrip_midnight_and_legacy_compatibility(tmp_path):
    event = {'name': 'ISOKNOCK · Niteharts', 'artist': ' ISOKNOCK ', 'venue': 'Niteharts',
             'starts_at': '2026-10-18T23:30', 'ends_at': '2026-10-19T01:00', 'timezone': 'America/New_York'}
    with client(tmp_path) as api:
        assert api.get('/crowdset/sets?limits=true').json()['event_metadata']
        created = api.post('/crowdset/sets', json=event)
        assert created.status_code == 201
        data = created.json()
        assert data['artist'] == 'ISOKNOCK'
        assert data['starts_at'] == '2026-10-19T03:30:00+00:00'
        assert data['ends_at'] == '2026-10-19T05:00:00+00:00'
        assert data['timezone'] == 'America/New_York'
        assert api.get('/crowdset/sets').json()[0] == data
        legacy = create(api)
        assert 'artist' not in api.get(legacy).json()
    with client(tmp_path) as api:
        assert api.get('/crowdset/sets/' + data['id']).json() == data


@pytest.mark.parametrize('changes', [
    {'artist': None}, {'venue': '  '}, {'timezone': 'not/a-zone'},
    {'starts_at': '0001-01-01T00:00:00+01:00'},
    {'starts_at': '2026-10-19'}, {'starts_at': '1792380000'},
    {'ends_at': '2026-10-18T22:00'},
    {'starts_at': '2026-03-08T02:30', 'ends_at': '2026-03-08T04:00'},
    {'starts_at': '2026-11-01T01:30', 'ends_at': '2026-11-01T03:00'},
])
def test_invalid_or_uncertain_event_time_never_creates_set(tmp_path, changes):
    event = {'name': 'Event', 'artist': 'Artist', 'venue': 'Venue', 'starts_at': '2026-10-18T23:30',
             'ends_at': '2026-10-19T01:00', 'timezone': 'America/New_York', **changes}
    with client(tmp_path) as api:
        assert api.post('/crowdset/sets', json=event).status_code == 422
        assert api.get('/crowdset/sets').json() == []


def test_explicit_offset_disambiguates_dst_transition(tmp_path):
    with client(tmp_path) as api:
        response = api.post('/crowdset/sets', json={'name': 'Event', 'artist': 'Artist', 'venue': 'Venue',
            'starts_at': '2026-11-01T01:30:00-04:00', 'ends_at': '2026-11-01T01:30:00-05:00',
            'timezone': 'America/New_York'})
        assert response.status_code == 201
        assert response.json()['starts_at'] == '2026-11-01T05:30:00+00:00'
        assert response.json()['ends_at'] == '2026-11-01T06:30:00+00:00'


def test_legacy_audio_remains_pinned_after_modern_publication(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from crowdset.worker import write_json
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    monkeypatch.setattr('crowdset.store.subprocess.Popen', lambda *args, **kwargs: SimpleNamespace(wait=lambda **kwargs: 0, poll=lambda: 0))
    with client(tmp_path) as api:
        path = create(api)
        store = api.app.state.store
        data = api.get(path).json()
        data.update(playable=True)
        folder = store.directory(data['id'])
        (folder / 'reconstruction.wav').write_bytes(b'legacy audio')
        store.save(data)
        (folder / 'pending.wav').write_bytes(b'new audio')
        write_json(folder / 'result.json', {'playable': True, 'clips': [], 'timeline': {}})
        store.run(data['id'])
        assert api.get(path + '/audio?v=legacy').content == b'legacy audio'
        assert api.get(path + '/audio').content == b'new audio'
        assert (folder / 'reconstruction.wav').exists()


def test_contained_clip_updates_alignment_without_duplicate_video(tmp_path):
    from crowdset.tests.test_video import make_video
    raw = music(80)
    audio = write_wav(tmp_path / 'full.wav', raw)
    full = make_video(tmp_path / 'full.mp4', audio, size='160x90', duration=80)
    with client(tmp_path / 'store') as api:
        path = create(api)
        upload(api, path, 'full.mp4', full.read_bytes())
        first = wait(api, path)
        assert first['status'] == 'ready'
        original_video = api.get(path + '/video').content
        short = write_wav(tmp_path / 'short.wav', raw[20 * 16000:29 * 16000])
        upload(api, path, 'friend.wav', short.read_bytes())
        second = wait(api, path)
        assert second['status'] == 'ready', second
        assert len(second['clips']) == 2
        assert second['clips'][1]['alignment']['status'] == 'matched'
        assert second['clips'][1]['alignment']['offset_seconds'] == pytest.approx(20, abs=.1)
        assert second['mix_revision'] == first['mix_revision']
        assert second['video_file'] == first['video_file']
        assert api.get(path + '/video').content == original_video
        assert len(list((tmp_path / 'store' / second['id']).glob('mix-*.mp4'))) == 1
        assert not (tmp_path / 'store' / second['id'] / 'pending.wav').exists()

        folder = tmp_path / 'store' / second['id']
        recording = second['clips'][1]['id']
        alignment_cache = folder / (recording + '.alignment.json')
        old = json.loads(alignment_cache.read_text())
        old.update(version=1, alignment={'status': 'unmatched', 'windows': [], 'reason': 'Old minimum length'})
        alignment_cache.write_text(json.dumps(old))
        for metadata in folder.glob('*.analysis.json'):
            analysis = json.loads(metadata.read_text())
            analysis.pop('capture_version', None)
            analysis.pop('capture', None)
            metadata.write_text(json.dumps(analysis))
        preparation = {p: p.stat().st_mtime_ns for p in folder.iterdir() if p.suffix in ('.wav', '.npy')}
        assert api.post(path + '/process').status_code == 202
        third = wait(api, path)
        assert third['clips'][1]['alignment']['status'] == 'matched'
        assert json.loads(alignment_cache.read_text())['version'] == 2
        assert all(p.stat().st_mtime_ns == stamp for p, stamp in preparation.items())
        assert third['mix_revision'] == first['mix_revision']
        cache_time = alignment_cache.stat().st_mtime_ns
        assert api.post(path + '/process').status_code == 202
        assert wait(api, path)['status'] == 'ready'
        assert alignment_cache.stat().st_mtime_ns == cache_time


def test_worker_preserves_specific_storage_error(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = tmp_path / 'data'
    folder = root / ('a' * 32)
    folder.mkdir(parents=True)
    (folder / 'job.json').write_text(json.dumps({'id': folder.name, 'clips': []}))
    env = {key: value for key, value in os.environ.items() if not key.startswith('CROWDSET_')}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parents[2]), CROWDSET_WORK_BYTES=str(1024 ** 2))
    result = subprocess.run([sys.executable, '-m', 'crowdset.worker', str(folder)], env=env,
                            start_new_session=True, capture_output=True, timeout=15)
    assert result.returncode == 1
    assert json.loads((folder / 'failure.json').read_text())['error'].startswith('Processing storage is full.')
