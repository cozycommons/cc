from dataclasses import replace
import hashlib
import json
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from crowdset.app import create_app
from crowdset.limits import Limits, MIB, GIB
from crowdset.store import Store
from crowdset.tests.test_audio import music, write_wav


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    value = Store(tmp_path)
    yield value
    value.close()


def start(store, data, body, owner='alice', batch=None, fingerprint=None):
    return store.prepare_session(data['id'], 'clip.wav', len(body), fingerprint or hashlib.sha256(body).hexdigest(), owner, batch)


def append(store, data, session, body, owner='alice', offset=0):
    return store.append_session(data['id'], session['id'], owner, offset, body, hashlib.sha256(body).hexdigest())


def test_fifty_friends_and_released_recording_admitted_and_persisted(store, tmp_path):
    data = store.create('Many friends', owner='alice')
    batch = store.begin_batch(data['id'], 'alice')['id']
    for index in range(51):
        audio = write_wav(tmp_path / 'input.wav', music(2) * (1 - index / 100)).read_bytes()
        session = start(store, data, audio, batch=batch, fingerprint=f'{index:064x}')
        append(store, data, session, audio)
        saved = store.complete_session(data['id'], session['id'], 'alice')
        assert saved['status'] == 'uploading'
        assert len(saved['clips']) == index + 1
    result = store.finish_batch(data['id'], batch, 'alice')
    assert result['status'] == 'queued'
    assert len(result['clips']) == 51
    assert len(store.pending) == 1
    assert len({clip['sha256'] for clip in result['clips']}) == 51
    assert all(store.originals.path(data['id'], clip).exists() for clip in result['clips'])


def test_resume_committed_offset_after_restart_and_idempotent_finish(store, tmp_path, monkeypatch):
    data = store.create('Restart')
    session = start(store, data, b'abcde')
    append(store, data, session, b'abc')
    partial = store.originals.uploads / data['id'] / f'{session["id"]}.part'
    with partial.open('ab') as output:
        output.write(b'uncommitted tail')
    store.close()
    monkeypatch.setattr('crowdset.store.probe', lambda *args, **kwargs: 2)
    recovered = Store(tmp_path)
    try:
        assert partial.read_bytes() == b'abc'
        assert recovered.session(data['id'], session['id'], 'alice')['offset'] == 3
        append(recovered, data, session, b'de', offset=3)
        first = recovered.complete_session(data['id'], session['id'], 'alice')
        second = recovered.complete_session(data['id'], session['id'], 'alice')
        assert len(first['clips']) == len(second['clips']) == 1
        assert recovered.originals.path(data['id'], first['clips'][0]).read_bytes() == b'abcde'
        assert start(recovered, data, b'abcde')['state'] == 'complete'
    finally:
        recovered.close()


def test_checksum_offset_owner_and_batch_guards(store):
    data = store.create('Protected')
    batch = store.begin_batch(data['id'], 'alice')['id']
    session = start(store, data, b'abcdef', batch=batch)
    with pytest.raises(HTTPException) as failure:
        append(store, data, session, b'ab', owner='bob')
    assert failure.value.status_code == 403
    with pytest.raises(HTTPException) as failure:
        store.append_session(data['id'], session['id'], 'alice', 0, b'ab', '0' * 64)
    assert failure.value.status_code == 422
    assert append(store, data, session, b'ab')['offset'] == 2
    assert append(store, data, session, b'ab')['offset'] == 2
    with pytest.raises(HTTPException) as failure:
        append(store, data, session, b'xy')
    assert failure.value.status_code == 409
    with pytest.raises(HTTPException):
        store.begin_batch(data['id'], 'bob')
    with pytest.raises(HTTPException):
        store.cancel_session(data['id'], session['id'], 'bob')


def test_pending_count_and_byte_reservations_are_enforced(store):
    store.limits = replace(store.limits, recordings=2, original_bytes=10)
    data = store.create('Quota')
    start(store, data, b'123456')
    with pytest.raises(HTTPException) as failure:
        start(store, data, b'abcdef')
    assert failure.value.status_code == 507
    start(store, data, b'x')
    with pytest.raises(HTTPException) as failure:
        start(store, data, b'y')
    assert failure.value.status_code == 409


