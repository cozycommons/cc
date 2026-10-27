"""Upgrade starting states omitted by fresh-install and retry-only checks."""
import hashlib
import os
import shutil

import pytest

from tests.migration_harness import REPO, checkout_release, migration_database, reconciliation_release


PRE_ANALYTICS_RELEASE = "c63264dcadb77ce05183cb49a3119fc2c496387b"
ANALYTICS_MIGRATION = "0083_analytics_workspace.sql"


@pytest.fixture(scope="module")
def old_release(tmp_path_factory):
    return checkout_release(PRE_ANALYTICS_RELEASE, tmp_path_factory.mktemp("releases") / "before-analytics")


@pytest.fixture(scope="module")
def shipped_release(tmp_path_factory):
    return checkout_release("1bb44884d22c4e1b800aec72f666f73f23aaf171", tmp_path_factory.mktemp("shipped") / "analytics")


@pytest.fixture
def candidate_release(tmp_path):
    backend = tmp_path / "backend"
    for directory in ("migrations", "commons/migrations", "trips/migrations", "floor_planner/migrations"):
        shutil.copytree(REPO / "backend" / directory, backend / directory)
    shutil.copy(REPO / "backend/migration_runner.py", backend)
    shutil.copy(REPO / "backend/schema_catalog_v1.sql", backend)
    return backend


@pytest.fixture
def adopted_database(migration_database, old_release):
    database = migration_database
    database.release(old_release)
    # Synthetic imported Dice baseline: legacy cross-project analytics was absent.
    database.sql("""DROP TABLE public.analytics_events;
        DELETE FROM public.dice_schema_migrations WHERE version < 42;
        INSERT INTO auth.users(id) VALUES ('11111111-1111-1111-1111-111111111111');
        INSERT INTO public.dice_profiles(user_id,display_name)
        VALUES ('11111111-1111-1111-1111-111111111111','Upgrade fixture');""")
    return database


def test_upgrade_from_previous_release(migration_database, tmp_path):
    ref = os.getenv("MIGRATION_BASE_REF") or "origin/main"
    previous = checkout_release(ref, tmp_path / "previous")
    migration_database.release(previous)
    migration_database.sql("""INSERT INTO public.analytics_events(app,event_type,path,metadata)
        VALUES ('dice','pageview','/dice','{"synthetic":true}');""")
    before = migration_database.sql("SELECT id,created_at,app,event_type,path,metadata FROM public.analytics_events;").stdout
    migration_database.release()
    after = migration_database.sql("SELECT id,created_at,app,event_type,path,metadata FROM public.analytics_events;").stdout
    assert before == after
    assert migration_database.sql("SELECT public.dice_release_readiness(),public.trips_release_readiness();").stdout.strip() == "t|t"
    assert "Applying " not in migration_database.release().stdout


def test_adopted_baseline_without_analytics(adopted_database, shipped_release, reconciliation_release):
    database = adopted_database
    # The shipped runner reproduces the deployment error on this starting state.
    failure = database.release(shipped_release, check=False)
    assert failure.returncode != 0 and 'relation "public.analytics_events" does not exist' in failure.stderr
    assert database.sql("SELECT to_regtype('public.analytics_event_type') IS NULL;").stdout.strip() == "t"
    blocked = database.release(check=False)
    assert blocked.returncode != 0 and 'Migration history gap in dice' in blocked.stderr
    result = database.release(reconciliation_release)
    database.release()
    assert database.sql('SELECT max(version) FROM public.dice_schema_migrations;').stdout.strip() == (REPO / 'backend/migrations/DICE_SCHEMA_CONTRACT_VERSION').read_text().strip()
    assert "Preparing prerequisite for " + ANALYTICS_MIGRATION in result.stdout
    assert database.sql("SELECT display_name FROM public.dice_profiles;").stdout.strip() == "Upgrade fixture"
    assert database.sql("SELECT count(*) FROM public.analytics_saved_queries;").stdout.strip() == "4"
    assert database.sql("SELECT count(*) FROM public.dice_schema_migrations WHERE version IN (20,35) AND recorded_via='reconciled' AND reconciled_by=84;").stdout.strip() == "2"
    digest = hashlib.sha256((REPO / "backend/migrations/prerequisites" / ANALYTICS_MIGRATION).read_bytes()).hexdigest()
    assert database.sql("SELECT prerequisite_checksum FROM public.dice_schema_migrations WHERE version=83;").stdout.strip() == digest
    assert database.sql("SELECT public.dice_release_readiness();").stdout.strip() == "t"
    assert "Applying " not in database.release().stdout
    for role in ("anon", "authenticated"):
        denied = database.sql(f"SET ROLE {role}; SELECT * FROM public.analytics_events;", check=False)
        assert denied.returncode != 0 and "permission denied" in denied.stderr
    database.sql("""SET ROLE service_role;
        INSERT INTO public.analytics_events(app,event_type,path,event_name,schema_version,identity_status)
        VALUES ('dice','action','/dice','dice.fixture',1,'anonymous');""")


