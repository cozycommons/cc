from dataclasses import replace
import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from crowdset.app import create_app
from crowdset.limits import Limits
from crowdset.store import Store
from crowdset.tests.test_audio import music, write_wav
from crowdset.worker import write_json
from crowdset.youtube import FORMAT, canonical_url, validate_info

URL = 'https://www.youtube.com/watch?v=9dhFH_G5Bow'


@pytest.mark.parametrize('heights, expected', [([720, 1080, 2160], 1080), ([360, 720], 720)])
def test_download_selects_1080p_with_lower_resolution_fallback(heights, expected):
    import yt_dlp

    formats = [{'format_id': str(height), 'url': f'https://example.com/{height}.mp4',
                'height': height, 'width': height * 16 // 9, 'ext': 'mp4',
                'vcodec': 'avc1.640028', 'acodec': 'none'} for height in heights]
    formats.append({'format_id': 'audio', 'url': 'https://example.com/audio.m4a',
                    'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.2'})
    with yt_dlp.YoutubeDL({'format': FORMAT, 'quiet': True}) as downloader:
        result = downloader.process_ie_result({'id': 'test', 'title': 'Test', 'formats': formats}, download=False)
    assert result['requested_formats'][0]['height'] == expected
    assert result['requested_formats'][1]['format_id'] == 'audio'


@pytest.mark.parametrize('url', [
    'https://youtu.be/9dhFH_G5Bow?si=tracking',
    URL + '&list=ignored&t=90', 'https://m.youtube.com/watch?v=9dhFH_G5Bow',
    'https://www.youtube.com/shorts/9dhFH_G5Bow', 'https://youtube.com/live/9dhFH_G5Bow',
])
def test_canonical_single_video(url):
    assert canonical_url(url) == URL


@pytest.mark.parametrize('url', [
    'http://youtube.com/watch?v=9dhFH_G5Bow', 'https://youtube.com.evil.test/watch?v=9dhFH_G5Bow',
    'https://youtube.com@127.0.0.1/watch?v=9dhFH_G5Bow', 'file:///etc/passwd',
    'https://youtube.com:8000/watch?v=9dhFH_G5Bow', 'https://youtube.com/playlist?list=abc',
    'https://youtu.be/9dhFH_G5Bow/extra', URL + '&v=aaaaaaaaaaa',
    'https://youtube.com/watch?v=../../local', 'https://youtube.com/watch?v=short',
])
def test_rejects_arbitrary_network_and_playlist_inputs(url):
    with pytest.raises(ValueError):
        canonical_url(url)


@pytest.mark.parametrize('change', [
    {'duration': None}, {'duration': float('nan')}, {'duration': 7201}, {'duration': -1},
    {'live_status': 'is_live'}, {'live_status': 'is_upcoming'}, {'live_status': 'post_live'},
    {'availability': 'private'}, {'age_limit': 18}, {'id': 'other'}, {'_type': 'playlist'},
])
def test_metadata_bounds(change):
    with pytest.raises(ValueError):
        validate_info({'id': '9dhFH_G5Bow', 'duration': 100, **change}, URL, 7200)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    value = Store(tmp_path, limits=replace(Limits(), file_bytes=1024 ** 2))
    monkeypatch.setattr(value.pool, 'submit', lambda *args: None)
    yield value
    value.close()


def fake_download(monkeypatch, body, *, error=None):
    calls = []

    class Process:
        returncode = 1 if error else 0

        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))
            folder = Path(args[3])
            if error:
                write_json(folder / 'failure.json', {'error': error})
            else:
                (folder / 'source.mp4').write_bytes(body)
                write_json(folder / 'result.json', {'name': 'Released set.mp4'})

        def poll(self):
            return self.returncode

    monkeypatch.setattr('crowdset.store.subprocess.Popen', Process)
    # Popen is shared with the media probe, tested separately by existing finalizer tests.
    monkeypatch.setattr('crowdset.store.probe', lambda *args, **kwargs: 10)
    return calls


