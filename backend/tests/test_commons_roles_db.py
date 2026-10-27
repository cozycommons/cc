"""Role migration and API integration against a disposable loopback database."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.getenv('RUN_ANALYTICS_DB_TESTS') != '1', reason='Explicit loopback database opt-in')
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def database():
    import psycopg
    from psycopg import sql
    host = 'localhost:5432' if os.getenv('GITHUB_ACTIONS') == 'true' else '127.0.0.1:54322'
    base = f'postgresql://postgres:postgres@{host}'
    name = 'cc_roles_qa_' + uuid4().hex[:10]
    admin = psycopg.connect(base + '/postgres', autocommit=True)
    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    url = base + '/' + name
    ids = [str(uuid4()) for _ in range(7)]
    try:
        with psycopg.connect(url) as conn:
            conn.execute((ROOT / 'scripts/supabase-test-scaffold.sql').read_text())
            for uid, email, verified, anonymous, metadata in [
                (ids[0], 'jason.keungg@gmail.com', True, False, '{}'),
                (ids[1], 'legacy@example.test', True, False, '{"crowdset_admin":true}'),
                (ids[2], 'member@example.test', True, False, '{}'),
                (ids[3], 'unverified@example.test', False, False, '{"commons_admin":true}'),
                (ids[4], 'anon@example.test', True, True, '{"commons_admin":true}'),
                (ids[5], 'commons@example.test', True, False, '{"commons_admin":true}'),
                (ids[6], 'string@example.test', True, False, '{"commons_admin":"true"}'),
            ]:
                conn.execute("INSERT INTO auth.users(id,email,email_confirmed_at,is_anonymous,raw_app_meta_data) VALUES(%s,%s,CASE WHEN %s THEN now() END,%s,%s)", (uid,email,verified,anonymous,metadata))
            conn.execute((ROOT / 'backend/migrations/0085_dice_commons_roles.sql').read_text())
        yield url, ids
    finally:
        admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()


def role_call(url, actor, target, role, expected):
    import psycopg
    with psycopg.connect(url) as conn:
        conn.execute('SET ROLE service_role')
        return conn.execute('SELECT public.commons_set_role(%s,%s,%s,%s)', (actor,target,role,expected)).fetchone()[0]


def test_seed_directory_privileges_and_own_role(database):
    import psycopg
    url, ids = database
    with psycopg.connect(url) as conn:
        assert set(row[0] for row in conn.execute('SELECT user_id::text FROM commons_user_roles')) == {ids[0],ids[1],ids[5]}
        assert conn.execute('SELECT count(*) FROM commons_role_history').fetchone()[0] == 3
        conn.execute('SET ROLE service_role')
        assert conn.execute("SELECT email FROM commons_list_users('MEMBER@',0)").fetchall() == [('member@example.test',)]
        assert conn.execute("SELECT count(*) FROM commons_list_users('',0)").fetchone()[0] == 6
        assert conn.execute('SELECT commons_get_role(%s)', (ids[3],)).fetchone()[0] == 'member'
        conn.execute('RESET ROLE')
        for role in ['anon','authenticated']:
            conn.execute('SET ROLE ' + role)
            for statement in ['SELECT * FROM commons_accounts', 'SELECT * FROM commons_role_history', 'SELECT * FROM commons_role_audit',
                              "SELECT commons_get_role('" + ids[0] + "')", "SELECT * FROM commons_list_users('',0)",
                              "SELECT commons_set_role('"+ids[2]+"','"+ids[2]+"','admin','member')",
                              "UPDATE commons_user_roles SET role='admin'", 'DELETE FROM commons_user_roles',
                              "INSERT INTO commons_user_roles(user_id,role) VALUES('"+ids[2]+"','admin')"]:
                with conn.transaction():
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        with conn.transaction(): conn.execute(statement)
            conn.execute('RESET ROLE')
        conn.execute('SET ROLE authenticated')
        conn.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (ids[0],))
        assert conn.execute('SELECT user_id::text,role FROM commons_user_roles').fetchall() == [(ids[0],'admin')]


def test_changes_retries_stale_edits_and_audit(database):
    import psycopg
    url, ids = database
    assert role_call(url, ids[0],ids[2],'admin','member') == 'admin'
    assert role_call(url, ids[0],ids[2],'admin','member') == 'admin'
    with pytest.raises(psycopg.Error) as stale:
        role_call(url, ids[0],ids[2],'member','member')
    assert stale.value.sqlstate == 'PT409'
    for target in [ids[3], ids[4], str(uuid4())]:
        with pytest.raises(psycopg.Error): role_call(url,ids[0],target,'admin','member')
    with psycopg.connect(url) as conn:
        audit = conn.execute("SELECT actor_id::text, old_role,new_role FROM commons_role_history WHERE source='admin'").fetchall()
        assert audit == [(ids[0],'member','admin')]
        assert conn.execute('SELECT commons_get_role(%s)',(ids[2],)).fetchone()[0] == 'admin'
    assert role_call(url, ids[0],ids[2],'member','admin') == 'member'
    with pytest.raises(psycopg.Error) as revoked:
        role_call(url,ids[2],ids[2],'admin','member')
    assert revoked.value.sqlstate == 'PT403'
    # Neither legacy email nor metadata can restore the role.
    role_call(url, ids[0],ids[1],'member','admin')
    with psycopg.connect(url) as conn:
        assert conn.execute('SELECT commons_get_role(%s)',(ids[1],)).fetchone()[0] == 'member'
        conn.execute("INSERT INTO auth.users(id,email,email_confirmed_at) VALUES (%s,'homatt999@gmail.com',now())", (str(uuid4()),))
        assert conn.execute('SELECT count(*) FROM commons_user_roles WHERE role=\'admin\'').fetchone()[0] == 2


def test_simultaneous_self_demotions_keep_last_admin(database):
    import psycopg
    url, ids = database
    role_call(url,ids[0],ids[5],'member','admin')
    def demote(uid):
        try:
            return role_call(url,uid,uid,'member','admin')
        except psycopg.Error as exc:
            return exc.sqlstate
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(demote,ids[:2])) == ['PT409','member']
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT count(*) FROM commons_user_roles WHERE role='admin'").fetchone()[0] == 1


def test_actor_revocation_is_rechecked_after_lock(database):
    import psycopg
    url, ids = database
    with psycopg.connect(url) as conn:
        conn.execute('SELECT pg_advisory_xact_lock(873241905)')
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(role_call,url,ids[1],ids[2],'admin','member')
            conn.execute("UPDATE commons_user_roles SET role='member' WHERE user_id=%s",(ids[1],))
            conn.commit()
            with pytest.raises(psycopg.Error) as denied: task.result(timeout=5)
            assert denied.value.sqlstate == 'PT403'


def test_role_write_rolls_back_if_audit_fails(database):
    import psycopg
    url, ids = database
    with psycopg.connect(url) as conn:
        conn.execute("ALTER TABLE commons_role_history ADD CONSTRAINT reject_qa_audit CHECK (source <> 'admin')")
    with pytest.raises(psycopg.errors.CheckViolation): role_call(url,ids[0],ids[2],'admin','member')
    with psycopg.connect(url) as conn:
        assert conn.execute('SELECT commons_get_role(%s)',(ids[2],)).fetchone()[0] == 'member'


def test_admin_http_flow_uses_real_role_transactions(database):
    import psycopg
    from psycopg import sql
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from postgrest.exceptions import APIError
    from admin.routes import router
    url, ids = database
    class DatabaseClient:
        auth = SimpleNamespace(get_user=lambda token: SimpleNamespace(user=SimpleNamespace(
            id=token, email='qa@example.test', email_confirmed_at='now', is_anonymous=False)))
        def rpc(self,name,params):
            def execute():
                try:
                    with psycopg.connect(url) as conn:
                        conn.execute('SET ROLE service_role')
                        query = sql.SQL('SELECT * FROM public.{}({})').format(sql.Identifier(name),sql.SQL(',').join(sql.Placeholder(k) for k in params))
                        cursor = conn.execute(query,params)
                        rows = cursor.fetchall()
                        data = [dict(zip([col.name for col in cursor.description], row)) for row in rows] if name == 'commons_list_users' else rows[0][0]
                        return SimpleNamespace(data=data)
                except psycopg.Error as exc:
                    raise APIError({'code':exc.sqlstate,'message':'safe test error','details':None,'hint':None}) from exc
            return SimpleNamespace(execute=execute)
    app = FastAPI(); app.include_router(router,prefix='/admin'); app.state.analytics_supabase=DatabaseClient()
    client=TestClient(app)
    headers=lambda uid: {'Authorization':'Bearer '+uid}
    assert client.get('/admin/users').status_code == 401
    assert client.get('/admin/users',headers=headers(ids[2])).status_code == 403
    assert client.get('/admin/users?search=member',headers=headers(ids[0])).json()['users'][0]['role'] == 'member'
    path='/admin/users/'+ids[2]+'/role'
    assert client.put(path,headers=headers(ids[0]),json={'role':'admin','expected_role':'member'}).status_code == 200
    assert client.get('/admin/session',headers=headers(ids[2])).status_code == 200
    assert client.put(path,headers=headers(ids[0]),json={'role':'member','expected_role':'admin'}).status_code == 200
    assert client.get('/admin/session',headers=headers(ids[2])).status_code == 403
