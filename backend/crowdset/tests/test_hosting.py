import hashlib
import httpx
import pytest
from fastapi.testclient import TestClient

from crowdset.app import create_app
from crowdset.hosting import COOKIE
from crowdset.store import Store


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    monkeypatch.setenv('CROWDSET_ORIGIN', 'https://commons.example')
    monkeypatch.setenv('CROWDSET_AUTH_URL', 'https://test.supabase.co')
    monkeypatch.setenv('CROWDSET_AUTH_KEY', 'sb_publishable_test')
    monkeypatch.setenv('CROWDSET_DATA_DIR', str(tmp_path))
    first, second = '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'
    original = httpx.AsyncClient
    admin_roles = {'Bearer admin': True}
    auth_failures, auth_calls, clients = [], [], []

    def auth(request):
        if request.url.path == '/rest/v1/commons_user_roles':
            token = request.headers['authorization']
            return httpx.Response(200, json=[{'role': 'admin'}] if admin_roles.get(token) is True else [])
        assert request.url == 'https://test.supabase.co/auth/v1/user'
        assert request.headers['apikey'] == 'sb_publishable_test'
        token = request.headers['authorization']
        auth_calls.append(token)
        if auth_failures:
            failure = auth_failures.pop(0)
            if isinstance(failure, int):
                return httpx.Response(failure)
            raise failure('Simulated verification failure', request=request)
        if token == 'Bearer unavailable':
            return httpx.Response(503)
        if token not in ('Bearer first', 'Bearer second', 'Bearer anonymous', 'Bearer third', 'Bearer admin'):
            return httpx.Response(401)
        return httpx.Response(200, json={'id': '44444444-4444-4444-8444-444444444444' if token == 'Bearer admin' else first if token == 'Bearer first' else ('33333333-3333-4333-8333-333333333333' if token == 'Bearer third' else second),
                                       'is_anonymous': token == 'Bearer anonymous', 'email_confirmed_at': '2026-01-01',
                                       'app_metadata': {'crowdset_admin': admin_roles.get(token)},
                                       'email': 'private@example.com', 'user_metadata': {'full_name': 'Alice' if token == 'Bearer first' else '  Bob  Friend  ', 'id': first, 'role': 'admin', 'crowdset_admin': True}})

    def client(**kwargs):
        value = original(transport=httpx.MockTransport(auth), **kwargs)
        clients.append(value)
        return value

    monkeypatch.setattr('crowdset.hosting.httpx.AsyncClient', client)
    # Local files never become publicly owned when a checkout is hosted.
    store = Store(tmp_path)
    store.create('Local only')
    legacy = store.create('Legacy private', owner=first)
    legacy.pop('visibility')
    store.save(legacy)
    store.close()
    with TestClient(create_app(), base_url='https://commons.example') as api:
        api.app.state.test_admin_roles = admin_roles
        api.app.state.test_auth_failures = auth_failures
        api.app.state.test_auth_calls = auth_calls
        api.app.state.test_auth_clients = clients
        yield api
    assert all(client.is_closed for client in clients)


