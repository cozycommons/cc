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

    def auth(request):
        assert request.url == 'https://test.supabase.co/auth/v1/user'
        assert request.headers['apikey'] == 'sb_publishable_test'
        token = request.headers['authorization']
        if token == 'Bearer unavailable':
            return httpx.Response(503)
        if token not in ('Bearer first', 'Bearer second', 'Bearer anonymous', 'Bearer third'):
            return httpx.Response(401)
        return httpx.Response(200, json={'id': first if token == 'Bearer first' else ('33333333-3333-4333-8333-333333333333' if token == 'Bearer third' else second),
                                       'is_anonymous': token == 'Bearer anonymous', 'email_confirmed_at': '2026-01-01'})

    monkeypatch.setattr('crowdset.hosting.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(auth), **kwargs))
    # Local files never become publicly owned when a checkout is hosted.
    store = Store(tmp_path)
    store.create('Local only')
    legacy = store.create('Legacy private', owner=first)
    legacy.pop('visibility')
    store.save(legacy)
    store.close()
    with TestClient(create_app(), base_url='https://commons.example') as api:
        yield api


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
    assert api.delete(path + '/clips/' + clip['id'], headers=first).status_code == 200
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
    assert hosted.delete(path + '/clips/' + clip_id, headers=owner).json()['soundtrack_clip_id'] is None


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
