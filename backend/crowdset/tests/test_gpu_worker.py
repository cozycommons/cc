import copy
import hashlib
import sys

import pytest

from crowdset import gpu_worker


def test_remote_startup_hands_off_to_processing_python(monkeypatch):
    monkeypatch.setenv('CROWDSET_WORKER_URL', 'https://cozycommons.dev')
    monkeypatch.setenv('CROWDSET_WORKER_PYTHON', '/processing/bin/python')
    arguments = ['gpu_worker.py', '--root', '/worker/spool', '--ffmpeg', '/ffmpeg', '--ffprobe', '/ffprobe']
    monkeypatch.setattr(sys, 'argv', arguments)
    def execv(executable, argv):
        assert executable == '/processing/bin/python'
        assert argv == [executable, gpu_worker.__file__, *arguments[1:]]
        raise SystemExit(73)
    monkeypatch.setattr(gpu_worker.os, 'execv', execv)
    with pytest.raises(SystemExit) as result:
        gpu_worker.main()
    assert result.value.code == 73


def test_remote_startup_uses_current_processing_python(tmp_path, monkeypatch):
    from crowdset import remote_agent
    monkeypatch.setenv('CROWDSET_WORKER_URL', 'https://cozycommons.dev')
    monkeypatch.setenv('CROWDSET_WORKER_PYTHON', sys.executable)
    monkeypatch.setattr(sys, 'argv', ['gpu_worker.py', '--root', str(tmp_path), '--ffmpeg', '/ffmpeg', '--ffprobe', '/ffprobe'])
    monkeypatch.setattr(gpu_worker.signal, 'signal', lambda *_: None)
    monkeypatch.setattr(gpu_worker.os, 'umask', lambda *_: None)
    called = []
    monkeypatch.setattr(remote_agent, 'serve', lambda *args: called.append(args))
    gpu_worker.main()
    assert len(called) == 1
    assert called[0][:4] == (tmp_path.resolve(), '/ffmpeg', '/ffprobe', 'h264_nvenc')


def edit():
    return {'version': 1, 'audio_source': 'official',
            'sources': {'official': {'sha256': 'a' * 64, 'bytes': 1024}},
            'segments': [{'source': 'official', 'start_frame': 0, 'frames': 48}]}


@pytest.mark.parametrize('change', [
    {'version': True}, {'audio_source': '../private'}, {'audio_source': {}},
    {'sources': {'../secret': {'sha256': 'a' * 64, 'bytes': 1}}},
    {'sources': {'official': {'sha256': '../../secret', 'bytes': 1}}},
    {'sources': {'official': {'sha256': 'a' * 64, 'bytes': -1}}},
    {'segments': [{'source': 'official', 'start_frame': -1, 'frames': 48}]},
    {'segments': [{'source': 'official', 'start_frame': 0, 'frames': True}]},
    {'segments': [{'source': 'official', 'start_frame': 0, 'frames': gpu_worker.MAX_SECONDS * 24 + 1}]},
])
def test_rejects_unsafe_or_unbounded_edits(change):
    value = edit()
    value.update(change)
    with pytest.raises(ValueError):
        gpu_worker.manifest(value)


def test_bounds_total_duration_not_only_individual_segments():
    value = edit()
    value['segments'] *= 7201
    with pytest.raises(ValueError):
        gpu_worker.manifest(value)
    value['segments'] = [{'source': 'official', 'start_frame': 0, 'frames': gpu_worker.MAX_SECONDS * 24}] * 2
    with pytest.raises(ValueError, match='four hours'):
        gpu_worker.manifest(value)


def test_lock_prevents_two_workers_sharing_a_spool(tmp_path):
    with gpu_worker.single_worker(tmp_path):
        with pytest.raises(RuntimeError, match='Another worker'):
            with gpu_worker.single_worker(tmp_path):
                pytest.fail('Second renderer acquired the spool')
    with gpu_worker.single_worker(tmp_path):
        pass


def test_changed_source_fails_before_starting_ffmpeg(tmp_path):
    for name in ('sources', 'work', 'outputs'):
        (tmp_path / name).mkdir()
    source = tmp_path / 'sources' / ('a' * 64 + '.mp4')
    source.write_bytes(b'x' * 1024)
    assert hashlib.sha256(source.read_bytes()).hexdigest() != 'a' * 64
    with pytest.raises(ValueError, match='SHA256/size changed'):
        gpu_worker.render(tmp_path, 'b' * 32, edit(), '/must-not-run/ffmpeg', '/must-not-run/ffprobe')
    assert not list((tmp_path / 'outputs').iterdir())


def test_finished_outputs_cannot_be_overwritten(tmp_path):
    (tmp_path / 'outputs').mkdir()
    existing = tmp_path / 'outputs' / ('b' * 32 + '.mp4')
    existing.write_bytes(b'published')
    with pytest.raises(ValueError, match='already has a rendered output'):
        gpu_worker.render(tmp_path, 'b' * 32, edit(), 'ffmpeg', 'ffprobe')
    assert existing.read_bytes() == b'published'


def test_disk_budget_retains_existing_files(tmp_path, monkeypatch):
    retained = tmp_path / 'source.mp4'
    retained.write_bytes(b'original')
    monkeypatch.setattr(gpu_worker, 'MAX_DISK', 10)
    with pytest.raises(ValueError, match='disk budget'):
        gpu_worker.disk_admission(tmp_path, 10)
    assert retained.read_bytes() == b'original'


def test_rejects_hdr_and_non_normalized_sources():
    streams = [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080,
                'pix_fmt': 'yuv420p', 'r_frame_rate': '24/1'}]
    assert gpu_worker.check_video(streams)['width'] == 1920
    for patch in ({'color_transfer': 'smpte2084'}, {'color_primaries': 'bt2020'},
                  {'r_frame_rate': '30/1'}, {'avg_frame_rate': '24000/1001'}, {'start_time': '1'}, {'width': 1080}, {'side_data_list': [{'rotation': 90}]}):
        changed = copy.deepcopy(streams)
        changed[0].update(patch)
        with pytest.raises(ValueError):
            gpu_worker.check_video(changed)
