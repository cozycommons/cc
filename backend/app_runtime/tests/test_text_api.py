"""Authenticated text endpoints exercise actual temporary workspace outcomes."""
import threading
from unittest.mock import MagicMock

from app_runtime.tests.test_api import client, headers
from app_runtime import text_files as tf


def test_text_endpoints_require_contributor_recheck_ready_and_return_fixed_errors(client, tmp_path):
    c, api, runtime = client
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    runtime.text = MagicMock(side_effect=lambda name, op, body: tf.operate(workspace, op, body))
    body = {'path': 'test', 'content': 'hello\r\n', 'expected_sha256': None}
    url = '/api/apps/trip/text/write'
    assert c.post(url, json=body, headers=headers('viewer')).status_code == 403
    assert c.post(url, json=body, headers=headers('outsider')).status_code == 404
    runtime.text.assert_not_called()
    result = c.post(url, json=body, headers=headers('friend'))
    assert result.status_code == 200 and (workspace / 'test').read_bytes() == b'hello\r\n'
    assert c.post(url, json=body, headers=headers('friend')).json()['detail']['code'] == 'ALREADY_EXISTS'
    response = c.post('/api/apps/trip/text/read', json={'files': [{'path': 'test'}]}, headers=headers('friend'))
    assert response.json()['files'][0]['newline_style'] == 'CRLF'
    record = api.store.get('trip')
    record['status'] = 'maintenance'
    api.store.put(record)
    runtime.text.reset_mock()
    assert c.post(url, json=body, headers=headers('friend')).status_code == 409
    runtime.text.assert_not_called()


def test_text_body_bounds_and_invalid_arguments_do_not_echo_content(client):
    c, _, runtime = client
    runtime.text = MagicMock()
    for body in [b'{"secret": "private token"}', b'{broken private token']:
        result = c.post('/api/apps/trip/text/write', content=body, headers=headers('friend'))
        assert result.status_code == 422 and 'private token' not in result.text
    result = c.post('/api/apps/trip/text/write', content=b'x' * (tf.REQUEST_LIMIT + 1), headers=headers('friend'))
    assert result.status_code == 413 and result.json()['detail']['code'] == 'INPUT_TOO_LARGE'
    runtime.text.assert_not_called()


def test_structured_writer_holds_app_lock_and_conflicting_writer_retries(client, tmp_path):
    c, _, runtime = client
    entered, release = threading.Event(), threading.Event()
    def blocked(name, op, body):
        entered.set()
        assert release.wait(5)
        return {'done': True}
    runtime.text = MagicMock(side_effect=blocked)
    result = []
    body = {'path': 'x', 'content': 'hello', 'expected_sha256': None}
    first = threading.Thread(target=lambda: result.append(c.post('/api/apps/trip/text/write', json=body, headers=headers('friend'))))
    first.start()
    try:
        assert entered.wait(5)
        second = c.post('/api/apps/trip/text/write', json=body, headers=headers('owner'))
        assert second.status_code == 409
        assert runtime.text.call_count == 1
    finally:
        release.set()
        first.join(5)
    assert result[0].status_code == 200


def test_text_rejects_before_consuming_body_when_slot_or_auth_denied(client):
    import asyncio
    import pytest
    from fastapi import HTTPException
    _, api, runtime = client
    runtime.text = MagicMock()
    class RequestProbe:
        consumed = False
        async def stream(self):
            self.consumed = True
            yield b'{"files":[{"path":"x"}]}'
    def rejected(who, status):
        request = RequestProbe()
        with pytest.raises(HTTPException) as error:
            asyncio.run(api.text_operation('trip', 'read', request, who))
        assert error.value.status_code == status
        assert not request.consumed
    rejected('viewer', 403)
    with api.transfer_slot('friend'):
        rejected('friend', 429)
    with api.transfer_slot('one'), api.transfer_slot('two'):
        rejected('friend', 429)
    runtime.text.assert_not_called()
    assert not api.transfer_users