def test_physical_free_floor_and_generated_quota(store, monkeypatch):
    data = store.create('Disk')
    monkeypatch.setattr('crowdset.storage.shutil.disk_usage', lambda path: type('Disk', (), {'free': 1})())
    with pytest.raises(HTTPException) as failure:
        start(store, data, b'x')
    assert failure.value.status_code == 507
    monkeypatch.setattr('crowdset.storage.shutil.disk_usage', lambda path: type('Disk', (), {'free': 100 * 1024 ** 3})())
    with pytest.raises(HTTPException) as failure:
        store.originals.admit(store.limits, work_needed=store.limits.work_bytes + 1)
    assert failure.value.status_code == 507


def test_large_original_admission_retains_r2_and_physical_caps(store, monkeypatch):
    monkeypatch.setenv('CROWDSET_STORAGE_PROVIDER', 'r2')
    store.limits = Limits.environment()
    assert store.limits.original_bytes == 8_000_000_000
    assert 3 * store.limits.file_bytes + MIB < store.limits.work_bytes
    monkeypatch.setattr('crowdset.storage.shutil.disk_usage', lambda path: type('Disk', (), {'free': 20 * GIB})())
    data = store.create('Full performance')
    session = store.prepare_session(data['id'], 'Full performance.mp4', 3_165_006_590, 'a' * 64, 'alice')
    assert session['size'] == 3_165_006_590
    with pytest.raises(HTTPException) as failure:
        store.originals.admit(store.limits, incoming=5_000_000_000)
    assert failure.value.status_code == 507
    with pytest.raises(HTTPException) as failure:
        store.prepare_session(data['id'], 'Too large.mov', 3 * GIB + 1, 'b' * 64, 'alice')
    assert failure.value.status_code == 413


def test_remote_recording_limit_uses_worker_capacity_without_raising_storage_budget(monkeypatch):
    monkeypatch.setenv('CROWDSET_STORAGE_PROVIDER', 'r2')
    monkeypatch.setenv('CROWDSET_REMOTE_WORKER', '1')
    limits = Limits.environment()
    assert limits.file_bytes == 8 * GIB
    assert limits.original_bytes == 8_000_000_000
    assert limits.work_bytes == 10 * GIB
    monkeypatch.setenv('CROWDSET_MAX_FILE_BYTES', str(8 * GIB + 1))
    with pytest.raises(ValueError, match='MAX_FILE_BYTES'):
        Limits.environment()


def test_local_r2_recording_limit_stays_bounded_by_local_working_space(monkeypatch):
    monkeypatch.setenv('CROWDSET_STORAGE_PROVIDER', 'r2')
    monkeypatch.setenv('CROWDSET_REMOTE_WORKER', '0')
    assert Limits.environment().file_bytes == 3 * GIB
    monkeypatch.setenv('CROWDSET_MAX_FILE_BYTES', str(3 * GIB + 1))
    with pytest.raises(ValueError, match='MAX_FILE_BYTES'):
        Limits.environment()


def test_durable_batch_resumes_and_job_recovery_is_bounded(store, tmp_path):
    data = store.create('Recovery')
    batch = store.begin_batch(data['id'], 'alice')['id']
    store.close()
    recovered = Store(tmp_path)
    assert recovered.begin_batch(data['id'], 'alice')['id'] == batch
    recovered.finish_batch(data['id'], batch, 'alice')
    data = recovered.get(data['id'])
    data.update(status='processing', recovery_attempts=2)
    recovered.save(data)
    recovered.close()
    last = Store(tmp_path)
    try:
        result = last.get(data['id'])
        assert result['status'] == 'failed'
        assert 'repeatedly' in result['error']
        assert not last.pending
    finally:
        last.close()


def test_expired_session_reclaims_reservation(store):
    data = store.create('Expiry')
    session = start(store, data, b'abc')
    append(store, data, session, b'a')
    stored = store.session(data['id'], session['id'], 'alice')
    stored['expires_at'] = time.time() - 1
    store.save_session(stored)
    store.expire_sessions()
    assert not store.originals.sessions()
    assert not list(store.originals.uploads.glob('*/*.part'))


