"""Transport behavior and authorization, without Docker or production access."""
import base64
import hashlib
import json
import threading
from unittest.mock import MagicMock

import pytest

from app_runtime.tests.test_api import client, headers
from app_runtime.tool_helpers import transfer_request, snapshot_request


def test_details_are_opt_in_and_do_not_leak_runtime_config(client):
    c, api, fake = client
    fake.inspect = MagicMock(return_value={'state': 'running', 'usage': {'memory_bytes': 23}})
    assert 'runtime' not in c.get('/api/apps', headers=headers('owner')).json()[0]
    fake.inspect.assert_not_called()
    result = c.get('/api/apps?details=true', headers=headers('viewer')).json()[0]
    assert result['runtime']['usage']['memory_bytes'] == 23
    fake.inspect.reset_mock()
    assert c.get('/api/apps?details=true', headers=headers('outsider')).json() == []
    fake.inspect.assert_not_called()
    api.inspection_cache.clear()
    fake.inspect.side_effect = RuntimeError('secret environment')
    result = c.get('/api/apps?details=true', headers=headers('owner'))
    assert 'secret' not in result.text
    assert result.json()[0]['runtime']['usage'] is None


def test_job_retry_reconnect_incremental_gap_and_cancel(client):
    c, api, fake = client
    entered, release = threading.Event(), threading.Event()
    calls = []
    def run(name, command, timeout, output, job_id=None):
        calls.append(command)
        output('first 🌿\n')
        entered.set()
        assert release.wait(5)
        output('last\n')
        return 130
    fake.run = run
    fake.cancel = lambda name, job: release.set()
    body = {'command': 'synthetic', 'idempotency_key': 'start-1'}
    base = '/api/apps/trip'
    job = c.post(base+'/exec', json=body, headers=headers('friend')).json()
    try:
        assert entered.wait(2)
        retry = c.post(base+'/exec', json=body, headers=headers('friend')).json()
        assert retry['id'] == job['id']
        assert len(calls) == 1
        assert c.post(base+'/exec', json={**body, 'command': 'different'}, headers=headers('friend')).status_code == 409
        url = base+'/jobs/'+job['id']
        first = c.get(url+'?after=0', headers=headers('friend')).json()
        assert first['output'] == 'first 🌿\n'
        assert 'request_hash' not in first and 'caller' not in first
        assert c.get(url+'?after='+str(first['next_cursor']), headers=headers('friend')).json()['output'] == ''
        assert c.get(url+'?after=99999', headers=headers('friend')).status_code == 422
        assert c.post(url+'/cancel', headers=headers('viewer')).status_code == 403
        assert c.post('/api/apps/other/jobs/'+job['id']+'/cancel', headers=headers('owner')).status_code == 404
        assert c.post(url+'/cancel', headers=headers('friend')).status_code == 200
    finally:
        release.set()
    # Wait for actual completion with a bounded event-style polling loop.
    import time
    for _ in range(100):
        result = c.get(url, headers=headers('friend')).json()
        if result['status'] != 'running': break
        time.sleep(.01)
    assert result['status'] == 'cancelled'
    tail = c.get(url+'?after='+str(first['next_cursor']), headers=headers('friend')).json()
    assert tail['output'] == 'last\n'
    assert c.post(url+'/cancel', headers=headers('friend')).json()['status'] == 'cancelled'
    saved = api.store.get(job['id'], 'jobs')
    saved.update(output='tail', bytes_seen=100000, truncated=True)
    api.store.put(saved, 'jobs')
    gap = c.get(url+'?after=0', headers=headers('friend')).json()
    assert gap['truncated'] and gap['output_start'] == 99996 and gap['next_cursor'] == 100000
    # Interrupted starts remain deduplicated across manager monitoring loss.
    saved['status'] = 'interrupted'
    api.store.put(saved, 'jobs')
    assert c.post(base+'/exec', json=body, headers=headers('friend')).json()['status'] == 'interrupted'
    assert calls == ['synthetic']


def test_file_binary_checksum_limits_and_authorization(client):
    c, api, fake = client
    data = bytes(range(256))*400
    sha = hashlib.sha256(data).hexdigest()
    fake.transfer = MagicMock(return_value={'size_bytes': len(data), 'sha256': sha})
    url = '/api/apps/trip/transfer?path=/workspace/archive.tgz&sha256='+sha
    for user, status in [('viewer',403), ('outsider',404), ('app',403)]:
        assert c.put(url, content=data, headers=headers(user)).status_code == status
    fake.transfer.assert_not_called()
    assert c.put(url, content=b'bad', headers=headers('friend')).status_code == 422
    fake.transfer.assert_not_called()
    assert c.put(url, content=data, headers=headers('friend')).status_code == 200
    fake.transfer.assert_called_once_with('trip','/workspace/archive.tgz',data)
    fake.transfer.return_value = {'content': data, 'sha256': sha}
    response = c.get('/api/apps/trip/transfer?path=/workspace/archive.tgz', headers=headers('friend'))
    assert response.content == data and response.headers['X-Content-SHA256'] == sha
    api.TRANSFER_LIMIT = 3
    assert c.put(url, content=data, headers=headers('friend')).status_code == 413


