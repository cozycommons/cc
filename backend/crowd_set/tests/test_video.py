import subprocess
import re

import imageio_ffmpeg
import numpy as np
import pytest

from crowd_set import video
from crowd_set.limits import Limits
from crowd_set.storage import OriginalStore
from crowd_set.tests.test_audio import music, write_wav


def make_video(path, audio, *, color='red', size='90x160', delay=0, duration=None):
    args = [imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s={size}:r=24',
            '-itsoffset', str(delay), '-i', str(audio), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-threads', '1']
    if delay:
        args += ['-vf', "drawbox=c=red:t=fill:enable='lt(t,1)'"]
    args += ['-t', str(duration)] if duration else ['-shortest']
    subprocess.run(args + [str(path)], check=True, timeout=30)
    return path


def frame(path, seconds):
    raw = subprocess.check_output([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-ss', str(seconds), '-i', str(path),
                                   '-frames:v', '1', '-vf', 'scale=85:48', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], timeout=30)
    return np.frombuffer(raw, dtype=np.uint8).reshape(48, 85, 3)


def clip(identifier, offset, duration, *, picture=True, **extra):
    return {'id': identifier, 'duration': duration, 'role': 'crowd', 'included': True,
            'alignment': {'status': 'matched', 'offset_seconds': offset},
            'video': {'start': 0, 'end': duration, 'audio_start': 0} if picture else None, **extra}


def test_visual_plan_independent_of_audio_selection_and_global_frame_grid():
    clips = [clip('anchor', 0, 20, picture=False), clip('a', -2, 5.017), clip('b', 6.013, 4.011),
             clip('reference', 0, 50, role='reference'), clip('excluded', 0, 50, included=False),
             clip('unmatched', 0, 50, alignment={'status': 'unmatched'})]
    plan = video.plan_video(clips, {'duration': 22, 'origin_seconds': -2})
    assert [s['clip_id'] for s in plan['segments']] == ['a', 'b']
    assert plan['segments'][0]['first_frame'] == 0
    pieces = sorted(plan['segments'] + plan['gaps'], key=lambda s: s['first_frame'])
    assert pieces[0]['first_frame'] == 0 and pieces[-1]['last_frame'] == 22 * 24
    assert all(a['last_frame'] == b['first_frame'] for a, b in zip(pieces, pieces[1:]))
    assert sum(s['last_frame'] - s['first_frame'] for s in pieces) == 22 * 24
    assert video.plan_video(list(reversed(clips)), {'duration': 22, 'origin_seconds': -2}) == plan


def test_portrait_landscape_gaps_delayed_audio_and_soundtrack(tmp_path):
    audio = write_wav(tmp_path / 'source.wav', music(8))
    a = make_video(tmp_path / 'a.mp4', audio, duration=3)
    b = make_video(tmp_path / 'b.mp4', audio, color='blue', size='160x90', delay=1, duration=4)
    root = tmp_path / 'store'
    root.mkdir()
    originals = OriginalStore(root)
    folder = root / 'set'
    folder.mkdir()
    clips = [clip('a', 0, 3, file='a.mp4', name='a.mp4'), clip('b', 5, 3, file='b.mp4', name='b.mp4')]
    for c, source in zip(clips, (a, b)):
        c['video'] = video.probe(source, Limits())
        originals.destination('set', c).write_bytes(source.read_bytes())
    assert clips[1]['video']['audio_start'] == pytest.approx(1, abs=.08)
    assert clips[1]['video']['start'] == pytest.approx(-clips[1]['video']['audio_start'], abs=.001)
    assert video.probe(audio, Limits()) is None
    write_wav(folder / 'pending.wav', music(8))
    timeline = video.plan_video(clips, {'duration': 8, 'origin_seconds': 0})
    assert video.render(timeline, clips, originals, 'set', folder, Limits())
    output = folder / 'pending.mp4'
    metadata = video.run(['-v', 'info', '-i', str(output), '-frames:v', '1', '-f', 'null', '-'], 30)
    assert '1920x1080' in metadata
    assert (timeline['width'], timeline['height']) == (1920, 1080)
    red, gap, blue = [frame(output, t) for t in (1, 4, 5.5)]
    assert red[24, 42, 0] > 200 and red[24, 42, 2] < 40
    assert np.max(np.abs(red[24, 0].astype(int) - [36, 48, 39])) < 10  # Portrait letterbox.
    assert np.max(np.abs(gap[24, 42].astype(int) - [36, 48, 39])) < 10
    assert blue[24, 42, 2] > 200 and blue[24, 42, 0] < 40
    decoded = subprocess.check_output([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', str(output), '-vn',
                                       '-ar', '16000', '-ac', '1', '-f', 'f32le', '-'], timeout=30)
    actual = np.frombuffer(decoded, dtype='<f4')[:8 * 16000]
    assert np.corrcoef(actual, music(8))[0, 1] > .98
    assert output.stat().st_size < video.byte_bound(8)


def test_early_video_end_is_neutral_not_frozen(tmp_path):
    audio = write_wav(tmp_path / 'source.wav', music(5))
    path = tmp_path / 'short.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=24:d=2',
                    '-i', str(audio), '-c:v', 'libx264', '-c:a', 'aac', str(path)], check=True, timeout=30)
    root = tmp_path / 'store'
    root.mkdir()
    originals = OriginalStore(root)
    folder = root / 'set'
    folder.mkdir()
    item = clip('one', 0, 5, file='short.mp4', name='short.mp4')
    item['video'] = video.probe(path, Limits())
    originals.destination('set', item).write_bytes(path.read_bytes())
    write_wav(folder / 'pending.wav', music(5))
    plan = video.plan_video([item], {'duration': 5, 'origin_seconds': 0})
    assert plan['segments'][0]['end'] == pytest.approx(2, abs=1/24)
    assert plan['gaps'][0]['start'] == pytest.approx(2, abs=1/24)
    video.render(plan, [item], originals, 'set', folder, Limits())
    assert frame(folder / 'pending.mp4', 1)[24, 42, 0] > 200
    assert np.max(np.abs(frame(folder / 'pending.mp4', 4)[24, 42].astype(int) - [36, 48, 39])) < 10


