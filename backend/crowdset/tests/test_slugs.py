from crowdset.store import Store


def test_stable_unique_slugs_and_legacy_backfill(tmp_path):
    store = Store(tmp_path)
    try:
        first = store.create('ISOKNOCK NITEHARTS 2026')
        second = store.create('ISOKNOCK NITEHARTS 2026')
        assert first['slug'] == 'isoknock-niteharts-2026'
        assert second['slug'] == 'isoknock-niteharts-2026-2'
        assert store.create('Beyoncé — live!!')['slug'] == 'beyonce-live'
        assert store.create('🎵')['slug'] == 'set'
        assert store.create('Health')['slug'] == 'health-2'
        legacy = store.create('ISOKNOCK NITEHARTS 2026')
        legacy.pop('slug')
        store.save(legacy)
    finally:
        store.close()
    store = Store(tmp_path)
    try:
        assert store.get(first['id'])['slug'] == first['slug']
        assert store.get(second['id'])['slug'] == second['slug']
        assert store.get(legacy['id'])['slug'] == 'isoknock-niteharts-2026-3'
        assert store.get(legacy['id'])['clips'] == []
    finally:
        store.close()


def test_direct_page_refresh_keeps_api_errors_and_asset_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from crowdset.app import create_app
    static = tmp_path / 'frontend'
    (static / 'assets').mkdir(parents=True)
    (static / 'index.html').write_text('<html>Crowdset shell</html>')
    monkeypatch.setenv('CROWDSET_STATIC_DIR', str(static))
    with TestClient(create_app(tmp_path / 'data'), base_url='http://127.0.0.1') as api:
        assert api.get('/crowdset/isoknock-niteharts-2026').text == '<html>Crowdset shell</html>'
        assert api.get('/crowdset/sets/not-found').status_code == 404
        assert api.get('/crowdset/sets/not-found').headers['content-type'] == 'application/json'
        assert api.get('/crowdset/assets/missing.js').status_code == 404
        assert api.get('/crowdset/session').status_code == 404
        assert api.get('/crowdset/health').json() == {'status': 'ok'}
