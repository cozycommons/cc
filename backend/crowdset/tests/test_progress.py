import json

from crowdset.progress import snapshot


def test_render_progress_combines_segments_and_ignores_incomplete_writes(tmp_path):
    folder = tmp_path / 'video-test'
    folder.mkdir()
    telemetry = folder / '1-progress.txt'
    telemetry.write_text('frame=240\nfps=24.0\nout_time_us=10000000\nprogress=continue\nframe=480\nfps=24.0\n')
    (tmp_path / 'progress.json').write_text(json.dumps({
        'stage': 'Rendering video…', 'processing': {'phase': 'render', 'started_at': 100},
        'render': {'file': 'video-test/1-progress.txt', 'completed_frames': 240, 'segment_frames': 720, 'total_frames': 960},
    }))
    value = snapshot(tmp_path)
    assert value['processing']['percent'] == 50
    assert value['processing']['completed'] == 480
    assert value['processing']['remaining_seconds'] == 20
    assert 'render' not in value
    telemetry.write_text('frame=720\nfps=0.0\nprogress=end\n')
    value = snapshot(tmp_path)
    assert value['processing']['percent'] == 100
    assert 'remaining_seconds' not in value['processing']
    telemetry.unlink()
    assert snapshot(tmp_path)['processing']['phase'] == 'render'
    assert 'percent' not in snapshot(tmp_path)['processing']


def test_progress_keeps_legacy_stage_and_never_reads_outside_set(tmp_path):
    path = tmp_path / 'progress.json'
    path.write_text('{')
    assert snapshot(tmp_path) == {}
    path.write_text(json.dumps({'stage': 'Rendering video…'}))
    assert snapshot(tmp_path) == {'stage': 'Rendering video…'}
    path.write_text(json.dumps({'stage': 'Rendering video…', 'processing': {'phase': 'render'},
                               'render': {'file': '../outside.txt'}}))
    assert snapshot(tmp_path) == {'stage': 'Rendering video…', 'processing': {'phase': 'render'}}
