import hashlib
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from crowd_set.app import create_app
from crowd_set.blobs import BlobError, SupabaseBlobs


def provider(handler):
    return SupabaseBlobs('https://project.supabase.co', 'server-test-key', 'crowd-set-media', transport=httpx.MockTransport(handler))


def test_resumable_cloud_transfer_recovers_lost_acknowledgment(tmp_path):
    body = b'a' * (6 * 1024 * 1024) + b'last chunk'
    path = tmp_path / 'original'
    path.write_bytes(body)
    state = {'body': bytearray(), 'fail': True, 'posts': 0}

    def handler(request):
        assert request.headers['apikey'] == 'server-test-key'
        if '/object/authenticated/' in request.url.path:
            return httpx.Response(200, headers={'Content-Length': str(len(body))}) if len(state['body']) == len(body) else httpx.Response(404)
        if request.method == 'POST':
            state['posts'] += 1
            return httpx.Response(201, headers={'Location': '/storage/v1/upload/resumable/one'})
        if request.method == 'HEAD':
            return httpx.Response(200, headers={'Upload-Offset': str(len(state['body']))})
        assert request.method == 'PATCH'
        assert int(request.headers['upload-offset']) == len(state['body'])
        state['body'].extend(request.content)
        if state['fail']:
            state['fail'] = False
            raise httpx.ReadError('Lost acknowledgment')
        return httpx.Response(204, headers={'Upload-Offset': str(len(state['body']))})

    blobs = provider(handler)
    with pytest.raises(httpx.ReadError):
        blobs.put(path, 'originals/set/clip/hash')
    blobs.put(path, 'originals/set/clip/hash')
    assert bytes(state['body']) == body
    assert state['posts'] == 1
    assert not path.with_name('original.transfer.json').exists()
    assert path.read_bytes() == body


def test_cloud_download_checks_size_and_hash_and_preserves_bytes(tmp_path):
    body = b'original bytes'
    blobs = provider(lambda request: httpx.Response(200, content=body))
    output = tmp_path / 'copy'
    assert blobs.materialize('originals/set/clip/hash', output, len(body), hashlib.sha256(body).hexdigest()).read_bytes() == body
    with pytest.raises(BlobError, match='integrity'):
        blobs.materialize('originals/set/clip/hash', tmp_path / 'bad', len(body), '0' * 64)
    assert not (tmp_path / 'bad').exists()
    assert not (tmp_path / 'bad.download').exists()


def test_cloud_bucket_must_be_private_and_upload_location_same_project(tmp_path):
    blobs = provider(lambda request: httpx.Response(200, json={'public': True}))
    with pytest.raises(BlobError, match='private'):
        blobs.check_bucket(100)
    with pytest.raises(BlobError, match='invalid transfer location'):
        blobs.validate_location('https://evil.example/storage/v1/upload/resumable/stolen')
    with pytest.raises(ValueError):
        SupabaseBlobs('http://evil.example', 'server-test-key', 'private')
    with pytest.raises(ValueError):
        SupabaseBlobs('https://project.supabase.co', 'sb_publishable_public', 'private')