@pytest.mark.parametrize("context", [False, True], ids=["legacy-base-only", "legacy-with-context"])
def test_upgrade_preserves_legacy_rows(migration_database, old_release, context):
    database = migration_database
    database.release(old_release)
    if not context:
        database.sql("ALTER TABLE public.analytics_events DROP COLUMN user_id, DROP COLUMN email, DROP COLUMN session_id, DROP COLUMN ip_address;")
    database.sql("""INSERT INTO public.analytics_events(id,created_at,app,event_type,label,path,metadata)
        VALUES (123,'2026-01-01Z','dice','pageview','original','/dice','{"keep":true}');""")
    before = database.sql("SELECT id,created_at,app,event_type,label,path,metadata FROM public.analytics_events;").stdout
    database.release()
    assert before == database.sql("SELECT id,created_at,app,event_type,label,path,metadata FROM public.analytics_events;").stdout
    assert database.sql("SELECT schema_version,identity_status FROM public.analytics_events;").stdout.strip() == "0|legacy_unverified"
    assert database.sql("SELECT count(*) FROM analytics.legacy_events;").stdout.strip() == "1"
    assert database.sql("SELECT count(*) FROM analytics.events;").stdout.strip() == "0"


def test_pre_sidecar_receipt_is_preserved(migration_database, shipped_release):
    database = migration_database
    database.release(shipped_release)
    result = database.release()
    assert "Preparing prerequisite" not in result.stdout
    assert database.sql("SELECT prerequisite_checksum IS NULL FROM public.dice_schema_migrations WHERE version=83;").stdout.strip() == "t"


@pytest.mark.parametrize("change", ["modified", "removed"])
def test_prerequisite_checksum_is_checked_before_any_migrations(migration_database, candidate_release, change):
    database = migration_database
    database.release()
    database.sql("DELETE FROM public.commons_schema_migrations WHERE version=12;")
    backend = candidate_release
    prerequisite = backend / "migrations/prerequisites" / ANALYTICS_MIGRATION
    if change == "modified":
        prerequisite.write_text(prerequisite.read_text() + "\nSELECT 1;\n")
    else:
        prerequisite.unlink()
    result = database.release(backend, check=False)
    assert result.returncode != 0 and "prerequisite checksum changed" in result.stderr
    assert "Applying " not in result.stdout
    assert database.sql("SELECT count(*) FROM public.commons_schema_migrations WHERE version=12;").stdout.strip() == "0"


def test_prerequisite_and_receipt_rollback_together(migration_database, old_release, candidate_release):
    database = migration_database
    database.release(old_release)
    database.sql('DROP TABLE public.analytics_events;')
    backend = candidate_release
    migration = backend / "migrations" / ANALYTICS_MIGRATION
    migration.write_text(migration.read_text() + "\nSELECT 1/0;\n")
    result = database.release(backend, check=False)
    assert result.returncode != 0 and "division by zero" in result.stderr
    assert database.sql("SELECT to_regclass('public.analytics_events') IS NULL, to_regclass('public.analytics_saved_queries') IS NULL, to_regtype('public.analytics_event_type') IS NULL;").stdout.strip() == "t|t|t"
    assert database.sql("SELECT count(*) FROM public.dice_schema_migrations WHERE version=83;").stdout.strip() == "0"
    database.release()
