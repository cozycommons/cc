import hashlib

from fastapi.testclient import TestClient

from crowdset.app import create_app
from crowdset.store import Store
from crowdset import video
from crowdset.tests.test_audio import music, write_wav
from crowdset.tests.test_video import make_video


def test_same_bytes_renamed_or_uploaded_by_friend_reuse_active_clip(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    monkeypatch.setattr('crowdset.store.probe', lambda *args, **kwargs: 2)
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as api:
        store = api.app.state.store
        data = store.create('Duplicates', owner='alice')
        body = b'the same original bytes'
        original = None
        for index, owner in enumerate(('alice', 'bob')):
            session = store.prepare_session(data['id'], f'renamed-{index}.wav', len(body), f'{index:064x}', owner)
            store.append_session(data['id'], session['id'], owner, 0, body, hashlib.sha256(body).hexdigest())
            if index:
                # No additional R2 writes, thumbnail work, or processing for a duplicate.
                monkeypatch.setattr(store.originals, 'publish', lambda *args: (_ for _ in ()).throw(AssertionError('republished')))
                monkeypatch.setattr(store, 'queue', lambda *args: (_ for _ in ()).throw(AssertionError('queued')))
            result = store.complete_session(data['id'], session['id'], owner)
            assert len(result['clips']) == 1
            if index:
                assert result['duplicate_clip_id'] == original['id']
                assert result['clips'][0]['uploader'] == 'alice'
                assert store.complete_session(data['id'], session['id'], owner)['duplicate_clip_id'] == original['id']
                assert not (store.originals.session_directory(data['id']) / f'{session["id"]}.part').exists()
            else:
                original = result['clips'][0]
            current = store.get(data['id'])
            current.update(status='idle', dirty=False)
            store.save(current)
        assert store.originals.path(data['id'], original).read_bytes() == body
        assert 'duplicate_clip_id' not in store.get(data['id'])


def test_legacy_upload_dedupes_and_deleted_clip_can_be_reuploaded(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as api:
        store = api.app.state.store
        data = store.create('Legacy')
        ids = []
        for index in range(3):
            clip, partial = store.begin_upload(data['id'], f'{index}.mp4')
            partial.write_bytes(b'original')
            result = store.finish_upload(data['id'], clip, partial, True)
            ids.append(result['clips'][0]['id'])
            current = store.get(data['id'])
            current.update(status='idle', dirty=False)
            if index == 1:
                current['deleted_clips'] = current['clips']
                current['clips'] = []
            store.save(current)
        assert ids[0] == ids[1] != ids[2]
        assert len(store.get(data['id'])['deleted_clips']) == 1


def test_small_jpeg_preview_generated_on_publish_and_hidden_after_soft_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    source = make_video(tmp_path / 'phone.mov', write_wav(tmp_path / 'audio.wav', music(1)))
    with TestClient(create_app(tmp_path / 'data'), base_url='http://127.0.0.1') as api:
        store = api.app.state.store
        data = store.create('Preview')
        clip, partial = store.begin_upload(data['id'], 'phone.mov')
        partial.write_bytes(source.read_bytes())
        store.finish_upload(data['id'], clip, partial, True)
        path = f'/crowdset/sets/{data["id"]}/clips/{clip["id"]}/thumbnail'
        response = api.get(path)
        assert response.status_code == 200
        assert response.headers['content-type'] == 'image/jpeg'
        assert response.content.startswith(b'\xff\xd8') and len(response.content) < 100_000
        current = store.get(data['id'])
        current.update(status='idle', dirty=False)
        store.save(current)
        api.delete(f'/crowdset/sets/{data["id"]}/clips/{clip["id"]}')
        assert api.get(path).status_code == 404
        assert (store.directory(data['id']) / f'{clip["id"]}.jpg').exists()


def test_preview_failure_does_not_fail_original_upload(tmp_path, monkeypatch):
    def failed(*args):
        raise ValueError('unsupported picture')
    monkeypatch.setattr(video, 'run', failed)
    video.thumbnail(tmp_path / 'source', tmp_path / 'preview.jpg')
    assert not list(tmp_path.glob('*.jpg'))