@pytest.mark.parametrize('failure', [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError, 429, 503, 504])
def test_upload_recovers_from_transient_auth_failure_between_chunks(hosted, monkeypatch, failure, caplog):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    monkeypatch.setattr('crowdset.store.probe', lambda *args, **kwargs: 5)
    headers = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    path = '/crowdset/sets/' + hosted.post('/crowdset/sets', headers=headers, json={'name': 'Resume'}).json()['id']
    batch = hosted.post(path + '/batches', headers=headers).json()['id']
    fingerprint = hashlib.sha256(b'abcdef').hexdigest()
    upload = hosted.post(path + '/uploads', headers=headers, json={
        'name': 'clip.wav', 'size': 6, 'fingerprint': fingerprint, 'batch_id': batch,
    }).json()
    route = path + '/uploads/' + upload['id']
    checksum = hashlib.sha256(b'abc').hexdigest()
    assert hosted.patch(route + '?offset=0&checksum=' + checksum, headers=headers, content=b'abc').status_code == 200
    hosted.app.state.test_auth_failures.append(failure)
    hosted.app.state.test_auth_calls.clear()
    checksum = hashlib.sha256(b'def').hexdigest()
    response = hosted.patch(route + '?offset=3&checksum=' + checksum, headers=headers, content=b'def')
    assert response.status_code == 200 and response.json()['offset'] == 6
    assert hosted.app.state.test_auth_calls == ['Bearer first', 'Bearer first']
    assert len(hosted.app.state.test_auth_clients) == 1
    assert 'verification attempt 1/3 failed' in caplog.text
    assert 'Bearer first' not in caplog.text
    saved = hosted.post(route + '/finish', headers=headers)
    assert saved.status_code == 200
    clip = saved.json()['clips'][0]
    store = hosted.app.state.store
    assert store.originals.path(path.rsplit('/', 1)[1], clip).read_bytes() == b'abcdef'
    assert hosted.post(path + '/batches/' + batch + '/finish', headers=headers).status_code == 200


