"""Real SQL boundary and metric checks in a disposable loopback database.

Run with RUN_ANALYTICS_DB_TESTS=1. Never loads dotenv or connects to hosted data.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skipif(os.getenv('RUN_ANALYTICS_DB_TESTS') != '1', reason='Explicit loopback database test opt-in')


@pytest.fixture(scope='module')
def database():
    import psycopg
    from psycopg import sql
    root = Path(__file__).resolve().parents[1]
    database = 'cc_analytics_qa_' + uuid4().hex[:10]
    password = uuid4().hex
    ci = os.getenv('GITHUB_ACTIONS') == 'true'
    admin_url = 'postgresql://postgres:postgres@localhost:5432/dummi_test' if ci else 'postgresql://postgres:postgres@127.0.0.1:54322/postgres'
    admin = psycopg.connect(admin_url, autocommit=True)
    reader_role = 'commons_analytics_reader.qa_' + uuid4().hex[:10]
    existed = admin.execute("SELECT 1 FROM pg_roles WHERE rolname='commons_analytics_reader'").fetchone()
    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
    host = 'localhost:5432' if ci else '127.0.0.1:54322'
    url = f'postgresql://postgres:postgres@{host}/{database}'
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute('CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY, raw_user_meta_data jsonb, created_at timestamptz, last_sign_in_at timestamptz, is_anonymous boolean)')
            for migration in ('0020_analytics_events.sql','0035_analytics_events_context.sql','0083_analytics_workspace.sql'):
                conn.execute((root/'migrations'/migration).read_text())
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN IN ROLE commons_analytics_reader PASSWORD {}').format(sql.Identifier(reader_role), sql.Literal(password)))
        yield url, f'postgresql://{reader_role}:{password}@{host}/{database}'
    finally:
        admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(reader_role)))
        if not existed:
            admin.execute('DROP ROLE commons_analytics_reader')
        admin.close()


def test_live_metrics_and_boundary(database, monkeypatch):
    import psycopg
    from admin.query import execute_query
    writer, reader = database
    monkeypatch.setenv('ANALYTICS_DATABASE_URL', reader)
    uid, sid = str(uuid4()), str(uuid4())
    with psycopg.connect(writer) as conn:
        for time, identity in [('2026-10-25T01:00Z','anonymous'),('2026-10-25T02:00Z','verified'),('2026-10-26T01:00Z','verified')]:
            conn.execute("INSERT INTO public.analytics_events(app,event_type,path,event_id,schema_version,identity_status,user_id,session_id,created_at) VALUES ('dice','pageview','/dice',%s,1,%s,%s,%s,%s)", (str(uuid4()), identity, uid if identity=='verified' else None,sid,time))
        conn.execute("INSERT INTO public.analytics_events(app,event_type,path,user_id,session_id) VALUES ('dice','pageview','/dice',%s,%s)",(str(uuid4()),str(uuid4())))
        queries = conn.execute('SELECT title,sql FROM public.analytics_saved_queries ORDER BY position').fetchall()
    start = datetime(2026,10,25,tzinfo=timezone.utc); end=datetime(2026,10,27,tzinfo=timezone.utc)
    results = {title:execute_query(query,start,end,None) for title,query in queries}
    assert results['Active users']['rows'] == [{'project':'dice','active_users':1}]
    assert results['Visits']['rows'] == [{'project':'dice','visits':1,'logged_in':1,'logged_out':1}]
    assert len(results['Daily active users']['rows']) == 10
    assert sum(row['active_users'] for row in results['Daily active users']['rows']) == 2
    assert execute_query('SELECT generate_series(1,1100) AS n',start,end,None)['truncated']
    with psycopg.connect(reader) as conn:
        for statement in ["INSERT INTO public.analytics_events(app,event_type,path) VALUES ('dice','pageview','/dice')",'SELECT * FROM auth.users','DELETE FROM public.analytics_saved_queries']:
            with pytest.raises(psycopg.Error): conn.execute(statement)
            conn.rollback()
    # Invalid statement does not poison the next connection or semaphore slot.
    from fastapi import HTTPException
    with pytest.raises(HTTPException): execute_query('SELECT missing FROM analytics.events',start,end,None)
    assert execute_query('SELECT 1 AS ok',start,end,None)['rows']==[{'ok':1}]


def test_parameters_preserve_literals(database, monkeypatch):
    from admin.query import execute_query
    monkeypatch.setenv('ANALYTICS_DATABASE_URL', database[1])
    start = datetime(2026,10,25,tzinfo=timezone.utc)
    result = execute_query("SELECT '$1'::text AS literal, $3::text AS project", start, start, "quote' and dollar $1")
    assert result['rows'] == [{'literal':'$1','project':"quote' and dollar $1"}]


def test_statement_timeout_recovers(database, monkeypatch):
    from admin.query import execute_query
    from fastapi import HTTPException
    monkeypatch.setenv('ANALYTICS_DATABASE_URL', database[1])
    start = datetime(2026,10,25,tzinfo=timezone.utc)
    with pytest.raises(HTTPException) as caught:
        execute_query('SELECT sum(n) AS total FROM generate_series(1,1000000000) AS n',start,start,None)
    assert caught.value.status_code == 408
    assert execute_query('SELECT 1 AS ok',start,start,None)['rows']==[{'ok':1}]