def test_authenticated_app_proxies_cloud_ranges_without_secret_in_urls(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        assert 'server-test-key' not in str(request.url)
        if '/bucket/' in request.url.path:
            return httpx.Response(200, json={'public': False, 'file_size_limit': 2 * 1024 ** 3})
        assert request.headers['Range'] == 'bytes=1-3'
        return httpx.Response(206, content=b'bcd', headers={'Content-Range': 'bytes 1-3/6', 'Accept-Ranges': 'bytes'})

    blobs = provider(handler)
    monkeypatch.setattr(SupabaseBlobs, 'environment', lambda: blobs)
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as api:
        item = api.post('/crowd-set/sets', json={'name': 'Cloud'}).json()
        store = api.app.state.store
        data = store.get(item['id'])
        data['clips'].append({'id': '1' * 32, 'name': 'Original.mov', 'role': 'recording', 'included': True, 'uploader': None,
                              'file': 'original.mov.upload', 'object_key': 'originals/set/clip/hash', 'bytes': 6, 'sha256': 'a' * 64})
        store.save(data)
        response = api.get(f'/crowd-set/sets/{item["id"]}/clips/{"1" * 32}/media', headers={'Range': 'bytes=1-3'})
        assert response.status_code == 206
        assert response.content == b'bcd'
        assert response.headers['content-type'] == 'video/quicktime'
        assert response.headers['content-range'] == 'bytes 1-3/6'
        assert 'server-test-key' not in response.text


def test_blob_ledger_counts_unpublished_objects_for_quota(tmp_path):
    from crowd_set.storage import OriginalStore
    store = OriginalStore(tmp_path, provider(lambda request: httpx.Response(200)))
    store.record_blob('mixes/set/pending.wav', 200)
    assert store.usage()[0] == 200
    store.remove_blobs(['mixes/set/pending.wav'])
    assert store.usage()[0] == 0


def test_cloud_publication_quota_and_generation_cleanup(tmp_path, monkeypatch):
    from dataclasses import replace
    from types import SimpleNamespace
    from crowd_set.store import Store
    from crowd_set.worker import write_json

    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    store = Store(tmp_path)
    uploaded, removed = [], []
    store.blobs = SimpleNamespace(put=lambda path, key, content_type: uploaded.append(key), remove=lambda keys: removed.extend(keys))
    store.originals.blobs = store.blobs
    monkeypatch.setattr('crowd_set.store.subprocess.Popen', lambda *args, **kwargs: SimpleNamespace(wait=lambda **kwargs: 0, poll=lambda: 0))
    data = store.create('Cloud publication')
    folder = store.directory(data['id'])
    prefix = f'mixes/{data["id"]}/'
    current, previous, failed = [prefix + name + '.wav' for name in ('current', 'previous', 'failed')]
    data.update(status='processing', playable=True, mix_file='old.wav', mix_object=current, mix_bytes=4,
                previous_mix_object=previous, previous_mix_bytes=4)
    store.save(data)
    for key in (current, previous, failed):
        store.originals.record_blob(key, 4)
    (folder / 'old.wav').write_bytes(b'old!')
    (folder / 'pending.wav').write_bytes(b'new!')
    write_json(folder / 'result.json', {'playable': True, 'clips': [], 'timeline': {}})
    store.limits = replace(store.limits, original_bytes=11)
    try:
        store.run(data['id'])
        saved = store.get(data['id'])
        assert saved['status'] == 'failed'
        assert saved['mix_object'] == current
        assert 'storage is full' in saved['error']
        assert uploaded == []
        assert failed in removed and current not in removed and previous not in removed
        store.limits = replace(store.limits, original_bytes=100)
        (folder / 'pending.wav').write_bytes(b'new!')
        store.run(data['id'])
        saved = store.get(data['id'])
        assert saved['status'] == 'ready'
        assert saved['previous_mix_object'] == current
        assert saved['mix_object'] == uploaded[0]
        assert previous in removed and current not in removed and uploaded[0] not in removed
        assert store.originals.usage()[0] == 8
        with pytest.raises(Exception, match='Reload Crowd Set'):
            store.begin_upload(data['id'], 'old-client.wav')
    finally:
        store.close()


def test_transfer_state_is_not_an_upload_session(tmp_path):
    from crowd_set.storage import OriginalStore
    store = OriginalStore(tmp_path)
    folder = store.session_directory('a' * 32)
    (folder / 'b.part.transfer.json').write_text('{"location":"https://example.test"}')
    assert store.sessions() == []


def test_cancel_and_expiry_reconcile_unpublished_originals(tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace
    from crowd_set.store import Store
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    store = Store(tmp_path)
    removed = []
    store.blobs = SimpleNamespace(remove=lambda keys: removed.extend(keys))
    store.originals.blobs = store.blobs
    try:
        data = store.create('Orphans')
        for expired in (False, True):
            session = store.prepare_session(data['id'], 'clip.wav', 100, ('a' if expired else 'b') * 64, 'alice')
            saved = store.session(data['id'], session['id'], 'alice')
            key = f'originals/{data["id"]}/{saved["clip"]["id"]}/hash'
            store.originals.record_blob(key, 100)
            if expired:
                saved['expires_at'] = time.time() - 1
                store.save_session(saved)
                store.expire_sessions()
            else:
                store.cancel_session(data['id'], session['id'], 'alice')
            assert key in removed
            assert store.originals.usage()[0] == 0
            assert not store.originals.sessions()
    finally:
        store.close()


def test_cloud_staging_and_object_reservation_count_once(tmp_path):
    from crowd_set.storage import OriginalStore
    from crowd_set.worker import write_json
    store = OriginalStore(tmp_path, provider(lambda request: httpx.Response(200)))
    folder = store.session_directory('set')
    (folder / 'session.part').write_bytes(b'abc')
    write_json(folder / 'session.json', {'id': 'session', 'set_id': 'set', 'clip': {'id': 'clip'}, 'state': 'uploading', 'size': 3, 'offset': 3})
    store.record_blob('originals/set/clip/hash', 3)
    assert store.usage()[0] == 3
    assert (folder / 'session.part').read_bytes() == b'abc'


@pytest.mark.parametrize('failure', ['video_upload', 'metadata_save'])
def test_paired_publication_failure_preserves_entire_revision(tmp_path, monkeypatch, failure):
    from types import SimpleNamespace
    from crowd_set.store import Store
    from crowd_set.worker import write_json
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    store = Store(tmp_path)
    uploaded, removed = [], []

    def put(path, key, mime):
        uploaded.append(key)
        if failure == 'video_upload' and mime == 'video/mp4':
            raise BlobError('simulated second artifact failure')

    store.blobs = SimpleNamespace(put=put, remove=lambda keys: removed.extend(keys))
    store.originals.blobs = store.blobs
    monkeypatch.setattr('crowd_set.store.subprocess.Popen', lambda *args, **kwargs: SimpleNamespace(wait=lambda **kwargs: 0, poll=lambda: 0))
    data = store.create('Paired publication')
    prefix = f'mixes/{data["id"]}/'
    data.update(status='processing', playable=True, video_playable=True, mix_revision='old',
                mix_file='mix-old.wav', video_file='mix-old.mp4', mix_object=prefix+'old.wav', video_object=prefix+'old.mp4',
                timeline={'old': 'audio'}, video_timeline={'old': 'video'})
    store.save(data)
    folder = store.directory(data['id'])
    for suffix in ('wav', 'mp4'):
        (folder / f'mix-old.{suffix}').write_bytes(b'old!')
        (folder / f'pending.{suffix}').write_bytes(b'new!')
        store.originals.record_blob(prefix + f'old.{suffix}', 4)
    write_json(folder / 'result.json', {'playable': True, 'video_playable': True, 'clips': [], 'timeline': {'new': 'audio'}, 'video_timeline': {'new': 'video'}})
    original_save = store.save

    def save(value):
        if failure == 'metadata_save' and value['status'] == 'ready':
            raise OSError('simulated atomic save failure')
        return original_save(value)

    monkeypatch.setattr(store, 'save', save)
    try:
        store.run(data['id'])
        saved = store.get(data['id'])
        assert saved['status'] == 'failed'
        for key in ('mix_revision', 'mix_file', 'video_file', 'mix_object', 'video_object', 'timeline', 'video_timeline'):
            assert saved[key] == data[key]
        assert len(uploaded) == 2
        assert set(uploaded) <= set(removed)
        assert prefix+'old.wav' not in removed and prefix+'old.mp4' not in removed
        assert store.originals.usage()[0] == 8
    finally:
        store.close()
