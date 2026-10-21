import json
from unittest.mock import Mock

import pytest

from crowdset import gpu_updater as updater

SHA = 'a' * 40


def checks():
    return {'total_count': len(updater.REQUIRED), 'check_runs': [
        {'id': i, 'name': name, 'status': 'completed', 'conclusion': 'success', 'head_sha': SHA,
         'app': {'slug': 'github-actions'}} for i, name in enumerate(sorted(updater.REQUIRED), 1)]}


def test_release_requires_all_four_linux_ci_jobs():
    assert updater.REQUIRED == {'frontend', 'backend', 'crowdset-container', 'crowdset (ubuntu-latest)'}
    payload = checks()
    assert updater.approved(payload, SHA)
    for check in payload['check_runs']:
        missing = {**payload, 'check_runs': [c for c in payload['check_runs'] if c is not check]}
        assert not updater.approved(missing, SHA)


def test_only_latest_checks_from_actions_on_exact_head_can_approve():
    payload = checks()
    assert updater.approved(payload, SHA)
    assert not updater.approved(payload, 'b' * 40)
    cancelled = dict(payload['check_runs'][0], id=99, conclusion='cancelled')
    payload['check_runs'].append(cancelled)
    assert not updater.approved(payload, SHA)
    payload['check_runs'].append(dict(cancelled, id=100, conclusion='success'))
    assert updater.approved(payload, SHA)
    payload['check_runs'][1]['app'] = {'slug': 'some-other-app'}
    assert not updater.approved(payload, SHA)


@pytest.mark.parametrize('change', [
    {'status': 'queued', 'conclusion': None}, {'conclusion': 'skipped'}, {'conclusion': 'failure'},
])
def test_pending_failed_or_skipped_checks_never_deploy(change):
    payload = checks()
    payload['check_runs'][0].update(change)
    assert not updater.approved(payload, SHA)


def prepare(tmp_path, monkeypatch):
    for directory in ('data', 'units', 'incoming'):
        (tmp_path / directory).mkdir()
    monkeypatch.setattr(updater, 'destination', lambda root, name: root / 'units' / name)
    for name in updater.FILES:
        (tmp_path / 'units' / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / 'incoming' / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / 'units' / name).write_bytes(b'old ' + name.encode())
        (tmp_path / 'incoming' / name).write_bytes(b'new ' + name.encode())
    (tmp_path / 'data' / 'original.mp4').write_bytes(b'original media')
    updater.record(tmp_path / 'deployment.json', {'sha': 'b' * 40})
    return {'sha': SHA, 'phase': 'staged'}


def test_active_render_is_left_running_and_update_waits(tmp_path, monkeypatch):
    pending = prepare(tmp_path, monkeypatch)
    control = Mock(side_effect=AssertionError('Must not stop a busy render'))
    monkeypatch.setattr(updater, 'control', control)
    monkeypatch.setattr(updater, 'wait_paused', lambda root: False)
    updater.record(tmp_path / 'pending-update.json', pending)
    updater.deploy(tmp_path, pending)
    assert (tmp_path / 'data/update-requested').exists()
    assert json.loads((tmp_path / 'update-status.json').read_text())['state'] == 'waiting_for_render'
    assert (tmp_path / 'units/gpu_worker.py').read_bytes() == b'old gpu_worker.py'
    assert not control.called


def test_successful_update_retains_media_and_records_commit(tmp_path, monkeypatch):
    pending = prepare(tmp_path, monkeypatch)
    updater.record(tmp_path / 'pending-update.json', pending)
    monkeypatch.setattr(updater, 'wait_paused', lambda root: True)
    control = Mock()
    monkeypatch.setattr(updater, 'control', control)
    monkeypatch.setattr(updater, 'healthy', lambda root: True)
    updater.deploy(tmp_path, pending)
    assert (tmp_path / 'units/gpu_worker.py').read_bytes() == b'new gpu_worker.py'
    assert json.loads((tmp_path / 'deployment.json').read_text())['sha'] == SHA
    assert (tmp_path / 'rollback/gpu_worker.py').read_bytes() == b'old gpu_worker.py'
    assert not (tmp_path / 'data/update-requested').exists()
    assert not (tmp_path / 'pending-update.json').exists()
    assert (tmp_path / 'data/original.mp4').read_bytes() == b'original media'
    assert control.call_args_list[0].args == ('stop', updater.SERVICE)