def test_rotation_is_preserved_and_oversize_rendition_rejected(tmp_path, monkeypatch):
    audio = write_wav(tmp_path / 'source.wav', music(3))
    original = make_video(tmp_path / 'portrait.mp4', audio)
    rotated = tmp_path / 'rotated.mp4'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-display_rotation:v:0', '90', '-i', str(original), '-c', 'copy', str(rotated)], check=True, timeout=30)
    root = tmp_path / 'store'
    root.mkdir()
    originals = OriginalStore(root)
    folder = root / 'set'
    folder.mkdir()
    item = clip('one', 0, 3, file='rotated.mp4', name='rotated.mp4')
    item['video'] = video.probe(rotated, Limits())
    originals.destination('set', item).write_bytes(rotated.read_bytes())
    write_wav(folder / 'pending.wav', music(3))
    plan = video.plan_video([item], {'duration': 3, 'origin_seconds': 0})
    video.render(plan, [item], originals, 'set', folder, Limits())
    assert frame(folder / 'pending.mp4', 1)[24, 5, 0] > 200
    monkeypatch.setattr(video, 'byte_bound', lambda duration: 1024)
    with pytest.raises(ValueError, match='bounds|bound|render'):
        video.render(plan, [item], originals, 'set', folder, Limits())


def test_short_video_cannot_hide_an_available_picture():
    clips = [clip('b', 0, 5), clip('a', 3, 5), clip('c', 4, 3)]
    clips[1]['video']['end'] = 1
    plan = video.plan_video(clips, {'duration': 8, 'origin_seconds': 0})
    assert [(s['clip_id'], s['start'], s['end']) for s in plan['segments']] == [('b', 0, 5), ('c', 5, 7)]
    assert plan['gaps'][0]['start'] == 7


def test_probe_recovers_when_ffmpeg_omits_audio_frame_log(tmp_path, monkeypatch):
    audio = write_wav(tmp_path / 'source.wav', music(3))
    source = make_video(tmp_path / 'delayed.mp4', audio, delay=1, duration=4)
    run = video.run

    def omit_combined_audio(args, *positional, **kwargs):
        report = run(args, *positional, **kwargs)
        if '-vf' in args:
            report = re.sub(r'\[Parsed_ashowinfo_[^\n]*', '', report)
        return report

    monkeypatch.setattr(video, 'run', omit_combined_audio)
    picture = video.probe(source, Limits())
    assert picture['audio_start'] == pytest.approx(1, abs=.08)
    assert picture['start'] == pytest.approx(-picture['audio_start'], abs=.001)
