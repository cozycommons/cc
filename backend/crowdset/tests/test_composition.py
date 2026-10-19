from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from crowdset import composition, video
from crowdset.store import Store
from crowdset.worker import write_json
from crowdset.tests.test_app import client, create, upload, wait
from crowdset.tests.test_audio import music, write_wav
from crowdset.tests.test_video import clip, make_video, frame


def test_friend_priority_overlap_stability_bounds_and_leftovers():
    anchor = clip('official', 0, 100)
    clips = [anchor, clip('a', 10, 20), clip('b', 15, 17), clip('c', 16, 25),
             clip('negative', -5, 10), clip('tail', 98, 9),
             clip('excluded', 40, 10, included=False), clip('unmatched', 50, 10, alignment={'status': 'unmatched'}),
             clip('audio', 60, 10, picture=False), clip('other-full', 0, 100)]
    timeline = {'duration': 100, 'origin_seconds': 0}
    plan, base = composition.plan(clips, timeline, anchor)
    assert [(s['clip_id'], s['start'], s['end']) for s in plan['segments']] == [
        ('negative', 0, 5), ('official', 5, 10), ('a', 10, 30), ('c', 30, 41),
        ('official', 41, 98), ('tail', 98, 100)]
    assert base == video.plan_video([anchor], timeline)
    assert composition.plan(list(reversed(clips)), timeline, anchor) == (plan, base)
    tie, _ = composition.plan([anchor, clip('z', 10, 5), clip('a', 10, 5)], timeline, anchor)
    assert tie['segments'][1]['clip_id'] == 'a'
    delayed = clip('delayed', 0, 100, video={'start': 2, 'end': 98, 'audio_start': 0})
    delayed_plan, _ = composition.plan([delayed], timeline, delayed)
    assert [(s['start'], s['end']) for s in delayed_plan['gaps']] == [(0, 2), (98, 100)]
    assert [(s['start'], s['end']) for s in delayed_plan['segments']] == [(2, 98)]


def test_official_audio_and_normalized_friend_video_reuse(tmp_path):
    raw = music(80)
    full = make_video(tmp_path / 'official.mp4', write_wav(tmp_path / 'official.wav', raw), color='blue', size='160x90')
    friend = make_video(tmp_path / 'friend.mp4', write_wav(tmp_path / 'friend.wav', raw[20*16000:70*16000]), color='red')
    with client(tmp_path / 'store') as api:
        path = create(api)
        upload(api, path, 'official.mp4', full.read_bytes())
        first = wait(api, path)
        assert first['status'] == 'ready', first
        original_audio = api.get(path + '/audio').content
        official_id = first['clips'][0]['id']
        upload(api, path, 'friend.mp4', friend.read_bytes())
        assert api.put(path + '/soundtrack', json={'clip_id': official_id}).status_code == 200
        second = wait(api, path)
        assert second['status'] == 'ready', second
        assert second['composition']['soundtrack_clip_id'] == official_id
        assert second['mix_revision'] != first['mix_revision']
        assert second['mix_file'] == first['mix_file'] and second['video_file'] == first['video_file']
        assert api.get(path + '/audio').content == original_audio
        assert {s['clip_id'] for s in second['timeline']['segments']} == {official_id}
        insert = next(s for s in second['video_timeline']['segments'] if s.get('asset_id'))
        assert insert['start'] == pytest.approx(20, abs=.1)
        assert insert['end'] == pytest.approx(70, abs=.15)
        url = path + '/overlays/' + insert['asset_id'] + '?v=' + second['mix_revision']
        response = api.get(url)
        assert response.status_code == 200
        assert api.get(url, headers={'Range': 'bytes=0-99'}).content == response.content[:100]
        assert api.get(url.replace(second['mix_revision'], first['mix_revision'])).status_code == 404
        output = tmp_path / 'insert.mp4'
        output.write_bytes(response.content)
        info = video.run(['-v', 'info', '-i', str(output), '-frames:v', '1', '-f', 'null', '-'], 30)
        assert '1920x1080' in info and 'Audio:' not in info
        image = frame(output, 1)
        assert image[24, 42, 0] > 200
        assert np.max(np.abs(image[24, 0].astype(int) - [36, 48, 39])) < 10
        store = api.app.state.store
        legacy = store.get(second['id'])
        legacy.pop('scrub_previews', None)
        store.save(legacy)
        for sheet in (tmp_path / 'store' / second['id']).glob('scrub-*'):
            sheet.unlink()
        assert api.post(path + '/process').status_code == 202
        third = wait(api, path)
        assert third['status'] == 'ready' and third['mix_revision'] == second['mix_revision']
        assert set(third['scrub_previews']) == {official_id, insert['clip_id']}
        sheet = third['scrub_previews'][insert['clip_id']]['sheets'][0]
        assert api.get(path + '/previews/' + sheet + '?v=' + third['mix_revision']).status_code == 200
        assert api.get(url).content == response.content
        asset = third['composition']['assets'][insert['asset_id']]
        (tmp_path / 'store' / third['id'] / asset['file']).unlink()
        api.post(path + '/process')
        repaired = wait(api, path)
        assert repaired['status'] == 'ready' and repaired['mix_revision'] != third['mix_revision']
        assert api.get(url).content == response.content
        api.patch(path + '/clips/' + official_id, json={'included': False})
        failed = wait(api, path)
        assert failed['status'] == 'failed' and 'selected full set' in failed['error']
        assert failed['mix_revision'] == repaired['mix_revision']
        assert api.get(url).status_code == 200