def test_auth_outage_keeps_saved_offset_and_retry_resumes_same_upload(hosted, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    headers = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    path = '/crowdset/sets/' + hosted.post('/crowdset/sets', headers=headers, json={'name': 'Outage'}).json()['id']
    body = {'name': 'clip.wav', 'size': 6, 'fingerprint': 'a' * 64}
    upload = hosted.post(path + '/uploads', headers=headers, json=body).json()
    route = path + '/uploads/' + upload['id']
    checksum = hashlib.sha256(b'abc').hexdigest()
    assert hosted.patch(route + '?offset=0&checksum=' + checksum, headers=headers, content=b'abc').status_code == 200
    hosted.app.state.test_auth_failures.extend([httpx.ReadTimeout] * 3)
    hosted.app.state.test_auth_calls.clear()
    checksum = hashlib.sha256(b'def').hexdigest()
    response = hosted.patch(route + '?offset=3&checksum=' + checksum, headers=headers, content=b'def')
    assert response.status_code == 503
    assert 'progress is retained' in response.json()['detail']
    assert len(hosted.app.state.test_auth_calls) == 3
    resumed = hosted.post(path + '/uploads', headers=headers, json=body).json()
    assert resumed['id'] == upload['id'] and resumed['offset'] == 3
    assert hosted.patch(route + '?offset=3&checksum=' + checksum, headers=headers, content=b'def').json()['offset'] == 6
    other = {**headers, 'Authorization': 'Bearer second'}
    assert hosted.get(route, headers=other).status_code == 403


@pytest.mark.parametrize('status', [401, 403])
def test_rejected_credentials_are_not_retried(hosted, status):
    hosted.app.state.test_auth_failures.append(status)
    hosted.app.state.test_auth_calls.clear()
    assert hosted.get('/crowdset/sets', headers={'Authorization': 'Bearer first'}).status_code == 401
    assert hosted.app.state.test_auth_calls == ['Bearer first']


def test_hosted_auth_origin_cookie_and_owner_isolation(hosted):
    api = hosted
    route = '/crowdset/sets'
    first = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    second = {'Authorization': 'Bearer second', 'Origin': 'https://commons.example'}
    assert api.get(route).status_code == 401
    assert api.get(route, headers={**first, 'Host': 'evil.example'}).status_code == 403
    assert api.post(route, headers={'Authorization': 'Bearer first'}, json={'name': 'No origin'}).status_code == 403
    assert api.post(route, headers={**first, 'Origin': 'https://evil.example'}, json={'name': 'Bad origin'}).status_code == 403
    assert [s['name'] for s in api.get(route, headers=first).json()] == ['Legacy private']
    result = api.post(route, headers=first, json={'name': 'Owned'})
    assert result.status_code == 201
    cookie = result.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/crowdset' in cookie
    path = route + '/' + result.json()['id']
    assert api.get(path).status_code == 200
    assert api.get(path, headers={'Authorization': 'Bearer expired'}).status_code == 401
    assert api.post(path + '/process', headers={'Origin': 'https://commons.example'}).status_code == 401
    third = {'Authorization': 'Bearer third', 'Origin': 'https://commons.example'}
    assert api.get(path, headers=second).status_code == 200
    assert not api.get(path, headers=second).json()['can_manage']
    assert [s['name'] for s in api.get(route, headers=second).json()] == ['Owned']
    legacy_path = route + '/' + next(s['id'] for s in api.get(route, headers=first).json() if s['name'] == 'Legacy private')
    for method, suffix in [('GET', ''), ('GET', '/audio'), ('GET', '/video'), ('GET', '/clips/abc/media'), ('POST', '/process'),
                           ('DELETE', ''), ('POST', '/youtube'), ('PATCH', '/clips/abc'), ('PUT', '/clips?name=x.wav')]:
        assert api.request(method, legacy_path + suffix, headers=second).status_code == 404
    batch = api.post(path + '/batches', headers=second).json()['id']
    assert api.post(path + '/batches/' + batch + '/finish', headers=third).status_code == 403
    uploaded = api.put(path + '/clips?name=video.mp4&batch_id=' + batch, headers=second, content=b'original video bytes')
    assert uploaded.status_code == 201
    assert api.post(path + '/batches/' + batch + '/finish', headers=second).status_code == 200
    clip = uploaded.json()['clips'][0]
    assert clip['uploader'] == '22222222-2222-4222-8222-222222222222'
    assert clip['can_edit']
    media = path + '/clips/' + clip['id'] + '/media'
    response = api.get(media, headers={**third, 'Range': 'bytes=0-7'})
    assert response.status_code == 206 and response.content == b'original'
    assert response.headers['content-type'] == 'video/mp4'
    assert api.patch(path + '/clips/' + clip['id'], headers=third, json={'included': False}).status_code == 403
    assert api.delete(path + '/clips/' + clip['id'], headers=third).status_code == 403
    assert api.delete(path, headers=second).status_code == 403
    assert api.patch(path + '/clips/' + clip['id'], headers=second, json={'included': False}).status_code == 200
    assert api.delete(path, headers=first).status_code == 403
    assert api.delete(path + '/clips/' + clip['id'], headers=first).status_code == 403
    assert not api.get(path, headers=first).json()['clips'][0]['can_delete']
    assert api.delete(path + '/clips/' + clip['id'], headers=second).status_code == 200
    assert api.get(media, headers=third).status_code == 404
    assert api.get(path, headers=second).json()['clips'] == []
    assert 'deleted_clips' not in api.get(path, headers=first).json()
    retained = api.app.state.store.get(path.rsplit('/', 1)[1])['deleted_clips'][0]
    assert api.app.state.store.originals.path(path.rsplit('/', 1)[1], retained).read_bytes() == b'original video bytes'
    api.cookies.clear()
    assert api.get(media).status_code == 401
    assert api.get(path + '/audio').status_code == 401
    assert api.get(path + '/video').status_code == 401
    assert api.post(path + '/youtube', headers={'Origin': 'https://commons.example'}, json={'url': 'https://youtu.be/9dhFH_G5Bow'}).status_code == 401
    assert api.get(route, headers={'Authorization': 'Bearer anonymous'}).status_code == 403
    assert api.get(route, headers={'Authorization': 'Bearer unavailable'}).status_code == 503
    assert api.delete('/crowdset/session', headers={'Origin': 'https://commons.example'}).status_code == 204
    assert api.get(route).status_code == 401


def test_hosted_settings_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('CROWDSET_ORIGIN', 'https://commons.example')
    monkeypatch.delenv('CROWDSET_AUTH_KEY', raising=False)
    with pytest.raises(RuntimeError, match='requires'):
        create_app(tmp_path)


def test_only_owner_can_choose_soundtrack(hosted, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    owner = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    friend = {'Authorization': 'Bearer second', 'Origin': 'https://commons.example'}
    created = hosted.post('/crowdset/sets', headers=owner, json={'name': 'Official set'}).json()
    path = '/crowdset/sets/' + created['id']
    added = hosted.put(path + '/clips?name=official.mp4', headers=friend, content=b'video').json()
    clip_id = added['clips'][0]['id']
    assert hosted.put(path + '/soundtrack', headers=friend, json={'clip_id': clip_id}).status_code == 403
    assert hosted.put(path + '/soundtrack', headers=owner, json={'clip_id': clip_id}).json()['soundtrack_clip_id'] == clip_id
    assert hosted.put(path + '/soundtrack', headers=friend, json={'clip_id': None}).status_code == 403
    assert hosted.delete(path + '/clips/' + clip_id, headers=owner).status_code == 403
    assert hosted.delete(path + '/clips/' + clip_id, headers=friend).json()['soundtrack_clip_id'] is None


def test_legacy_routes_redirect_pages_and_keep_authenticated_api_and_media_working(hosted):
    first = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    assert hosted.get('/crowd-set?view=clips', follow_redirects=False).headers['location'] == '/crowdset?view=clips'
    assert hosted.get('/crowd-set/sets').status_code == 401
    created = hosted.post('/crowd-set/sets', headers=first, json={'name': 'Legacy browser tab'})
    assert created.status_code == 201
    cookies = created.headers.get_list('set-cookie')
    assert any('__Secure-crowdset=' in c and 'Path=/crowdset' in c for c in cookies)
    assert any('__Secure-crowd-set=' in c and 'Path=/crowd-set' in c for c in cookies)
    path = '/crowd-set/sets/' + created.json()['id']
    uploaded = hosted.put(path + '/clips?name=video.mp4', headers=first, content=b'original video')
    clip_id = uploaded.json()['clips'][0]['id']
    media = path + '/clips/' + clip_id + '/media'
    assert hosted.get(media, headers={'Range': 'bytes=0-7'}).content == b'original'
    assert hosted.get(media.replace('/crowd-set/', '/crowdset/'), headers={'Range': 'bytes=0-7'}).content == b'original'
    assert hosted.delete(path + '/clips/' + clip_id, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert hosted.get('/crowd-set/health', headers={'Host': 'evil.example'}).status_code == 403
    logout = hosted.delete('/crowdset/session', headers={'Origin': 'https://commons.example'})
    assert len(logout.headers.get_list('set-cookie')) == 2
    assert hosted.get(media).status_code == 401
    assert hosted.get('/crowdset/sets').status_code == 401


def test_uploader_names_follow_recording_identity_not_current_viewer(hosted, monkeypatch):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    owner = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    friend = {'Authorization': 'Bearer second', 'Origin': 'https://commons.example'}
    data = hosted.post('/crowdset/sets', headers=owner, json={'name': 'Attribution'}).json()
    path = '/crowdset/sets/' + data['id']
    added = hosted.put(path + '/clips?name=friend.mp4', headers=friend, content=b'original').json()
    clip = added['clips'][0]
    assert clip['uploader_name'] == 'Bob Friend'
    assert clip['uploader'] == '22222222-2222-4222-8222-222222222222'
    assert hosted.get(path, headers=owner).json()['clips'][0]['uploader_name'] == 'Bob Friend'
    assert hosted.get('/crowdset/sets', headers=owner).json()[0]['clips'][0]['uploader_name'] == 'Bob Friend'
    assert 'private@example.com' not in hosted.get(path, headers=owner).text
    # Names are decoration: user-editable metadata cannot grant set ownership.
    assert hosted.delete(path, headers=friend).status_code == 403


def test_uploader_display_names_survive_restart_and_fill_legacy_recordings(tmp_path, monkeypatch):
    from crowdset.app import present
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    store = Store(tmp_path)
    data = store.create('Legacy names', owner='alice')
    data['clips'] = [{'id': 'old', 'name': 'phone.mov', 'uploader': 'alice'}]
    store.save(data)
    store.remember_uploader('alice', 'Alice')
    store.close()
    restored = Store(tmp_path)
    try:
        assert present(restored.get(data['id']), 'bob', restored.uploaders)['clips'][0]['uploader_name'] == 'Alice'
        restored.remember_uploader('alice', 'Alice Updated')
        assert present(restored.get(data['id']), 'bob', restored.uploaders)['clips'][0]['uploader_name'] == 'Alice Updated'
        assert not present(restored.get(data['id']), 'bob', restored.uploaders)['clips'][0]['can_edit']
    finally:
        restored.close()


@pytest.mark.parametrize('route', ['/crowdset/sets', '/crowd-set/sets'])
def test_admin_can_remove_any_clip_and_delete_sets_without_ownership(hosted, monkeypatch, route):
    monkeypatch.setattr(Store, 'schedule', lambda self: None)
    owner = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    friend = {'Authorization': 'Bearer second', 'Origin': 'https://commons.example'}
    admin = {'Authorization': 'Bearer admin', 'Origin': 'https://commons.example'}
    data = hosted.post(route, headers=owner, json={'name': 'Moderated'}).json()
    path = route + '/' + data['id']
    added = hosted.put(path + '/clips?name=friend.mp4', headers=friend, content=b'preserved original').json()
    clip = added['clips'][0]
    assert not added['can_delete'] and clip['can_delete']
    assert hosted.delete(path, headers=owner).status_code == 403
    assert hosted.delete(path + '/clips/' + clip['id'], headers=owner).status_code == 403
    admin_view = hosted.get(path, headers=admin).json()
    assert admin_view['can_delete'] and admin_view['clips'][0]['can_delete']
    assert not admin_view['can_manage']
    assert hosted.delete(path + '/clips/' + clip['id'], headers=admin).status_code == 200
    stored = hosted.app.state.store.get(data['id'])
    removed = stored['deleted_clips'][0]
    assert hosted.app.state.store.originals.path(data['id'], removed).read_bytes() == b'preserved original'
    assert hosted.delete(path, headers=admin).status_code == 204
    assert hosted.get(path, headers=admin).status_code == 404
    names = [s['name'] for s in hosted.get(route, headers=admin).json()]
    assert 'Legacy private' in names and 'Local only' not in names
    private = next(s for s in hosted.get(route, headers=admin).json() if s['name'] == 'Legacy private')
    assert hosted.delete(route + '/' + private['id'], headers=admin).status_code == 204


@pytest.mark.parametrize('revoked_role', [False, None, 'true', 'admin', 1])
def test_admin_revocation_is_checked_live_and_requires_boolean_true(hosted, revoked_role):
    owner = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    admin = {'Authorization': 'Bearer admin', 'Origin': 'https://commons.example'}
    data = hosted.post('/crowdset/sets', headers=owner, json={'name': 'Role changes'}).json()
    path = '/crowdset/sets/' + data['id']
    assert hosted.get(path, headers=admin).json()['can_delete']
    hosted.app.state.test_admin_roles['Bearer admin'] = revoked_role
    assert not hosted.get(path, headers=admin).json()['can_delete']
    assert hosted.delete(path, headers=admin).status_code == 403


def test_missing_uploader_does_not_grant_set_owner_clip_deletion(hosted):
    owner = {'Authorization': 'Bearer first', 'Origin': 'https://commons.example'}
    data = hosted.post('/crowdset/sets', headers=owner, json={'name': 'Unknown uploader'}).json()
    data['clips'] = [{'id': 'old', 'name': 'legacy.mov'}]
    hosted.app.state.store.save(data)
    path = '/crowdset/sets/' + data['id']
    assert not hosted.get(path, headers=owner).json()['clips'][0]['can_delete']
    assert hosted.delete(path + '/clips/old', headers=owner).status_code == 403
