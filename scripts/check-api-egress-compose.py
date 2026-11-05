#!/usr/bin/env python3
"""Check JSON from Compose invoked with Coolify's repository project directory."""
import json
from pathlib import Path
import sys


def check(config: dict, root: Path) -> None:
    services = config['services']
    for name, service in services.items():
        if 'build' in service:
            assert Path(service['build']['context']) == root, f'{name}: context escaped repository root'
            assert (root / service['build']['dockerfile']).is_file(), f'{name}: missing Dockerfile'
        assert not service.get('env_file'), f'{name}: CLI-readable env_file is forbidden'
        for mount in service.get('volumes', []):
            if mount['type'] == 'bind':
                assert Path(mount['source']).is_absolute(), f'{name}: relative bind source'
                assert name == 'api', f'{name}: only API may have bind mounts'
                assert mount['read_only'], 'runtime secret must be read-only'
    api = services['api']
    assert api['network_mode'] == 'service:netguard'
    assert api['restart'] == 'no', 'API must not boot before firewall health ordering'
    assert 'networks' not in api
    mounts = api.get('volumes', [])
    assert len(mounts) == 1 and mounts[0]['target'] == '/run/secrets/api-runtime'
    assert mounts[0]['bind']['create_host_path'] is False
    assert api['entrypoint'] == ['python', '-m', 'api_egress_entrypoint']
    print('PASS Coolify Compose paths, daemon-only secret mount and API namespace')


if __name__ == '__main__':
    check(json.load(sys.stdin), Path(sys.argv[1]).resolve())
