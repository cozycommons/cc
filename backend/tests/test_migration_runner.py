import os
from pathlib import Path
import subprocess
import time
import pytest
import migration_runner
from tests.dice_test_database import is_isolated_dice_test_database


def test_direct_pooler_normalization_preserves_encoded_password():
    url = "postgresql://postgres:p%40ss@db.example.supabase.co:5432/postgres?sslmode=require"
    assert migration_runner.normalize_url(url,"aws-0-us-east-2.pooler.supabase.com") == "postgresql://postgres.example:p%40ss@aws-0-us-east-2.pooler.supabase.com:5432/postgres?sslmode=require"
    with pytest.raises(ValueError): migration_runner.normalize_url(url)


def test_family_rendering_and_receipt_guards():
    commons = migration_runner.render(["commons"])
    assert "Applying 0008_commons_service_role_read.sql" in commons
    assert "Applying 0025_dice_schema.sql" not in commons
    both = migration_runner.render(["dice","commons"])
    assert both.index("pg_advisory_lock") < both.index("BEGIN;")
    assert "Migration checksum changed:" in both
    assert "Existing dice schema has no migration history" in both
    assert "Applying 0079_dice_staging_schema_reconciliation.sql" in both


@pytest.mark.skipif(not is_isolated_dice_test_database(os.environ),reason="isolated database required")
def test_real_runner_fresh_existing_retry_and_checksum_rejection(tmp_path):
    import re
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(os.environ["DB_URL"])
    name = "cc_runner_" + str(os.getpid())
    assert re.fullmatch(r"cc_runner_[0-9]+",name)
    def sql(query,url=os.environ["DB_URL"]):
        return subprocess.run(["psql",url,"-X","-v","ON_ERROR_STOP=1"],input=query,text=True,capture_output=True)
    assert sql('create database "'+name+'";').returncode == 0
    url = urlunparse(parsed._replace(path="/"+name))
    try:
        setup = """create schema auth; create table auth.users(id uuid primary key);
        grant usage on schema public to service_role;
        alter default privileges in schema public grant all on tables to service_role;
        """
        assert sql(setup,url).returncode == 0
        driver = migration_runner.render(["dice","commons"])
        first = sql(driver,url)
        assert first.returncode == 0, first.stdout+first.stderr
        assert sql("select public.dice_release_readiness();",url).returncode == 0
        service_ready = sql("set role service_role; select public.dice_release_readiness();",url)
        assert service_ready.returncode == 0, service_ready.stderr
        denied = sql("set role anon; select public.dice_release_readiness();",url)
        assert denied.returncode != 0 and "permission denied" in denied.stderr
        # Second run must skip every migration and preserve seeded Commons state.
        again = sql(driver,url)
        assert again.returncode == 0,again.stdout+again.stderr
        assert "Applying " not in again.stdout
        # A damaged checksum fails before any reapplication.
        assert sql("update dice_schema_migrations set checksum='corrupt' where version=79;",url).returncode == 0
        damaged = sql(driver,url)
        assert damaged.returncode != 0 and "Migration checksum changed" in damaged.stderr
        assert "Applying " not in damaged.stdout
        assert sql("update dice_schema_migrations set checksum=null where version=79; delete from dice_schema_migrations where version=43;",url).returncode == 0
        gap = sql(driver,url)
        assert gap.returncode != 0 and "Migration history gap" in gap.stderr
        assert "Applying " not in gap.stdout
    finally:
        assert sql('drop database "'+name+'" with (force);').returncode == 0
