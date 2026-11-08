from unittest.mock import MagicMock

from app_runtime.docker_runtime import Runtime


def test_provisioning_only_connects_proxy_and_injects_no_database(monkeypatch):
    client = MagicMock()
    client.containers.get.return_value.exec_run.return_value.exit_code = 0
    monkeypatch.setattr("app_runtime.docker_runtime.docker.from_env", lambda: client)
    runtime = Runtime()  # Does not require a Postgres password in the environment.
    runtime.create({"name": "fresh"}, "app-token")
    client.networks.create.return_value.connect.assert_called_once_with(
        "cc-apps-local-proxy", aliases=["proxy"]
    )
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
