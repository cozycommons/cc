"""Real persistence and atomic two-party commands against the owned loopback stack."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from tests.test_trips import local_api  # noqa: F401
from venmo import profiles, venmo_client


def test_lkg_survives_restart_and_two_parties_cannot_double_settle(local_api, monkeypatch):
    api, db, settings, tokens, cleanup = local_api
    handle = 'qa-' + uuid4().hex[:16]
    preview = dict(handle=handle, displayName='Synthetic Friend', photoUrl='https://pics-v3.venmo.com/a?width=200&height=200', initials='SF', active=True, source='live')
    monkeypatch.setattr(venmo_client, 'fetch', lambda *a, **kw: preview)
    first = profiles.ProfileLookup()
    try:
        assert first.lookup(handle, 'qa', db)['source'] == 'live'
        row = db.table('venmo_profiles').select('*').eq('handle', handle).execute().data[0]
        assert set(row) == {'handle', 'display_name', 'photo_url', 'initials', 'active', 'source', 'fetched_at'}
        monkeypatch.setattr(venmo_client, 'fetch', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('fixture upstream down')))
        restarted = profiles.ProfileLookup()
        result = restarted.lookup(handle, 'qa', db)
        restarted.executor.shutdown(wait=True)
        assert result['found'] and result['source'] == 'cached' and result['stale']
    finally:
        first.executor.shutdown(wait=True)
        db.table('venmo_profiles').delete().eq('handle', handle).execute()
    identifier = str(uuid4())
    cleanup.append(identifier)
    group = api.post('/trips/groups', headers=tokens['Matt'], json={'id': identifier, 'name': 'Synthetic obligations QA'}).json()
    base = '/trips/groups/' + identifier
    invitation = api.post(base + '/members', headers=tokens['Matt'], json={'name': 'Alex', 'revision': group['revision']}).json()
    group = api.post(base + '/join', headers=tokens['Alex'], json={'invite_token': invitation['invite_token']}).json()
    members = [m['id'] for m in group['members']]
    group = api.post(base + '/expenses', headers=tokens['Matt'], json={'id': str(uuid4()), 'description': 'Synthetic dinner', 'amount_minor': 2468, 'paid_by': members[0], 'participants': members, 'date': '2026-10-25', 'revision': group['revision']}).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda pair: api.post(base + '/settle/ready', headers=tokens[pair[0]], json={'member_id': pair[1], 'ready': True}), zip(['Matt', 'Alex'], members)))
    assert all(r.status_code == 200 for r in responses)
    group = api.get(base, headers=tokens['Matt']).json()
    assert group['settle']['started'] and len(group['settle']['ready']) == 2
    obligation = group['obligations'][0]
    path = base + '/obligations/' + obligation['id']
    def settle(name):
        return api.post(path + '/settle', headers=tokens[name], json={'cycle': 0, 'amount_minor': obligation['amount_minor']})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(settle, ['Matt', 'Alex']))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    settled = api.get(base, headers=tokens['Alex']).json()
    assert len(settled['repayments']) == 1
    assert all(v == 0 for v in settled['balances'].values())
    assert settled['obligations'][0]['status'] == 'settled'
    third = api.post(base + '/members', headers=tokens['Matt'], json={'name': 'Jamie', 'revision': settled['revision']}).json()
    joined = api.post(base + '/join', headers=tokens['Jamie'], json={'invite_token': third['invite_token']}).json()
    denied = api.request('DELETE', base + '/repayments/' + obligation['id'], headers=tokens['Jamie'], json={'revision': joined['revision']})
    assert denied.status_code == 403
    assert api.get(base, headers=tokens['Matt']).json()['repayments'] == settled['repayments']
    undone = api.post(path + '/undo', headers=tokens['Alex'], json={'cycle': 0}).json()
    assert {m: undone['balances'][m] for m in members} == group['balances'] and not undone['repayments']
    assert api.post(path + '/settle', headers=tokens['Matt'], json={'cycle': 0, 'amount_minor': obligation['amount_minor']}).status_code == 409


def test_photo_survives_restart_in_guarded_postgres(monkeypatch):
    import json
    import os
    import subprocess
    from types import SimpleNamespace
    import pytest
    from tests.dice_test_database import is_isolated_dice_test_database
    from venmo import photos
    if not is_isolated_dice_test_database(os.environ):
        pytest.skip('Requires guarded loopback Postgres')

    def literal(value):
        return "'" + value.replace("'", "''") + "'"

    def sql(statement):
        return subprocess.check_output(['psql', os.environ['DB_URL'], '-XAt', '-v', 'ON_ERROR_STOP=1', '-c', statement], text=True).strip()

    class PhotoQuery:
        def __init__(self, table):
            assert table == 'venmo_photos'
            self.filters = {}
            self.row = None
        def select(self, columns):
            return self
        def eq(self, key, value):
            assert key in {'handle', 'photo_url'}
            self.filters[key] = value
            return self
        def upsert(self, row):
            self.row = row
            return self
        def execute(self):
            if self.row:
                columns = ('handle', 'photo_url', 'body', 'content_type')
                sql('insert into public.venmo_photos (' + ','.join(columns) + ') values (' + ','.join(literal(self.row[k]) for k in columns) + ') on conflict (handle,photo_url) do update set body=excluded.body, content_type=excluded.content_type')
                return SimpleNamespace(data=[])
            where = ' and '.join(k + '=' + literal(v) for k, v in self.filters.items())
            data = sql("select coalesce(json_agg(p), '[]'::json) from (select body,content_type from public.venmo_photos where " + where + ') p')
            return SimpleNamespace(data=json.loads(data))

    handle = 'qa-' + uuid4().hex[:16]
    profile = dict(handle=handle, found=True, photoUrl='https://pics-v3.venmo.com/synthetic')
    db = SimpleNamespace(table=PhotoQuery)
    sql("insert into public.venmo_profiles values (" + literal(handle) + ", 'Synthetic', 'https://pics-v3.venmo.com/synthetic', 'S', true, 'live', now())")
    from unittest.mock import Mock
    fetch = Mock(return_value=(b'synthetic-photo', 'image/png'))
    monkeypatch.setattr(venmo_client, 'fetch', fetch)
    try:
        photos.cache.clear()
        assert photos.thumbnail(profile, db) == (b'synthetic-photo', 'image/png')
        photos.cache.clear()
        fetch.side_effect = AssertionError('No upstream after restart')
        assert photos.thumbnail(profile, db) == (b'synthetic-photo', 'image/png')
        assert fetch.call_count == 1
        assert sql("select has_table_privilege('anon', 'public.venmo_photos', 'select')") == 'f'
        assert sql("select has_table_privilege('authenticated', 'public.venmo_photos', 'insert')") == 'f'
    finally:
        photos.cache.clear()
        sql('delete from public.venmo_profiles where handle=' + literal(handle))
