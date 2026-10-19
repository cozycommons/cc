from types import SimpleNamespace

from fastapi import HTTPException

from crowdset import previews, video
from crowdset.limits import Limits
from crowdset.storage import OriginalStore
from crowdset.tests.test_app import client, create
from crowdset.tests.test_audio import music, write_wav
from crowdset.tests.test_video import make_video


def test_storyboard_generation_reuses_cache_and_repairs_missing_sheet(tmp_path, monkeypatch):
    root = tmp_path / 'store'
    root.mkdir()
    originals = OriginalStore(root)
    directory = root / 'set'
    directory.mkdir()
    source = make_video(directory / 'original.mp4', write_wav(tmp_path / 'audio.wav', music(12)), size='160x90')
    clip = {'id': 'clip', 'file': source.name, 'bytes': source.stat().st_size, 'sha256': 'source-hash', 'video': video.probe(source, Limits())}
    timeline = {'segments': [{'clip_id': 'clip'}]}
    def prepare():
        return previews.prepare([clip], timeline, {'id': 'set'}, originals, directory, Limits(), lambda *args: None)
    first = prepare()['clip']
    assert first['count'] == 2 and first['interval'] == 10
    assert len(first['sheets']) == 1
    sheet = directory / first['sheets'][0]
    assert sheet.read_bytes().startswith(b'\xff\xd8')
    info = video.run(['-v', 'info', '-i', str(sheet), '-frames:v', '1', '-f', 'null', '-'], 10)
    assert '320x90' in info
    modified = sheet.stat().st_mtime_ns
    assert prepare()['clip'] == first
    assert sheet.stat().st_mtime_ns == modified
    sheet.unlink()
    assert prepare()['clip'] == first and sheet.exists()
    monkeypatch.setattr(video, 'run', lambda *args: (_ for _ in ()).throw(ValueError('decoder failed')))
    sheet.unlink()
    assert prepare() == {}
    assert not list(directory.glob('video-preview-*'))
    assert source.exists()


def test_quota_failure_does_not_download_or_block_cut(tmp_path):
    def reject(*args, **kwargs):
        raise HTTPException(507, 'full')
    originals = SimpleNamespace(admit=reject)
    clip = {'id': 'clip', 'bytes': 20, 'object_key': 'original', 'video': {'start': 0, 'end': 60}}
    assert previews.prepare([clip], {'segments': [{'clip_id': 'clip'}]}, {'id': 'set'}, originals, tmp_path,
                            Limits(), lambda *args: None) == {}


def test_preview_routes_are_manifest_and_revision_scoped(tmp_path):
    with client(tmp_path) as api:
        route = create(api)
        store = api.app.state.store
        data = store.get(route.rsplit('/', 1)[-1])
        folder = store.directory(data['id'])
        data.update(mix_revision='current', scrub_previews={'clip': {'sheets': ['scrub-current-000.jpg']}},
                    previous_revision={'mix_revision': 'previous', 'scrub_previews': {'clip': {'sheets': ['scrub-previous-000.jpg']}}})
        store.save(data)
        for name in ('scrub-current-000.jpg', 'scrub-previous-000.jpg', 'scrub-orphan-000.jpg'):
            (folder / name).write_bytes(b'jpeg')
        response = api.get(route + '/previews/scrub-current-000.jpg?v=current')
        assert response.status_code == 200 and response.content == b'jpeg'
        assert response.headers['cache-control'] == 'no-store'
        assert api.get(route + '/previews/scrub-previous-000.jpg?v=previous').status_code == 200
        assert api.get(route + '/previews/scrub-orphan-000.jpg?v=current').status_code == 404
        assert api.get(route + '/previews/scrub-current-000.jpg?v=previous').status_code == 404
        assert api.get(route + '/previews/scrub-current-000.jpg?v=expired').status_code == 404
        store.collect_mixes(data['id'])
        assert (folder / 'scrub-current-000.jpg').exists()
        assert (folder / 'scrub-previous-000.jpg').exists()
        assert not (folder / 'scrub-orphan-000.jpg').exists()