def test_snapshot_retry_cannot_repeat_destructive_restore(client):
    c, api, fake = client
    fake.container = MagicMock()
    fake.archive = MagicMock()
    args = {'json': {'idempotency_key': 'backup-1'}, 'headers': headers('owner')}
    first = c.post('/api/apps/trip/backups', **args)
    assert first.status_code == 201
    assert c.post('/api/apps/trip/backups', **args).json() == first.json()
    assert fake.archive.call_count == 1
    backup_id = first.json()['id']
    url = f'/api/apps/trip/backups/{backup_id}/restore'
    body = {'confirm_replace_data': True, 'idempotency_key': 'restore-1'}
    assert c.post(url, json=body, headers=headers('friend')).status_code == 403
    assert c.post(url, json=body, headers=headers('owner')).status_code == 200
    assert c.post(url, json=body, headers=headers('owner')).status_code == 200
    assert fake.archive.call_count == 2
    assert c.post('/api/apps/trip/backups/'+'a'*32+'/restore', json=body, headers=headers('owner')).status_code == 409
    # An unknown/failed outcome is never replayed automatically.
    fake.archive.side_effect = RuntimeError('private failure')
    body['idempotency_key'] = 'restore-2'
    assert c.post(url, json=body, headers=headers('owner')).status_code == 500
    assert c.post(url, json=body, headers=headers('owner')).status_code == 409
    assert fake.archive.call_count == 3


def test_transfer_and_snapshot_parameter_validation():
    data = b'\x00binary\xff'
    sha = hashlib.sha256(data).hexdigest()
    method, query, payload = transfer_request('/workspace/a b', 'upload', base64.b64encode(data).decode(), sha)
    assert method == 'PUT' and 'a+b' in query and payload == data
    for encoded, checksum in [('invalid@@',sha), (base64.b64encode(data).decode(),'wrong')]:
        with pytest.raises(ValueError): transfer_request('/workspace/a', 'upload', encoded, checksum)
    with pytest.raises(ValueError): snapshot_request('restore','key','a'*32,False)
    with pytest.raises(ValueError): snapshot_request('create',None,None,False)


def test_raw_snapshot_mutations_require_keys(client):
    c, _, fake = client
    fake.archive = MagicMock()
    assert c.post('/api/apps/trip/backups', headers=headers('owner')).status_code == 422
    assert c.post('/api/apps/trip/backups/'+'a'*32+'/restore',
        json={'confirm_replace_data': True}, headers=headers('owner')).status_code == 422
    fake.archive.assert_not_called()


def test_transfer_concurrency_limit(client):
    c, api, fake = client
    fake.transfer = MagicMock()
    assert api.transfer_slots.acquire(False)
    assert api.transfer_slots.acquire(False)
    try:
        assert c.get('/api/apps/trip/transfer?path=/workspace/a', headers=headers('friend')).status_code == 429
    finally:
        api.transfer_slots.release()
        api.transfer_slots.release()
    fake.transfer.assert_not_called()


def test_late_or_failed_cancel_does_not_report_successful_command_cancelled(client):
    c, api, fake = client
    job = {'id': 'late', 'app': 'trip', 'status': 'running', 'output': '',
           'bytes_seen': 0, 'truncated': False, 'cancel_requested': True}
    api.store.put(job, 'jobs')
    fake.run = lambda *args, **kwargs: 0
    api.execute_job(job, 'synthetic', 10)
    assert api.store.get('late','jobs')['status'] == 'finished'
    job['status'] = 'interrupted'
    api.store.put(job, 'jobs')
    fake.cancel = MagicMock()
    result = c.post('/api/apps/trip/jobs/late/cancel',headers=headers('friend'))
    assert result.status_code == 200 and result.json()['cancel_requested']
    fake.cancel.assert_called_once_with('trip','late')


def test_backup_known_rejection_replays_without_unknown_outcome(client):
    c, api, fake = client
    record = api.store.get('trip')
    record['db_password'] = 'legacy-never-return'
    api.store.put(record)
    args = {'json': {'idempotency_key': 'legacy-backup'}, 'headers': headers('owner')}
    first = c.post('/api/apps/trip/backups', **args)
    second = c.post('/api/apps/trip/backups', **args)
    assert first.status_code == second.status_code == 422
    assert first.json() == second.json()
    assert 'legacy-never-return' not in second.text


