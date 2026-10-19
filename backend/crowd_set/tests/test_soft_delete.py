from dataclasses import replace
import hashlib
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from crowd_set.app import create_app
from crowd_set.store import Store
from crowd_set.worker import write_json


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    value = Store(tmp_path)
    yield value
    value.close()


def add_clip(store, set_id, body=b'original', deleted_at=None):
    data = store.get(set_id)
    clip_id = uuid4().hex
    clip = {'id': clip_id, 'file': clip_id + '.mp4.upload', 'name': 'phone.mp4',
            'role': 'recording', 'included': True, 'bytes': len(body), 'kind': 'video',
            'expected_duration': 5, 'sha256': hashlib.sha256(body).hexdigest()}
    if store.blobs:
        clip['object_key'] = f'originals/{set_id}/{clip_id}/{clip["sha256"]}'
        store.originals.record_blob(clip['object_key'], len(body))
    else:
        store.originals.destination(set_id, clip).write_bytes(body)
    if deleted_at is not None:
        clip['deleted_at'] = deleted_at
        data.setdefault('deleted_clips', []).append(clip)
    else:
        data['clips'].append(clip)
    store.save(data)
    return clip


def cloud(store, remove):
    store.blobs = SimpleNamespace(remove=remove)
    store.originals.blobs = store.blobs


def test_remove_hides_original_and_last_cut_but_retains_bytes_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as api:
        store = api.app.state.store
        data = store.create('Soft deletion')
        clip = add_clip(store, data['id'])
        data = store.get(data['id'])
        data.update(soundtrack_clip_id=clip['id'], playable=True, video_playable=True, mix_revision='old',
                    mix_file='mix-old.wav', video_file='mix-old.mp4', timeline={'duration': 5},
                    previous_revision={'mix_revision': 'previous', 'playable': True})
        store.save(data)
        cached = store.directory(data['id']) / (clip['id'] + '.wav')
        cached.write_bytes(b'cached audio')
        path = '/crowd-set/sets/' + data['id']
        media = path + '/clips/' + clip['id'] + '/media'
        assert api.get(media).content == b'original'
        removed = api.delete(path + '/clips/' + clip['id'])
        assert removed.status_code == 200
        assert removed.json()['clips'] == []
        assert removed.json()['soundtrack_clip_id'] is None
        for response in (removed.json(), api.get(path).json(), api.get('/crowd-set/sets').json()[0]):
            assert 'deleted_clips' not in response
            assert not response['playable']
        assert api.get(media).status_code == 404
        assert api.get(path + '/video').status_code == 404
        assert api.get(path + '/audio?v=previous').status_code == 404
        assert api.patch(path + '/clips/' + clip['id'], json={'included': True}).status_code == 404
        assert api.put(path + '/soundtrack', json={'clip_id': clip['id']}).status_code == 400
        assert store.originals.path(data['id'], clip).read_bytes() == b'original'
        assert cached.read_bytes() == b'cached audio'
    recovered = Store(tmp_path)
    try:
        retained = recovered.get(data['id'])['deleted_clips'][0]
        assert retained['deleted_at'] > 0 and not retained.get('purged_at')
        assert recovered.originals.path(data['id'], retained).read_bytes() == b'original'
    finally:
        recovered.close()


def test_removed_upload_survives_session_expiry_and_can_be_uploaded_again(store, monkeypatch):
    monkeypatch.setattr('crowd_set.store.probe', lambda *args, **kwargs: 5)
    store.limits = replace(store.limits, recordings=1, set_seconds=5)
    data = store.create('Expiry')
    fingerprint = hashlib.sha256(b'original').hexdigest()
    session = store.prepare_session(data['id'], 'clip.mp4', 8, fingerprint)
    store.append_session(data['id'], session['id'], None, 0, b'original', fingerprint)
    saved = store.complete_session(data['id'], session['id'])
    clip = saved['clips'][0]
    store.edit_clip(data['id'], clip['id'], delete=True)
    interrupted = store.session(data['id'], session['id'])
    interrupted['state'] = 'uploading'
    store.save_session(interrupted)
    assert store.complete_session(data['id'], session['id'])['clips'] == []
    expired = store.session(data['id'], session['id'])
    expired['expires_at'] = 0
    store.save_session(expired)
    store.expire_sessions()
    assert store.originals.path(data['id'], clip).read_bytes() == b'original'
    assert store.originals.sessions() == []
    fresh = store.prepare_session(data['id'], 'clip.mp4', 8, fingerprint)
    assert fresh['id'] != session['id']
    store.append_session(data['id'], fresh['id'], None, 0, b'original', fingerprint)
    assert len(store.complete_session(data['id'], fresh['id'])['clips']) == 1
    assert len(store.get(data['id'])['deleted_clips']) == 1


