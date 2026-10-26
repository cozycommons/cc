from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from admin.query import validate_query, reader_url
from admin.routes import router
from analytics import router as tracking, _buckets


@pytest.mark.parametrize('query', [
    'SELECT * FROM auth.users', 'SELECT * FROM public.analytics_events',
    "SELECT pg_sleep(1)", "SELECT public.count(*) FROM analytics.events", "SELECT set_config('x','y',false)",
    'SELECT 1; SELECT 2', 'DELETE FROM analytics.events',
    'WITH x AS (DELETE FROM analytics.events RETURNING *) SELECT * FROM x',
    'SELECT * INTO temp x FROM analytics.events', 'SELECT * FROM analytics.events FOR UPDATE',
    "SELECT 'auth.users'::regclass", 'SELECT $4', 'SELECT * FROM pg_catalog.pg_authid',
    'WITH unused AS (WITH pg_settings AS (SELECT 1) SELECT 1) SELECT * FROM pg_settings',
    'WITH pg_roles AS (SELECT * FROM pg_roles) SELECT * FROM pg_roles',
    "SELECT count(*) OPERATOR(public.+) 1 FROM analytics.events",
])
def test_reject_unsafe_sql(query):
    with pytest.raises(HTTPException): validate_query(query)


def test_valid_selects():
    validate_query('WITH x AS (SELECT project FROM analytics.events) SELECT project, count(*) AS n FROM x GROUP BY project')
    validate_query("SELECT date_trunc('day',created_at), count(*) FILTER(WHERE identity_status='verified') FROM analytics.events WHERE created_at >= $1::timestamptz GROUP BY 1")


def test_reader_requires_dedicated_role_and_sandbox(monkeypatch):
    monkeypatch.setenv('ANALYTICS_DATABASE_URL', 'postgresql://postgres@127.0.0.1:54322/postgres')
    with pytest.raises(HTTPException): reader_url()
    monkeypatch.setenv('ANALYTICS_DATABASE_URL', 'postgresql://commons_analytics_reader@remote.example:54322/postgres')
    with pytest.raises(HTTPException): reader_url(SimpleNamespace(is_dice_sandbox=True,is_trips_sandbox=False))


@pytest.fixture
def api():
    app = FastAPI(); app.include_router(router, prefix='/admin'); app.include_router(tracking, prefix='/track')
    app.state.analytics_supabase = MagicMock()
    user = SimpleNamespace(id=str(uuid4()), email='qa@example.invalid', email_confirmed_at='now', is_anonymous=False, app_metadata={'commons_admin':True})
    app.state.analytics_supabase.auth.get_user.return_value.user = user
    _buckets.clear()
    return TestClient(app), app, user


def event():
    return {'event_id':str(uuid4()),'project':'dice','event_type':'pageview','event_name':'dice.page_viewed','session_id':str(uuid4()),'path':'/dice'}


def test_admin_access(api):
    client, app, user = api
    assert client.get('/admin/session').status_code == 401
    assert client.get('/admin/session',headers={'Authorization':'Bearer valid'}).status_code == 200
    user.app_metadata = {}; user.user_metadata = {'commons_admin':True}
    assert client.get('/admin/session',headers={'Authorization':'Bearer valid'}).status_code == 403
    user.app_metadata = {'commons_admin':True}; user.email_confirmed_at = None
    assert client.get('/admin/session',headers={'Authorization':'Bearer valid'}).status_code == 403


def test_anonymous_and_verified_collection(api):
    client, app, user = api
    assert client.post('/track/events',json=event()).status_code == 204
    saved = app.state.analytics_supabase.table.return_value.upsert.call_args.args[0]
    assert saved['identity_status'] == 'anonymous' and saved['user_id'] is None
    assert 'email' not in saved and 'created_at' not in saved
    assert client.post('/track/events',json=event(),headers={'Authorization':'Bearer valid'}).status_code == 204
    saved = app.state.analytics_supabase.table.return_value.upsert.call_args.args[0]
    assert saved['user_id'] == user.id and saved['identity_status']=='verified'
    assert app.state.analytics_supabase.table.return_value.upsert.call_args.kwargs['ignore_duplicates']


def test_collector_validation(api):
    client, app, _ = api
    for extra in [{'user_id':str(uuid4())}, {'path':'/dice?token=secret'}, {'metadata':{'x':'a'*5000}}, {'project':'unknown'}, {'event_type':'invented'}]:
        assert client.post('/track/events',json={**event(),**extra}).status_code == 422
    assert client.post('/track/events',content='x'*9000).status_code == 413
    app.state.analytics_supabase.auth.get_user.side_effect = Exception('offline')
    assert client.post('/track/events',json=event(),headers={'Authorization':'Bearer invalid'}).status_code == 503
    app.state.analytics_supabase.table.return_value.upsert.assert_not_called()


def test_range_validation(api):
    client, _, _ = api
    data={'start_at':'2026-01-02T00:00:00Z','end_at':'2026-01-01T00:00:00Z','sql':'SELECT 1'}
    assert client.post('/admin/query',json=data,headers={'Authorization':'Bearer valid'}).status_code==422
