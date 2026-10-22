"""Remote ownership, quota and publication tests without real media or cloud access."""
from copy import deepcopy
import json
from pathlib import Path
import time

from fastapi import HTTPException
import pytest

from crowdset.remote import RemoteJobs
from crowdset.store import Store
from crowdset.worker import write_json
from crowdset.r2 import R2Blobs


class Blobs:
    def __init__(self, root):
        self.root = root
        self.started = []
    def check_bucket(self, size):
        pass
    def ledger(self):
        return {item['key']: item['bytes'] for item in (json.loads(p.read_text()) for p in (self.root / 'objects').glob('*.json'))}
    def signed(self, method, key, **kwargs):
        return 'https://media.example/' + key
    def begin_direct(self, key, size, sha, mime):
        self.started.append(key)
    def finish_direct(self, key, size, sha):
        pass
    def remove(self, keys):
        pass


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('CROWDSET_REMOTE_WORKER', '1')
    monkeypatch.setenv('CROWDSET_WORKER_TOKEN', 'test-worker-secret')
    value = Store(tmp_path, blobs=Blobs(tmp_path))
    yield value
    value.close()


def recording(data):
    return {'id': 'a' * 32, 'name': 'friend.mp4', 'file': 'a.upload', 'kind': 'video', 'bytes': 100,
            'uploader': data['owner'], 'included': True, 'role': 'recording', 'object_key': 'originals/a/source',
            'sha256': 'b' * 64, 'expected_duration': 10}


def test_remote_claim_survives_restart_and_rejects_expired_result(store):
    data = store.create('Live set', owner='owner')
    job = store.remote.enqueue(data, 'youtube', url='https://www.youtube.com/watch?v=9dhFH_G5Bow', owner='owner')
    claim = store.remote.claim()
    assert claim['id'] == job['id'] and claim['state'] == 'running'
    assert store.remote.claim() is None
    restarted = RemoteJobs(store)
    assert restarted.owned(claim['id'], claim['claim'])['id'] == claim['id']
    claim['lease_until'] = time.time() - 1
    restarted.save(claim)
    with pytest.raises(HTTPException, match='lease expired'):
        restarted.owned(claim['id'], claim['claim'])
    replacement = restarted.claim()
    assert replacement['claim'] != claim['claim']
    with pytest.raises(HTTPException):
        restarted.owned(claim['id'], claim['claim'])


@pytest.mark.parametrize('claimed', [False, True])
def test_finished_batch_keeps_first_upload_polling_during_worker_validation(store, claimed):
    data = store.create('First recording', owner='owner')
    batch = store.begin_batch(data['id'], 'owner')
    upload = store.prepare_session(data['id'], 'friend.mp4', 100, 'f' * 64, 'owner', batch['id'])
    session = store.session(data['id'], upload['id'], 'owner')
    store.remote.browser_prepare(session)
    store.remote.browser_ack(session, 1)
    store.remote.browser_finish(session)
    if claimed:
        assert store.remote.claim()['kind'] == 'ingest'
    value = store.finish_batch(data['id'], batch['id'], 'owner')
    assert value['clips'] == []
    assert value['status'] == 'queued'
    assert 'Validating' in value['stage']


def test_remote_inputs_and_output_reservations_are_scoped(store):
    data = store.create('Live set', owner='owner')
    data['clips'] = [recording(data)]
    store.save(data)
    store.remote.enqueue(data)
    job = store.remote.claim()
    assert store.remote.read(job, data['clips'][0]['object_key'])['url'].startswith('https://')
    with pytest.raises(HTTPException):
        store.remote.read(job, 'originals/another-set/private')
    for name in ('../secret', '/tmp/file', 'a/part'):
        with pytest.raises(HTTPException):
            store.remote.reserve(job, name, 3, 'f' * 64, 'video/mp4')
    value = store.remote.reserve(job, 'pending.mp4', 3, 'f' * 64, 'video/mp4')
    assert job['id'] in value['key'] and job['claim'] in value['key']
    with pytest.raises(HTTPException):
        store.remote.reserve(job, 'pending.mp4', 4, 'e' * 64, 'video/mp4')
    value['complete'] = True
    store.remote.save(job)
    before = len(store.blobs.started)
    store.remote.reserve(job, 'pending.mp4', 3, 'f' * 64, 'video/mp4')
    assert len(store.blobs.started) == before