def test_cloud_reclaims_oldest_only_on_pressure_and_counts_pending_uploads(store):
    removed = []
    cloud(store, lambda keys: removed.extend(keys))
    first, second = store.create('First'), store.create('Second')
    newer = add_clip(store, first['id'], b'newer', deleted_at=20)
    oldest = add_clip(store, second['id'], b'oldest', deleted_at=10)
    active = add_clip(store, first['id'], b'active')
    current = f'mixes/{first["id"]}/current.mp4'
    previous = f'mixes/{first["id"]}/previous.mp4'
    for key in (current, previous):
        store.originals.record_blob(key, 3)
    # 23 bytes stored. The first reservation fits exactly; a second needs reclamation.
    store.limits = replace(store.limits, original_bytes=26)
    store.prepare_session(first['id'], 'one.mp4', 3, '1' * 64)
    assert removed == [] and store.originals.usage()[0] == 23
    store.prepare_session(first['id'], 'two.mp4', 4, '2' * 64)
    assert removed == [oldest['object_key']]
    assert store.get(second['id'])['deleted_clips'][0]['purged_at'] > 0
    assert not store.get(first['id'])['deleted_clips'][0].get('purged_at')
    assert store.originals.usage()[0] == 17
    assert all(key not in removed for key in (newer['object_key'], active['object_key'], current, previous))


def test_failed_cloud_cleanup_keeps_reservation_and_retries(store):
    removed = []
    def fail(keys):
        raise httpx.ReadError('Lost delete acknowledgment')
    cloud(store, fail)
    data = store.create('Retry cleanup')
    clip = add_clip(store, data['id'], b'original', deleted_at=10)
    store.limits = replace(store.limits, original_bytes=8)
    with pytest.raises(HTTPException) as error:
        store.prepare_session(data['id'], 'next.mp4', 1, '1' * 64)
    assert error.value.status_code == 503
    assert store.originals.usage()[0] == 8
    assert not store.originals.sessions()
    assert not store.get(data['id'])['deleted_clips'][0].get('purged_at')
    store.blobs.remove = lambda keys: removed.extend(keys)
    store.prepare_session(data['id'], 'next.mp4', 1, '1' * 64)
    assert removed == [clip['object_key']]
    assert store.originals.usage()[0] == 0


def test_publication_reclaims_removed_original_without_touching_current_mix(store, monkeypatch):
    removed, uploaded = [], []
    cloud(store, lambda keys: removed.extend(keys))
    store.blobs.put = lambda path, key, mime: uploaded.append(key)
    monkeypatch.setattr('crowd_set.store.subprocess.Popen', lambda *args, **kwargs: SimpleNamespace(wait=lambda **kwargs: 0, poll=lambda: 0))
    data = store.create('Publication')
    clip = add_clip(store, data['id'], b'removed', deleted_at=10)
    data = store.get(data['id'])
    current = f'mixes/{data["id"]}/current.wav'
    data.update(status='processing', playable=True, mix_file='mix-current.wav', mix_object=current, mix_bytes=4)
    store.save(data)
    store.originals.record_blob(current, 4)
    folder = store.directory(data['id'])
    (folder / 'mix-current.wav').write_bytes(b'old!')
    (folder / 'pending.wav').write_bytes(b'new!')
    write_json(folder / 'result.json', {'playable': True, 'clips': [], 'timeline': {}})
    store.limits = replace(store.limits, original_bytes=11)
    store.run(data['id'])
    saved = store.get(data['id'])
    assert saved['status'] == 'ready', saved.get('error')
    assert saved['deleted_clips'][0]['purged_at'] > 0
    assert removed == [clip['object_key']]
    assert saved['previous_revision']['mix_object'] == current
    assert saved['mix_object'] == uploaded[0]
    assert store.originals.usage()[0] == 8


def test_full_set_deletion_cleans_retained_removed_originals(store):
    removed = []
    cloud(store, lambda keys: removed.extend(keys))
    data = store.create('Delete set')
    hidden = add_clip(store, data['id'], deleted_at=10)
    active = add_clip(store, data['id'])
    store.delete(data['id'])
    assert set(removed) == {hidden['object_key'], active['object_key']}
    assert store.originals.usage()[0] == 0


