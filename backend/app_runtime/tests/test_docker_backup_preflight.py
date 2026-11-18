"""Missing helper image must never interrupt an existing app."""
import os
import time
import uuid

import pytest

from app_runtime.backups import Backups, BackupRejected
from app_runtime.core import Store
from app_runtime.tests.test_docker_ergonomics import sandbox as runtime_sandbox


@pytest.fixture
def sandbox(runtime_sandbox):
    # Exercise actual app provisioning rather than inheriting fixture labels.
    app = runtime_sandbox.container("trip")
    app.stop()
    app.rename(app.name + "-fixture")
    runtime_sandbox.client.networks.create(runtime_sandbox.prefix + "trip")
    try:
        runtime_sandbox.create_container({"name": "trip"}, "synthetic-token")
        yield runtime_sandbox
    finally:
        runtime_sandbox.container("trip").remove(force=True)
        runtime_sandbox.client.networks.get(runtime_sandbox.prefix + "trip").remove()

pytestmark = pytest.mark.skipif(os.environ.get('APPS_DOCKER_TESTS') != '1', reason='Requires local Docker')


def test_real_missing_image_backup_preserves_running_container(sandbox, tmp_path):
    app = sandbox.container('trip')
    started = app.attrs['State']['StartedAt']
    sandbox.image = 'cc-apps-missing-helper-' + uuid.uuid4().hex + ':test'
    store = Store(tmp_path / 'registry.sqlite3')
    store.put({'name': 'trip', 'status': 'running'})
    backups = Backups(store, sandbox, tmp_path)
    with pytest.raises(BackupRejected, match='app was not stopped'):
        backups.create(store.get('trip'))
    app.reload()
    assert app.status == 'running' and app.attrs['State']['StartedAt'] == started
    assert store.get('trip')['status'] == 'running'
    assert store.get('trip')['next_backup_at'] > time.time()


def test_runtime_image_is_marked_as_platform_managed(sandbox):
    assert sandbox.client.images.get(sandbox.image).labels.get('coolify.managed') == 'true'
    app = sandbox.container('trip')
    assert app.labels.get('coolify.managed') == 'false'


def test_real_archive_helper_roundtrip(sandbox):
    state = sandbox.client.volumes.create(sandbox.prefix + 'state')
    backup_id = uuid.uuid4().hex
    try:
        sandbox.client.containers.run(
            sandbox.image, ['bash', '-ec', 'mkdir -p /state/backups/' + backup_id],
            entrypoint='', remove=True, network_mode='none',
            labels={'coolify.managed': 'false'},
            volumes={state.name: {'bind': '/state', 'mode': 'rw'}},
        )
        app = sandbox.container('trip')
        assert app.exec_run(['bash', '-ec', 'printf original > /workspace/example.txt']).exit_code == 0
        image = sandbox.prepare_archive()
        sandbox.archive('trip', backup_id, image=image)
        assert app.exec_run(['bash', '-ec', 'printf changed > /workspace/example.txt']).exit_code == 0
        sandbox.archive('trip', backup_id, restore=True, image=image)
        assert app.exec_run(['cat', '/workspace/example.txt']).output == b'original'
    finally:
        state.remove(force=True)