def test_publish_preserves_ownership_and_previous_playable_revision(store):
    data = store.create('Live set', owner='owner')
    data.update(clips=[recording(data)], mix_revision='old', playable=True, mix_object='mixes/old.wav', status='ready')
    store.save(data)
    store.remote.enqueue(data)
    job = store.remote.claim()
    for name in ('pending.mp4', 'pending.wav', 'scrub-0.jpg'):
        store.remote.reserve(job, name, 3, 'f' * 64, 'video/mp4')
    result = {'clips': [{**data['clips'][0], 'uploader': 'attacker', 'included': False, 'duration': 10}],
              'playable': True, 'video_playable': True, 'timeline': {'duration': 10},
              'video_timeline': {'segments': []}, 'composition': None,
              'scrub_previews': {'clip': {'sheets': ['scrub-0.jpg']}}}
    with pytest.raises(HTTPException, match='not completed'):
        store.remote.publish(job, result)
    assert store.get(data['id'])['mix_object'] == 'mixes/old.wav'
    for name in job['artifacts']:
        store.remote.complete(job, name)
    published = store.remote.publish(job, result)
    assert published['status'] == 'ready'
    assert published['clips'][0]['uploader'] == 'owner' and published['clips'][0]['included']
    assert published['previous_revision']['mix_object'] == 'mixes/old.wav'
    assert published['preview_objects']['scrub-0.jpg'].endswith('scrub-0.jpg')
    with pytest.raises(HTTPException):
        store.remote.owned(job['id'], job['claim'])


def test_direct_upload_never_creates_a_partial_file(store):
    data = store.create('Live set', owner='owner')
    session = store.prepare_session(data['id'], 'friend.mp4', 100, 'f' * 64, 'owner')
    saved = store.session(data['id'], session['id'], 'owner')
    public = store.remote.browser_prepare(saved)
    assert public['direct']
    store.remote.browser_ack(saved, 1)
    store.remote.browser_finish(saved)
    assert store.get(data['id'])['status'] == 'queued'
    assert not list(store.root.rglob('*.part'))
    assert store.remote.jobs()[0]['kind'] == 'ingest'
    with pytest.raises(HTTPException):
        store.session(data['id'], session['id'], 'other-owner')


def test_publication_rejects_wrong_clip_identity_and_infinite_metadata(store):
    data = store.create('Live set', owner='owner')
    data['clips'] = [recording(data)]
    store.save(data)
    store.remote.enqueue(data)
    job = store.remote.claim()
    with pytest.raises(HTTPException):
        store.remote.publish(job, {'playable': True, 'clips': []})
    with pytest.raises(ValueError):
        store.remote.publish(job, {'playable': True, 'duration': float('nan')})


def test_real_media_runs_off_api_and_publishes_from_worker(store, tmp_path, monkeypatch):
    import imageio_ffmpeg
    import subprocess
    import shutil
    from crowdset.blobs import digest
    from crowdset.remote_agent import execute
    from crowdset import video, composition
    def forbidden(*args, **kwargs):
        pytest.fail('Remote rendering must not normalize video with the old CPU pipeline')
    monkeypatch.setattr(video, 'render', forbidden)
    monkeypatch.setattr(composition, 'prepare', forbidden)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    source = tmp_path / 'synthetic.mp4'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=1920x1080:rate=24',
                    '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=16000', '-t', '6',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
    data = store.create('Remote synthetic set', owner='owner')
    clip = recording(data)
    clip.update(bytes=source.stat().st_size, sha256=digest(source), expected_duration=6)
    data['clips'] = [clip]
    store.save(data)
    store.remote.enqueue(data)
    job = store.remote.claim()
    job['limits'] = __import__('dataclasses').asdict(store.limits)
    published_files = {}
    class SyntheticControl:
        def download(self, key, destination, size, checksum=None):
            shutil.copyfile(source, destination)
            return destination
        def upload(self, path, name=None, mime='application/octet-stream'):
            name = name or path.name
            value = store.remote.reserve(job, name, path.stat().st_size, digest(path), mime)
            store.remote.complete(job, name)
            published_files[name] = path
            return value
        def call(self, operation, **body):
            assert operation == 'publish'
            return store.remote.publish(job, body['result'])
    spool = tmp_path / 'pc' / 'data'
    spool.mkdir(parents=True)
    execute(spool, SyntheticControl(), job, ffmpeg, 'ffprobe', 'libx264')
    result = store.get(data['id'])
    assert result['status'] == 'ready' and result['video_playable']
    assert published_files['pending.mp4'].is_file()
    assert result['composition'] is None
    assert not list(store.directory(data['id']).glob('*.mp4'))
    assert not list(store.directory(data['id']).glob('*.wav'))


def test_worker_api_requires_credential_and_legacy_bytes_are_blocked(store, monkeypatch):
    from fastapi.testclient import TestClient
    from crowdset import app as module
    monkeypatch.setattr(module, 'Store', lambda *args, **kwargs: store)
    data = store.create('API set', owner=None)
    store.remote.enqueue(data, 'youtube', owner=None, url='https://www.youtube.com/watch?v=9dhFH_G5Bow')
    with TestClient(module.create_app(store.root), base_url="http://127.0.0.1") as client:
        assert client.post('/crowdset/worker/claim', json={}).status_code == 403
        claimed = client.post('/crowdset/worker/claim', headers={'Authorization': 'Bearer test-worker-secret'}, json={})
        assert claimed.status_code == 200
        assert claimed.json()['kind'] == 'youtube'
        assert client.put(f"/crowdset/sets/{data['id']}/clips?name=clip.mp4", content=b'bytes').status_code == 409


