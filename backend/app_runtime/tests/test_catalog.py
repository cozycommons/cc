from fastapi import FastAPI
from fastapi.testclient import TestClient
from app_runtime import catalog


def test_catalog_requires_session_and_omits_platform_internals(monkeypatch):
    seen = []
    async def request(token, method, path):
        seen.append((token, method, path))
        return [{'name': 'health', 'status': 'running', 'members': {'private-id': 'owner'},
                 'routes': {'default': {'url': 'https://health.cozycommons.dev'}}},
                {'name': 'no-route', 'status': 'running', 'routes': {}}]
    monkeypatch.setattr(catalog, 'request', request)
    app = FastAPI(); app.include_router(catalog.router)
    with TestClient(app) as client:
        assert client.get('/apps/catalog').status_code == 401
        assert seen == []
        response = client.get('/apps/catalog', headers={'Authorization': 'Bearer test-session'})
    assert seen == [('test-session', 'GET', '/api/apps')]
    assert response.json() == [{'name': 'health', 'status': 'running', 'url': 'https://health.cozycommons.dev'}]
    assert response.headers['cache-control'] == 'private, no-store'