@pytest.mark.parametrize('failure', [None, 'quota', 'upload', 'metadata'])
def test_cloud_manifest_publication_and_shared_base_retention(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    store = Store(tmp_path)
    uploaded, removed = [], []
    def put(path, key, mime):
        uploaded.append(key)
        if failure == 'upload':
            raise ValueError('Upload failed')
    store.blobs = SimpleNamespace(put=put, remove=lambda keys: removed.extend(keys))
    store.originals.blobs = store.blobs
    data = store.create('Official set')
    prefix = f'mixes/{data["id"]}/'
    data.update(status='processing', playable=True, video_playable=True, mix_revision='old',
                mix_file='mix-old.wav', video_file='mix-old.mp4', mix_object=prefix+'old.wav',
                video_object=prefix+'old.mp4', mix_bytes=4, video_bytes=4)
    folder = store.directory(data['id'])
    for suffix in ('wav', 'mp4'):
        (folder / f'mix-old.{suffix}').write_bytes(b'old!')
        store.originals.record_blob(prefix + f'old.{suffix}', 4)
    store.save(data)
    def finish(**kwargs):
        (folder / 'pending.wav').write_bytes(b'old!')
        (folder / 'overlay-insert.mp4').write_bytes(b'insert')
        write_json(folder / 'result.json', {'playable': True, 'video_playable': True,
            'reuse_base_revision': 'old', 'clips': [], 'timeline': {}, 'video_timeline': {},
            'composition': {'assets': {'insert': {'file': 'overlay-insert.mp4', 'object': None, 'bytes': 6}}}})
        return 0
    monkeypatch.setattr('crowdset.store.subprocess.Popen', lambda *args, **kwargs: SimpleNamespace(wait=finish, poll=lambda: 0))
    store.limits = replace(store.limits, original_bytes=13 if failure == 'quota' else 14)
    save = store.save
    def publish(value):
        if failure == 'metadata' and value['status'] == 'ready':
            raise OSError('Metadata failed')
        return save(value)
    monkeypatch.setattr(store, 'save', publish)
    try:
        store.run(data['id'])
        saved = store.get(data['id'])
        assert saved['mix_object'] == data['mix_object'] and saved['video_object'] == data['video_object']
        assert data['video_object'] not in removed and data['mix_object'] not in removed
        if failure:
            assert saved['status'] == 'failed' and saved['mix_revision'] == 'old'
            assert store.originals.usage()[0] == 8
        else:
            assert saved['status'] == 'ready' and saved['mix_revision'] != 'old'
            assert uploaded == [prefix + 'overlay-insert.mp4']
            assert store.originals.usage()[0] == 14
            assert not (folder / 'overlay-insert.mp4').exists()
            # A subsequent manifest keeps assets referenced only by the preceding cut.
            saved['previous_revision'] = dict(saved)
            saved['composition'] = None
            store.save(saved)
            store.collect_mixes(data['id'])
            assert store.originals.usage()[0] == 14
            saved['previous_revision'] = {}
            store.save(saved)
            store.collect_mixes(data['id'])
            assert store.originals.usage()[0] == 8
    finally:
        store.close()


def test_hevc_phone_insert_normalizes_to_silent_h264(tmp_path):
    import subprocess
    import imageio_ffmpeg
    from crowdset.limits import Limits
    from crowdset.storage import OriginalStore
    wav = write_wav(tmp_path / 'phone.wav', music(3))
    source = make_video(tmp_path / 'phone.mp4', wav)
    phone = tmp_path / 'phone.mov'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(source),
                    '-c:v', 'libx265', '-x265-params', 'pools=1:frame-threads=1:log-level=error',
                    '-tag:v', 'hvc1', '-c:a', 'copy', str(phone)], check=True, timeout=30)
    root = tmp_path / 'store'
    root.mkdir()
    originals = OriginalStore(root)
    folder = root / 'set'
    folder.mkdir()
    official = clip('official', 0, 10)
    friend = clip('friend', 2, 3, file='phone.mov', name='phone.mov')
    friend['video'] = video.probe(phone, Limits())
    originals.destination('set', friend).write_bytes(phone.read_bytes())
    visual, _ = composition.plan([official, friend], {'duration': 10, 'origin_seconds': 0}, official)
    assets = composition.prepare(visual, [official, friend], {'id': 'set'}, originals, folder, Limits(), lambda *a, **k: None)
    output = folder / next(iter(assets.values()))['file']
    info = video.run(['-v', 'info', '-i', str(output), '-frames:v', '1', '-f', 'null', '-'], 30)
    assert 'Video: h264' in info and 'Audio:' not in info
    assert frame(output, 1)[24, 42, 0] > 200