def test_resumable_api_and_server_limits(tmp_path):
    audio = write_wav(tmp_path / 'input.wav', music(2)).read_bytes()
    with TestClient(create_app(tmp_path / 'store'), base_url='http://127.0.0.1') as api:
        limits = api.get('/crowdset/sets?limits=true').json()
        assert limits['recordings'] >= 51
        assert limits['resumable_uploads']
        item = api.post('/crowdset/sets', json={'name': 'API'}).json()
        path = f'/crowdset/sets/{item["id"]}'
        session = api.post(path + '/uploads', json={'name': 'recording.wav', 'size': len(audio), 'fingerprint': hashlib.sha256(audio).hexdigest()}).json()
        upload = path + '/uploads/' + session['id']
        assert api.post(upload + '/finish').status_code == 409
        saved = api.patch(upload, params={'offset': 0, 'checksum': hashlib.sha256(audio).hexdigest()}, content=audio)
        assert saved.json()['offset'] == len(audio)
        completed = api.post(upload + '/finish')
        assert completed.status_code == 200
        assert len(api.post(upload + '/finish').json()['clips']) == 1
        clip = completed.json()['clips'][0]
        media = path + '/clips/' + clip['id'] + '/media'
        assert api.get(media).content == audio
        assert api.get(media, headers={'Range': 'bytes=0-99'}).status_code == 206


def test_duration_budget_retains_partial_and_previous_mix(store, monkeypatch):
    store.limits = replace(store.limits, set_seconds=5)
    data = store.create('Duration')
    data.update(playable=True, mix_file='old.wav')
    store.save(data)
    session = start(store, data, b'abc')
    append(store, data, session, b'abc')
    monkeypatch.setattr('crowdset.store.probe', lambda *args, **kwargs: 6)
    with pytest.raises(HTTPException) as failure:
        store.complete_session(data['id'], session['id'], 'alice')
    assert failure.value.status_code == 413
    assert store.get(data['id'])['mix_file'] == 'old.wav'
    assert store.session(data['id'], session['id'], 'alice')['offset'] == 3
    assert store.upload is None


def test_batch_completion_reply_can_be_retried_after_restart(store, tmp_path):
    data = store.create('Batch retry')
    batch = store.begin_batch(data['id'], 'alice')['id']
    first = store.finish_batch(data['id'], batch, 'alice')
    assert store.finish_batch(data['id'], batch, 'alice') == first
    with pytest.raises(HTTPException):
        store.finish_batch(data['id'], batch, 'bob')
    store.close()
    recovered = Store(tmp_path)
    try:
        assert recovered.finish_batch(data['id'], batch, 'alice') == first
    finally:
        recovered.close()


def test_slow_chunk_holds_batch_until_body_is_saved(store):
    data = store.create('Slow body')
    batch = store.begin_batch(data['id'], 'alice')['id']
    session = start(store, data, b'abc', batch=batch)
    store.begin_chunk(data['id'], session['id'], 'alice')
    store.batches[data['id']]['deadline'] = time.monotonic() - 1
    store.dispatch()
    assert store.batches[data['id']]['id'] == batch
    append(store, data, session, b'abc')
    store.end_chunk(data['id'], session['id'])
    assert store.batches[data['id']]['deadline'] > time.monotonic()


def test_recovery_attempts_survive_actual_job_start(store, tmp_path, monkeypatch):
    data = store.create('Bounded recovery')
    data.update(status='processing', clips=[{'id': 'a' * 32, 'role': 'recording', 'included': True}])
    store.save(data)
    store.close()
    for attempt in (1, 2):
        recovered = Store(tmp_path)
        monkeypatch.setattr(recovered.pool, 'submit', lambda *args: None)
        assert recovered.get(data['id'])['recovery_attempts'] == attempt
        recovered.start(data['id'])
        assert recovered.get(data['id'])['recovery_attempts'] == attempt
        recovered.close()
    last = Store(tmp_path)
    try:
        assert last.get(data['id'])['status'] == 'failed'
    finally:
        last.close()
