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
    assert "adopted_baseline" not in both
    assert "expected.version >" not in both


def test_orphaned_prerequisite_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "schema_catalog_v1.sql").write_text("")
    directory = tmp_path / "migrations/prerequisites"
    directory.mkdir(parents=True)
    (directory / "9999_dice_missing.sql").write_text("SELECT 1;")
    monkeypatch.setattr(migration_runner, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Prerequisite has no matching migration"):
        migration_runner.render(["dice"])


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
        setup = (Path(__file__).resolve().parents[2] / 'scripts/supabase-test-scaffold.sql').read_text()
        assert sql(setup,url).returncode == 0
        driver = migration_runner.render(["dice", "commons", "beli", "trips"])
        first = sql(driver,url)
        assert first.returncode == 0, first.stdout+first.stderr
        # Fantasy settings stay service-only even under default table grants.
        for role in ("anon", "authenticated"):
            for statement in (
                "select * from public.fantasy_leagues",
                "insert into public.fantasy_leagues(season,espn_league_id) values(2027,'1')",
                "update public.fantasy_leagues set espn_league_id='2'",
                "delete from public.fantasy_leagues",
            ):
                denied = sql(f"set role {role}; {statement};", url)
                assert denied.returncode != 0 and "permission denied" in denied.stderr
        # RLS remains a second boundary if table privileges are ever granted.
        rls_denied = sql("""begin;
            grant select, insert on public.fantasy_leagues to authenticated;
            set local role authenticated;
            insert into public.fantasy_leagues(season,espn_league_id) values(2027,'1');
            rollback;""", url)
        assert rls_denied.returncode != 0 and "row-level security" in rls_denied.stderr
        service_settings = sql("""begin; set local role service_role;
            insert into public.fantasy_leagues(season,espn_league_id) values(2027,'1');
            update public.fantasy_leagues set espn_league_id='2' where season=2027;
            select espn_league_id from public.fantasy_leagues where season=2027;
            rollback;""", url)
        assert service_settings.returncode == 0, service_settings.stderr
        assert "2" in service_settings.stdout
        for value in ("abc", "１２３", "123\n", "1" * 13):
            invalid = sql("begin; set local role service_role; insert into public.fantasy_leagues"
                          f"(season,espn_league_id) values(2027,'{value}'); rollback;", url)
            assert invalid.returncode != 0 and "check constraint" in invalid.stderr
        rls = sql("select relrowsecurity from pg_class where oid='public.fantasy_leagues'::regclass;", url)
        assert rls.returncode == 0 and "t" in rls.stdout
        assert sql("select public.dice_release_readiness();",url).returncode == 0
        service_ready = sql("set role service_role; select public.dice_release_readiness();",url)
        assert service_ready.returncode == 0, service_ready.stderr
        denied = sql("set role anon; select public.dice_release_readiness();",url)
        assert denied.returncode != 0 and "permission denied" in denied.stderr
        # Second run must skip every migration and preserve seeded Commons state.
        again = sql(driver,url)
        assert again.returncode == 0,again.stdout+again.stderr
        assert "Applying " not in again.stdout
        # A bad Commons receipt must prevent even a pending Dice migration.
        latest = int((migration_runner.ROOT / "migrations/DICE_SCHEMA_CONTRACT_VERSION").read_text())
        assert sql(f"create table test_pending_dice_receipt as select * from dice_schema_migrations where version={latest}; delete from dice_schema_migrations where version={latest}; update commons_schema_migrations set checksum='corrupt' where version=12;",url).returncode == 0
        cross_family = sql(driver,url)
        assert cross_family.returncode != 0 and "Migration checksum changed in commons" in cross_family.stderr
        assert "Applying " not in cross_family.stdout
        # This test deliberately damaged receipts, so repair only its owned DB.
        import hashlib
        commons_file = next((migration_runner.ROOT / "commons/migrations").glob("0012_*.sql"))
        digest = hashlib.sha256(commons_file.read_bytes()).hexdigest()
        assert sql(f"update commons_schema_migrations set checksum='{digest}' where version=12;",url).returncode == 0
        # Restore the removed receipt: its additive schema is still present.
        assert sql("insert into dice_schema_migrations select * from test_pending_dice_receipt; drop table test_pending_dice_receipt;",url).returncode == 0
        assert sql(driver,url).returncode == 0
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