def test_queued_edits_are_kept_and_changed_inputs_reject_stale_claim(store):
    data = store.create('Queued set', owner='owner')
    clip = recording(data)
    data['clips'] = [clip]
    store.save(data)
    store.queue(data)
    data = store.get(data['id'])
    data['clips'][0]['included'] = False
    store.remote.enqueue(data)
    assert not store.get(data['id'])['clips'][0]['included']
    job = store.remote.claim()
    data = store.get(data['id'])
    data['clips'][0]['included'] = True
    store.save(data)
    with pytest.raises(HTTPException, match='Recordings changed'):
        store.remote.owned(job['id'], job['claim'])


def test_direct_activity_extends_batch_and_failed_ingest_can_be_retried(store):
    data = store.create('Retry set', owner='owner')
    batch = store.begin_batch(data['id'], 'owner')
    value = store.prepare_session(data['id'], 'friend.mp4', 100, 'f' * 64, 'owner', batch['id'])
    session = store.session(data['id'], value['id'], 'owner')
    store.remote.browser_prepare(session)
    assert store.batches[data['id']]['deadline'] > time.monotonic() + 500
    store.remote.browser_ack(session, 1)
    store.remote.browser_finish(session)
    job = store.remote.claim()
    store.remote.fail(job, 'Temporary transfer failure')
    assert store.session(data['id'], value['id'], 'owner')['state'] == 'validating'
    store.remote.browser_finish(session)
    assert any(j['state'] == 'queued' and j['kind'] == 'ingest' for j in store.remote.jobs())


def test_orphan_validating_session_is_recovered_and_retained_while_pc_offline(store):
    data = store.create('Recovered set', owner='owner')
    value = store.prepare_session(data['id'], 'friend.mp4', 100, 'f' * 64, 'owner')
    session = store.session(data['id'], value['id'], 'owner')
    store.remote.browser_prepare(session)
    session.update(state='validating', expires_at=time.time()-100)
    store.save_session(session)
    store.remote.recover()
    store.expire_sessions()
    assert store.session(data['id'], value['id'], 'owner')['state'] == 'validating'
    assert store.remote.jobs()[0]['kind'] == 'ingest'


def test_ingest_replay_never_deletes_its_already_published_original(store):
    data = store.create('Publication replay', owner='owner')
    value = store.prepare_session(data['id'], 'friend.mp4', 100, 'f' * 64, 'owner')
    session = store.session(data['id'], value['id'], 'owner')
    store.remote.browser_prepare(session)
    store.remote.browser_ack(session, 1)
    store.remote.browser_finish(session)
    job = store.remote.claim()
    clip = {**session['clip'], 'object_key': session['object_key'], 'sha256': 'b' * 64, 'expected_duration': 10}
    data['clips'] = [clip]
    store.save(data)  # Simulate a crash after metadata commit but before the job acknowledgment.
    result = store.remote.publish(job, {'sha256': 'b' * 64, 'duration': 10})
    assert result['clips'][0]['object_key'] in store.blobs.ledger()
    assert len(result['clips']) == 1


def test_measured_worker_progress_is_bounded_and_events_are_admin_only(store):
    from crowdset.app import present
    data = store.create('Progress', owner='owner')
    data['clips'] = [recording(data)]
    store.save(data)
    store.remote.enqueue(data)
    job = store.remote.claim()
    telemetry = {'phase': 'render', 'completed': 240, 'total': 2400, 'fps': 48.0,
                 'remaining_seconds': 45, 'updated_at': time.time(), 'engine': 'h264_nvenc',
                 'file': '/private/local/path', 'token': 'must-not-leak'}
    for _ in range(3):
        store.remote.heartbeat(job, 'Rendering video on the PC GPU…', telemetry)
    value = store.get(data['id'])
    assert value['processing']['percent'] == 10
    assert value['processing']['remaining_seconds'] == 45
    assert value['processing']['engine'] == 'h264_nvenc'
    assert 'token' not in value['processing'] and 'file' not in value['processing']
    assert len(value['processing_events']) == 3  # queued, claimed, rendering; no heartbeat spam
    assert 'processing_events' not in present(deepcopy(value), 'owner')
    assert len(present(deepcopy(value), 'owner', is_admin=True)['processing_events']) == 3
    for n in range(50):
        store.remote.heartbeat(job, f'Stage {n}', {'phase': 'bad', 'fps': float('inf'), 'completed': -1, 'total': True})
    value = store.get(data['id'])
    assert len(value['processing_events']) == 40
    assert value['processing']['phase'] == 'remote'
    assert 'percent' not in value['processing'] and 'fps' not in value['processing']