def test_import_reuses_original_finalizer_and_queues_once(store, tmp_path, monkeypatch):
    data = store.create('Set', owner='alice')
    body = write_wav(tmp_path / 'input.wav', music(2)).read_bytes()
    calls = fake_download(monkeypatch, body)
    monkeypatch.setenv('CROWDSET_R2_SECRET_ACCESS_KEY', 'must-not-inherit')
    started = store.import_youtube(data['id'], URL, 'alice')
    assert started['status'] == 'importing'
    assert store.originals.sessions()[0]['size'] == store.limits.file_bytes
    assert store.import_youtube(data['id'], URL, 'alice')['youtube_import'] == started['youtube_import']
    with pytest.raises(HTTPException):
        store.begin_batch(data['id'], 'bob')
    store.run_import(data['id'])
    saved = store.get(data['id'])
    assert saved['status'] == 'queued'
    assert saved['youtube_import']['state'] == 'complete'
    clip = saved['clips'][0]
    assert clip['source_url'] == URL and clip['uploader'] == 'alice'
    assert clip['expected_duration'] == 10 and clip['bytes'] == len(body)
    assert store.originals.path(data['id'], clip).read_bytes() == body
    assert store.active is None and store.upload is None
    assert not (store.directory(data['id']) / 'youtube').exists()
    assert len(store.import_youtube(data['id'], URL, 'alice')['clips']) == 1
    assert len(calls) == 1 and 'CROWDSET_R2_SECRET_ACCESS_KEY' not in calls[0][1]['env']
    assert calls[0][1]['start_new_session']


def test_download_failure_preserves_current_cut_and_releases_reservation(store, monkeypatch):
    data = store.create('Has cut')
    data.update(playable=True, status='ready', mix_revision='current', timeline={'duration': 10})
    store.save(data)
    fake_download(monkeypatch, b'', error='YouTube is blocking downloads. Upload the file.')
    store.import_youtube(data['id'], URL)
    store.run_import(data['id'])
    saved = store.get(data['id'])
    assert saved['status'] == 'ready' and saved['mix_revision'] == 'current'
    assert 'blocking' in saved['youtube_import']['error']
    assert saved['clips'] == [] and store.originals.sessions() == []
    assert store.active is None and store.upload is None


def test_admission_rejects_import_before_worker_or_network(store):
    data = store.create('Full')
    store.limits = replace(store.limits, original_bytes=100)
    with pytest.raises(HTTPException) as error:
        store.import_youtube(data['id'], URL)
    assert error.value.status_code == 507
    assert store.originals.sessions() == [] and store.active is None
    store.limits = replace(store.limits, original_bytes=10 ** 9, recordings=1)
    data['clips'] = [{'id': 'one', 'role': 'recording'}]
    store.save(data)
    with pytest.raises(HTTPException) as error:
        store.import_youtube(data['id'], URL)
    assert error.value.status_code == 409


def test_restart_marks_interrupted_import_retryable_and_cleans_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    original = Store(tmp_path, limits=replace(Limits(), file_bytes=1024 ** 2))
    monkeypatch.setattr(original.pool, 'submit', lambda *args: None)
    data = original.create('Restart')
    original.import_youtube(data['id'], URL)
    (original.directory(data['id']) / 'youtube/source.mp4.part').write_bytes(b'partial')
    original.close()
    recovered = Store(tmp_path)
    try:
        saved = recovered.get(data['id'])
        assert saved['status'] == 'idle'
        assert saved['youtube_import']['state'] == 'failed'
        assert 'restart' in saved['youtube_import']['error']
        assert recovered.originals.sessions() == []
        assert not (recovered.directory(data['id']) / 'youtube').exists()
    finally:
        recovered.close()


def test_route_validates_url_and_returns_pollable_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    with TestClient(create_app(tmp_path), base_url='http://127.0.0.1') as api:
        store = api.app.state.store
        store.limits = replace(store.limits, file_bytes=1024 ** 2)
        monkeypatch.setattr(store.pool, 'submit', lambda *args: None)
        data = api.post('/crowdset/sets', json={'name': 'Import'}).json()
        path = f'/crowdset/sets/{data["id"]}/youtube'
        assert api.post(path, json={'url': 'http://127.0.0.1'}).status_code == 422
        result = api.post(path, json={'url': URL})
        assert result.status_code == 202 and result.json()['status'] == 'importing'
        assert 'session_id' not in result.json()['youtube_import']
        assert api.get('/crowdset/sets?limits=true').json()['youtube_imports']