def test_remove_queues_replacement_and_worker_receives_only_remaining_clips(store, monkeypatch):
    data = store.create('Cut without the removed clip')
    official = add_clip(store, data['id'])
    friend = add_clip(store, data['id'])
    data = store.get(data['id'])
    data.update(playable=True, mix_revision='published', soundtrack_clip_id=official['id'])
    store.save(data)
    changed = store.edit_clip(data['id'], friend['id'], delete=True)
    assert changed['status'] == 'queued' and changed['playable']
    assert changed['mix_revision'] == 'published'
    assert changed['soundtrack_clip_id'] == official['id']
    monkeypatch.setattr(store.pool, 'submit', lambda *args: None)
    store.start(data['id'])
    import json
    job = json.loads((store.directory(data['id']) / 'job.json').read_text())
    assert [clip['id'] for clip in job['clips']] == [official['id']]
    assert store.originals.path(data['id'], friend).exists()


def test_local_reclamation_persists_tombstone_and_removes_cache(store):
    data = store.create('Local pressure')
    clip = add_clip(store, data['id'], b'original', deleted_at=10)
    cached = store.directory(data['id']) / (clip['id'] + '.wav')
    cached.write_bytes(b'cached audio')
    store.limits = replace(store.limits, original_bytes=10, file_bytes=5)
    store.begin_upload(data['id'], 'new.mp4')
    assert store.get(data['id'])['deleted_clips'][0]['purged_at'] > 0
    assert not cached.exists()
    assert not store.originals.path(data['id'], clip).exists()


def test_no_reclamation_for_disk_or_work_failure_and_no_active_original_eviction(store, monkeypatch):
    removed = []
    cloud(store, lambda keys: removed.extend(keys))
    data = store.create('Guards')
    deleted = add_clip(store, data['id'], b'deleted', deleted_at=10)
    active = add_clip(store, data['id'], b'active')
    store.limits = replace(store.limits, original_bytes=13)
    with pytest.raises(HTTPException, match='Processing storage is full'):
        store.originals.admit(store.limits, incoming=1, work_needed=store.limits.work_bytes + 1,
                              reclaim=store.reclaim_deleted)
    with monkeypatch.context() as context:
        context.setattr('crowd_set.storage.shutil.disk_usage', lambda root: SimpleNamespace(free=0))
        with pytest.raises(HTTPException, match='server is low on storage'):
            store.prepare_session(data['id'], 'next.mp4', 1, '1' * 64)
    assert removed == []
    with pytest.raises(HTTPException, match='Recording storage is full'):
        store.prepare_session(data['id'], 'too-big.mp4', 10, '2' * 64)
    assert removed == [deleted['object_key']]
    assert store.get(data['id'])['clips'][0]['id'] == active['id']
    assert store.originals.usage()[0] == 6
    assert store.originals.sessions() == []


def test_soft_delete_does_not_call_cloud_cleanup_or_release_storage(store):
    removed = []
    cloud(store, lambda keys: removed.extend(keys))
    data = store.create('Cloud retention')
    clip = add_clip(store, data['id'])
    store.edit_clip(data['id'], clip['id'], delete=True)
    assert removed == []
    assert store.originals.usage()[0] == clip['bytes']
    retained = store.get(data['id'])['deleted_clips'][0]
    assert retained['object_key'] == clip['object_key'] and retained['sha256'] == clip['sha256']


def test_reupload_skips_interrupted_completed_session_for_removed_clip(store, monkeypatch):
    monkeypatch.setattr('crowd_set.store.probe', lambda *args, **kwargs: 5)
    store.limits = replace(store.limits, recordings=1)
    data = store.create('Interrupted completion')
    fingerprint = hashlib.sha256(b'original').hexdigest()
    session = store.prepare_session(data['id'], 'clip.mp4', 8, fingerprint)
    store.append_session(data['id'], session['id'], None, 0, b'original', fingerprint)
    saved = store.complete_session(data['id'], session['id'])
    store.edit_clip(data['id'], saved['clips'][0]['id'], delete=True)
    interrupted = store.session(data['id'], session['id'])
    interrupted['state'] = 'uploading'
    store.save_session(interrupted)
    fresh = store.prepare_session(data['id'], 'clip.mp4', 8, fingerprint)
    assert fresh['id'] != session['id']
    assert store.complete_session(data['id'], session['id'])['clips'] == []