def test_failed_start_rolls_back_code_and_keeps_previous_deployment(tmp_path, monkeypatch):
    pending = prepare(tmp_path, monkeypatch)
    updater.record(tmp_path / 'pending-update.json', pending)
    monkeypatch.setattr(updater, 'wait_paused', lambda root: True)
    monkeypatch.setattr(updater, 'control', Mock())
    monkeypatch.setattr(updater, 'healthy', Mock(side_effect=[False, True]))
    with pytest.raises(RuntimeError, match='startup health'):
        updater.deploy(tmp_path, pending)
    assert (tmp_path / 'units/gpu_worker.py').read_bytes() == b'old gpu_worker.py'
    assert json.loads((tmp_path / 'deployment.json').read_text())['sha'] == 'b' * 40
    assert json.loads((tmp_path / 'update-status.json').read_text())['failed_sha'] == SHA
    assert not (tmp_path / 'data/update-requested').exists()
    assert (tmp_path / 'data/original.mp4').read_bytes() == b'original media'


def test_interrupted_install_recovers_backup_without_network(tmp_path, monkeypatch):
    pending = prepare(tmp_path, monkeypatch)
    (tmp_path / 'rollback').mkdir()
    for name in updater.FILES:
        (tmp_path / 'rollback' / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / 'rollback' / name).write_bytes(b'backup ' + name.encode())
    updater.record(tmp_path / 'pending-update.json', dict(pending, phase='installing'))
    monkeypatch.setattr(updater, 'get', Mock(side_effect=AssertionError('Recovery must work offline')))
    monkeypatch.setattr(updater, 'control', Mock())
    monkeypatch.setattr(updater, 'healthy', lambda root: True)
    updater.update(tmp_path)
    assert (tmp_path / 'units/gpu_worker.py').read_bytes() == b'backup gpu_worker.py'
    assert (tmp_path / 'data/original.mp4').read_bytes() == b'original media'


def test_failed_release_is_not_retried_until_main_changes(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    updater.record(tmp_path / 'update-status.json', {'state': 'rolled_back', 'failed_sha': SHA})
    get = Mock(return_value=json.dumps({'sha': SHA}).encode())
    monkeypatch.setattr(updater, 'get', get)
    updater.update(tmp_path)
    assert get.call_count == 1
    assert not (tmp_path / 'data/update-requested').exists()


def test_new_worker_is_healthy_while_processing_queued_jobs(tmp_path, monkeypatch):
    import time
    (tmp_path / 'data').mkdir()
    updater.record(tmp_path / 'data/status.json', {'state': 'rendering', 'pid': 42, 'updated_at': time.time()})
    monkeypatch.setattr(updater, 'running_pid', lambda: 42)
    assert updater.healthy(tmp_path, seconds=0.1)


def test_expanded_bundle_adds_new_modules_before_stopping_service(tmp_path, monkeypatch):
    pending = prepare(tmp_path, monkeypatch)
    modules = [name for name in updater.FILES if name.startswith('crowdset/')]
    for name in modules:
        (tmp_path / 'units' / name).unlink()
    monkeypatch.setattr(updater, 'wait_paused', lambda root: True)
    def control(*args):
        if args == ('stop', updater.SERVICE):
            assert all((tmp_path / 'units' / name).exists() for name in modules)
    monkeypatch.setattr(updater, 'control', control)
    monkeypatch.setattr(updater, 'healthy', lambda root: True)
    updater.record(tmp_path / 'pending-update.json', pending)
    updater.deploy(tmp_path, pending)
    assert (tmp_path / 'units/crowdset/youtube.py').read_bytes() == b'new crowdset/youtube.py'
    assert (tmp_path / 'data/original.mp4').read_bytes() == b'original media'


def test_worker_can_be_healthy_while_waiting_for_control_plane(tmp_path, monkeypatch):
    import time
    (tmp_path / 'data').mkdir()
    updater.record(tmp_path / 'data/status.json', {'state': 'offline', 'pid': 42, 'updated_at': time.time()})
    monkeypatch.setattr(updater, 'running_pid', lambda: 42)
    assert updater.healthy(tmp_path, seconds=0.1)