def test_import_keeps_exclusive_slot_until_final_metadata_commit(store, monkeypatch):
    data = store.create('Atomic import')
    fake_download(monkeypatch, b'video')
    finish = store.complete_session

    def checked_finish(*args, **kwargs):
        result = finish(*args, **kwargs)
        assert store.get(data['id'])['status'] == 'importing'
        assert store.upload is not None
        with pytest.raises(HTTPException):
            store.delete(data['id'])
        return result

    monkeypatch.setattr(store, 'complete_session', checked_finish)
    store.import_youtube(data['id'], URL)
    store.run_import(data['id'])
    assert store.get(data['id'])['status'] == 'queued'
    assert store.active is None and store.upload is None


def test_failed_cloud_cleanup_keeps_reservation_until_acknowledged(store, monkeypatch):
    import httpx

    class UnavailableBlobs:
        fail_cleanup = True

        def put(self, *args):
            raise httpx.ReadError('storage unavailable')

        def remove(self, keys):
            if self.fail_cleanup:
                raise httpx.ReadError('cleanup unavailable')

    blobs = UnavailableBlobs()
    store.blobs = store.originals.blobs = blobs
    data = store.create('Cloud failure')
    fake_download(monkeypatch, b'video')
    store.import_youtube(data['id'], URL)
    store.run_import(data['id'])
    saved = store.get(data['id'])
    assert saved['youtube_import']['state'] == 'failed' and saved['clips'] == []
    assert store.originals.usage()[0] == len(b'video')
    assert len(list((store.root / 'objects').glob('*.json'))) == 1
    assert store.active is None and store.upload is None
    with pytest.raises(HTTPException) as failure:
        store.import_youtube(data['id'], URL)
    assert failure.value.status_code == 503
    blobs.fail_cleanup = False
    assert store.cleanup_import(saved)
    assert store.originals.usage()[0] == 0
    assert store.originals.sessions() == []


def test_metadata_failure_still_releases_import_worker(store, monkeypatch):
    data = store.create('Disk failure')
    fake_download(monkeypatch, b'video')
    store.import_youtube(data['id'], URL)
    save = store.save

    def fail_final(value):
        if value.get('youtube_import', {}).get('state') == 'complete':
            raise OSError('Disk unavailable')
        return save(value)

    monkeypatch.setattr(store, 'save', fail_final)
    with pytest.raises(OSError):
        store.run_import(data['id'])
    assert store.active is None and store.upload is None


def test_oversized_download_never_enters_original_storage(store, monkeypatch):
    data = store.create('Oversized')
    fake_download(monkeypatch, b'x' * (store.limits.file_bytes + 1))
    store.import_youtube(data['id'], URL)
    store.run_import(data['id'])
    saved = store.get(data['id'])
    assert saved['clips'] == []
    assert 'size limit' in saved['youtube_import']['error']
    assert store.originals.sessions() == []


def test_download_deadline_kills_group_and_leaves_retryable_set(store, monkeypatch):
    data = store.create('Timeout')
    store.limits = replace(store.limits, media_seconds=-1)
    killed = []

    class HungProcess:
        pid = 12345
        returncode = None

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return self.returncode

        def wait(self):
            self.returncode = -9

    monkeypatch.setattr('crowdset.store.subprocess.Popen', HungProcess)
    monkeypatch.setattr('crowdset.store.os.killpg', lambda pid, sig: killed.append(pid))
    store.import_youtube(data['id'], URL)
    store.run_import(data['id'])
    assert killed == [12345]
    assert 'time or storage limit' in store.get(data['id'])['youtube_import']['error']
    assert store.active is None and store.originals.sessions() == []


def test_restart_after_original_commit_queues_processing_without_redownload(tmp_path, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    original = Store(tmp_path, limits=replace(Limits(), file_bytes=1024 ** 2))
    monkeypatch.setattr(original.pool, 'submit', lambda *args: None)
    data = original.create('Committed')
    original.import_youtube(data['id'], URL)
    data = original.get(data['id'])
    data.update(dirty=True, clips=[{'id': 'saved', 'source_url': URL}])
    original.save(data)
    original.close()
    recovered = Store(tmp_path)
    try:
        saved = recovered.get(data['id'])
        assert saved['status'] == 'queued'
        assert saved['youtube_import']['state'] == 'complete'
        assert data['id'] in recovered.pending
    finally:
        recovered.close()
