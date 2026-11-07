"""Opt-in local Docker acceptance checks, with isolated containers and synthetic data.

APPS_DOCKER_TESTS=1 python -m pytest app_runtime/tests/test_docker_ergonomics.py
"""
import base64
import hashlib
import os
import threading
import time
import uuid

import pytest

from app_runtime.docker_runtime import Runtime
from app_runtime import mcp_server
from app_runtime.tests.test_api import client, headers

pytestmark = pytest.mark.skipif(os.environ.get('APPS_DOCKER_TESTS') != '1', reason='Requires local Docker socket and runtime image')


@pytest.fixture
def sandbox():
    runtime = Runtime()
    runtime.prefix = 'cc-apps-ergonomics-' + uuid.uuid4().hex[:12] + '-'
    name = runtime.prefix + 'trip'
    volume = runtime.client.volumes.create(name + '-workspace')
    container = None
    try:
        container = runtime.client.containers.run(runtime.image, ['sleep', '300'], entrypoint='',
            name=name, detach=True, network_mode='none', mem_limit='128m', pids_limit=64,
            volumes={volume.name: {'bind': '/workspace', 'mode': 'rw'}})
        yield runtime
    finally:
        if container:
            container.remove(force=True)
        volume.remove(force=True)


def test_real_binary_transfer_cancel_timeout_and_inspection(sandbox):
    data = bytes(range(256)) * 8192  # 2 MiB, larger than shell argument and old file limits.
    metadata = sandbox.transfer('trip', '/workspace/nested/archive.tgz', data)
    assert metadata['sha256'] == hashlib.sha256(data).hexdigest()
    assert sandbox.transfer('trip', '/workspace/nested/archive.tgz')['content'] == data
    sandbox.container('trip').exec_run(['ln','-s','/etc/hosts','/workspace/escape'])
    with pytest.raises(ValueError): sandbox.transfer('trip','/workspace/escape')
    with pytest.raises(ValueError): sandbox.transfer('trip','/workspace/../etc/passwd')
    inspection = sandbox.inspect('trip')
    assert inspection['limits']['memory_bytes'] == 128 * 1024 * 1024
    assert inspection['usage']['memory_bytes'] > 0
    assert 'Env' not in str(inspection) and 'Mounts' not in str(inspection)
    output, done = [], threading.Event()
    job_id = uuid.uuid4().hex
    def run():
        output.append(sandbox.run('trip', "printf ready; (sleep 2; touch /workspace/leaked-child) & wait", 30, output.append, job_id))
        done.set()
    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 10
    while 'ready' not in output and time.monotonic() < deadline: time.sleep(.05)
    assert 'ready' in output
    sandbox.cancel('trip',job_id)
    assert done.wait(10)
    thread.join()
    assert output[-1] == 130
    time.sleep(2.1)
    assert sandbox.container('trip').exec_run(['test','!','-e','/workspace/leaked-child']).exit_code == 0
    assert sandbox.run('trip', 'sleep 30', 1, lambda _: None) == 124
    assert sandbox.run('trip', 'printf "🌿"', 10, output.append) == 0
    assert '🌿' in output


def test_real_mcp_api_disconnect_reconnect_and_binary_roundtrip(client, sandbox, monkeypatch):
    c, api, _ = client
    api.runtime = sandbox
    def call(method, path, data=None, *, content=None):
        response = c.request(method,path,json=data,content=content,headers=headers('friend'))
        response.raise_for_status()
        if method == 'GET' and '/transfer?' in path:
            from app_runtime.tool_helpers import transfer_response
            return transfer_response(response)
        return response.json()
    monkeypatch.setattr(mcp_server,'call',call)
    data = b'\x00synthetic archive\xff' * 10000
    encoded = base64.b64encode(data).decode()
    checksum = hashlib.sha256(data).hexdigest()
    assert mcp_server.transfer_file('trip','/workspace/upload.bin','upload',encoded,checksum)['sha256'] == checksum
    download = mcp_server.transfer_file('trip','/workspace/upload.bin','download')
    assert base64.b64decode(download['content_base64']) == data
    command = 'printf first; sleep 1; printf second'
    start = mcp_server.exec_command('trip',command,idempotency_key='once',wait_ms=0)
    retry = mcp_server.exec_command('trip',command,idempotency_key='once',wait_ms=0)
    assert retry['id'] == start['id']
    result = mcp_server.exec_command('trip',job_id=start['id'],wait_ms=5000)
    assert result['status'] == 'finished' and result['output'] == 'firstsecond'
    assert mcp_server.exec_command('trip',job_id=start['id'],after=result['next_cursor'])['output'] == ''


def test_stdio_protocol_reconnect_transfer_and_inventory(client, sandbox):
    import asyncio
    import json
    import socket
    import sys
    import uvicorn
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, api, _ = client
    api.runtime = sandbox
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, lifespan='off', log_level='error'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    async def exercise_protocol():
        parameters = StdioServerParameters(command=sys.executable, args=['-m','app_runtime.mcp_server'],
            env={**os.environ, 'COMMONS_URL': f'http://127.0.0.1:{port}', 'COMMONS_TOKEN': 'friend-key'})
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == {
                    'list_apps','create_app','set_app_member','exec_command','transfer_file','app_backups'}
                async def tool(name, args):
                    response = await session.call_tool(name,args)
                    assert not response.isError, response.content
                    if name == 'list_apps':
                        return [json.loads(block.text) for block in response.content]
                    return json.loads(response.content[0].text)
                inventory = await tool('list_apps',{'details':True})
                assert inventory[0]['runtime']['limits']['memory_bytes'] == 128*1024*1024
                content = b'\x00archive content\xff' * 100000
                encoded = base64.b64encode(content).decode()
                await tool('transfer_file',{'app':'trip','path':'/workspace/protocol.tgz','direction':'upload',
                    'content_base64':encoded,'sha256':hashlib.sha256(content).hexdigest()})
                downloaded = await tool('transfer_file',{'app':'trip','path':'/workspace/protocol.tgz','direction':'download'})
                assert base64.b64decode(downloaded['content_base64']) == content
                started = await tool('exec_command',{'app':'trip','command':'sleep 1; printf protocol',
                    'idempotency_key':'protocol-once','wait_ms':0})
                result = await tool('exec_command',{'app':'trip','job_id':started['id'],'wait_ms':5000})
                assert result['status'] == 'finished' and result['output'] == 'protocol'
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic()<deadline: time.sleep(.01)
        assert server.started
        asyncio.run(exercise_protocol())
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