def test_mcp_binary_limit_fits_hosted_transport_body_protection():
    from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE
    from app_runtime.tool_helpers import MCP_TRANSFER_LIMIT
    data = b'a' * MCP_TRANSFER_LIMIT
    checksum = hashlib.sha256(data).hexdigest()
    encoded = base64.b64encode(data).decode()
    envelope = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
        'name': 'transfer_file', 'arguments': {'app': 'trip', 'path': '/workspace/source.tgz',
            'direction': 'upload', 'content_base64': encoded, 'sha256': checksum}}}
    assert len(json.dumps(envelope).encode()) < DEFAULT_MAX_REQUEST_BODY_SIZE
    assert transfer_request('/workspace/a', 'upload', encoded, checksum)[2] == data
    oversized = base64.b64encode(data+b'x').decode()
    with pytest.raises(ValueError, match='2 MiB'):
        transfer_request('/workspace/a', 'upload', oversized, hashlib.sha256(data+b'x').hexdigest())
    method, query, _ = transfer_request('/workspace/a','download',None,None)
    assert method == 'GET' and 'max_bytes=2097152' in query


def test_details_samples_are_cached_and_concurrency_bounded(client):
    c, api, fake = client
    fake.inspect = MagicMock(return_value={'state': 'running'})
    for _ in range(3):
        assert c.get('/api/apps?details=true',headers=headers('viewer')).json()[0]['runtime']['state']=='running'
    assert fake.inspect.call_count == 1
    api.inspection_cache.clear()
    api.inspection_slots.acquire()
    api.inspection_slots.acquire()
    try:
        result=c.get('/api/apps?details=true',headers=headers('viewer')).json()[0]
        assert result['runtime']['usage'] is None and 'busy' in result['runtime']['diagnostic']
    finally:
        api.inspection_slots.release()
        api.inspection_slots.release()


def test_transfer_busy_app_does_not_hold_global_slots(client):
    c, api, fake = client
    fake.transfer = MagicMock()
    with api.store.app_lock('trip'):
        response=c.get('/api/apps/trip/transfer?path=/workspace/a',headers=headers('friend'))
        assert response.status_code==409
    assert api.transfer_slots.acquire(False)
    assert api.transfer_slots.acquire(False)
    api.transfer_slots.release()
    api.transfer_slots.release()
    fake.transfer.assert_not_called()


def test_transfer_per_caller_limit_and_upload_deadline(client,monkeypatch):
    import asyncio
    c,api,fake=client
    fake.transfer=MagicMock()
    with api.transfer_slot('friend'):
        assert c.get('/api/apps/trip/transfer?path=/workspace/a',headers=headers('friend')).status_code==429
    async def slow_stream(self):
        await asyncio.sleep(.1)
        yield b''
    monkeypatch.setattr(api.Request,'stream',slow_stream)
    monkeypatch.setattr(api,'UPLOAD_BODY_TIMEOUT',.01)
    response=c.put('/api/apps/trip/transfer?path=/workspace/a&sha256='+hashlib.sha256(b'').hexdigest(),
                   content=b'',headers=headers('friend'))
    assert response.status_code==408
    fake.transfer.assert_not_called()
    assert api.transfer_user_slots['friend'].acquire(False)
    api.transfer_user_slots['friend'].release()


def test_invalid_snapshot_manifest_is_a_repeatable_rejection(client):
    c,api,fake=client
    backup_id='d'*32
    folder=api.state/'backups'/backup_id
    folder.mkdir(parents=True)
    (folder/'manifest.json').write_text('not json')
    fake.archive=MagicMock()
    url=f'/api/apps/trip/backups/{backup_id}/restore'
    args={'json':{'idempotency_key':'corrupt','confirm_replace_data':True},'headers':headers('owner')}
    assert c.post(url,**args).status_code==422
    assert c.post(url,**args).status_code==422
    fake.archive.assert_not_called()
    assert api.store.get('trip')['status']=='running'


def test_only_known_manager_errors_cross_the_oauth_bridge():
    import httpx
    from app_runtime.tool_helpers import manager_error
    response=httpx.Response(409,json={'detail':'Operation outcome is unknown; inspect snapshots and app before a new request'})
    assert 'unknown' in manager_error(response)
    assert manager_error(httpx.Response(422,json={'detail':'unexpected upstream secret'})) is None
    assert manager_error(httpx.Response(422,json={'detail':{'secret':'unexpected'}})) is None
