from unittest.mock import MagicMock

from app_runtime.docker_runtime import Runtime
from app_runtime.git_inspection import (
    GIT_INSPECTION_SCRIPT,
    INSPECTION_TIMEOUT,
    INSPECTION_WALL_TIMEOUT,
)


def test_provisioning_only_connects_proxy_and_injects_no_database(monkeypatch):
    client = MagicMock()
    client.containers.get.return_value.exec_run.return_value.exit_code = 0
    monkeypatch.setattr("app_runtime.docker_runtime.docker.from_env", lambda: client)
    runtime = Runtime()  # Does not require a Postgres password in the environment.
    runtime.create({"name": "fresh"}, "app-token")
    client.networks.create.return_value.connect.assert_called_once_with(
        "cc-apps-local-proxy", aliases=["proxy"]
    )
    assert client.containers.run.call_args.kwargs["labels"]["coolify.managed"] == "false"
    environment = client.containers.run.call_args.kwargs["environment"]
    assert set(environment) == {"COMMONS_APP", "COMMONS_APP_TOKEN", "COMMONS_CONTROL_URL"}
    assert client.containers.run.call_args.kwargs["volumes"] == {
        "cc-apps-local-fresh-workspace": {"bind": "/workspace", "mode": "rw"}
    }


def test_inspection_uses_one_shot_and_does_not_invent_cpu_sample(monkeypatch):
    client=MagicMock()
    monkeypatch.setattr('app_runtime.docker_runtime.docker.from_env',lambda:client)
    runtime=Runtime()
    container=client.containers.get.return_value
    container.attrs={'State':{'Status':'running','Running':True},'HostConfig':{'Memory':512},'RestartCount':0}
    container.stats.return_value={'cpu_stats':{'system_cpu_usage':100,'cpu_usage':{'total_usage':10}},
                                  'memory_stats':{'usage':10}}
    result=runtime.inspect('trip')
    container.stats.assert_called_once_with(stream=False,one_shot=True)
    assert result['usage']['cpu_percent'] is None
    assert result['usage']['memory_bytes']==10


def test_changes_uses_fixed_helper_and_workspace(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr('app_runtime.docker_runtime.docker.from_env', lambda: client)
    runtime = Runtime()
    calls = []
    expected = b'{"repositories":[],"truncated":false}'

    def fake_exec(name, command, seconds, on_output):
        calls.append((name, command, seconds))
        on_output(expected)
        return 0

    monkeypatch.setattr(runtime, '_exec', fake_exec)
    assert runtime.changes('trip') == {'repositories': [], 'truncated': False}
    assert calls == [(
        'trip',
        [
            '/usr/bin/timeout',
            '--signal=TERM',
            '--kill-after=1s',
            INSPECTION_WALL_TIMEOUT,
            'python',
            '-c',
            GIT_INSPECTION_SCRIPT,
            '/workspace',
        ],
        INSPECTION_TIMEOUT,
    )]


def test_proxy_network_reconciliation_checks_labels_and_skips_existing(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr('app_runtime.docker_runtime.docker.from_env', lambda: client)
    runtime = Runtime()
    proxy = client.containers.get.return_value
    proxy.attrs = {'NetworkSettings': {'Networks': {runtime.prefix + 'existing': {}}}}
    network = client.networks.get.return_value
    network.attrs = {'Labels': {'cc.apps.instance': runtime.prefix, 'cc.apps': 'trip'}}
    runtime.reconcile_proxy_networks([{'name': 'new', 'status': 'creating'}, {'name': 'existing'}, {'name': 'trip'}])
    client.networks.get.assert_called_once_with(runtime.prefix + 'trip')
    network.connect.assert_called_once_with(proxy, aliases=['proxy'])
    network.connect.reset_mock()
    network.attrs['Labels']['cc.apps.instance'] = 'another-instance'
    runtime.reconcile_proxy_networks([{'name': 'trip'}])
    network.connect.assert_not_called()


def test_archive_preflight_resolves_local_image_without_pull(monkeypatch):
    import pytest
    client = MagicMock()
    monkeypatch.setattr('app_runtime.docker_runtime.docker.from_env', lambda: client)
    runtime = Runtime()
    client.images.get.return_value.id = 'sha256:trusted'
    assert runtime.prepare_archive() == 'sha256:trusted'
    client.images.get.assert_called_once_with(runtime.image)
    client.images.pull.assert_not_called()
    client.images.get.side_effect = RuntimeError('private daemon details')
    with pytest.raises(RuntimeError, match='Backup helper image is unavailable') as error:
        runtime.prepare_archive()
    assert 'private' not in str(error.value)
    client.containers.run.assert_not_called()


def test_archive_uses_pinned_preflight_image_instead_of_mutable_tag(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr('app_runtime.docker_runtime.docker.from_env', lambda: client)
    runtime = Runtime()
    client.containers.create.return_value.wait.return_value = {'StatusCode': 0}
    runtime.archive('trip', 'a' * 32, image='sha256:checked-before-stop')
    assert client.containers.create.call_args.args[0] == 'sha256:checked-before-stop'
    assert client.containers.create.call_args.kwargs['network_mode'] == 'none'
    client.images.pull.assert_not_called()


def test_archive_failure_cleans_helper_and_never_pulls(monkeypatch):
    import pytest
    client = MagicMock()
    monkeypatch.setattr('app_runtime.docker_runtime.docker.from_env', lambda: client)
    runtime = Runtime()
    helper = client.containers.create.return_value
    helper.wait.return_value = {'StatusCode': 1}
    with pytest.raises(RuntimeError, match='Workspace archive helper failed'):
        runtime.archive('trip', 'a' * 32, image='sha256:trusted')
    assert client.containers.create.call_args.kwargs['labels']['coolify.managed'] == 'false'
    helper.remove.assert_called_once_with(force=True)
    client.images.pull.assert_not_called()
    client.containers.create.side_effect = RuntimeError('image disappeared')
    with pytest.raises(RuntimeError):
        runtime.archive('trip', 'a' * 32, image='sha256:trusted')
    client.images.pull.assert_not_called()
