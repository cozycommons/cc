"""Verify fresh and imported histories converge before removing adoption rules."""
import pytest

from tests.migration_harness import checkout_release, disposable_migration_database, migration_database, reconciliation_release


@pytest.fixture(scope="module")
def previous_release(tmp_path_factory):
    return checkout_release("fcdeb4f7db94413035c583bc9528b74d884e12ad", tmp_path_factory.mktemp("convergence") / "previous")


@pytest.fixture(scope="module")
def canonical_catalog():
    with disposable_migration_database() as database:
        database.release()
        return database.catalog()


@pytest.fixture
def imported_database(migration_database, previous_release):
    database = migration_database
    database.release(previous_release)
    # Model the schema and receipt differences observed in the hosted catalog.
    database.sql("""
        DELETE FROM public.dice_schema_migrations WHERE version<42;
        UPDATE public.dice_schema_migrations SET checksum=NULL WHERE version BETWEEN 42 AND 78;
        ALTER TABLE public.dice_live_command_metrics RENAME CONSTRAINT dice_live_command_metrics_duration_check TO dice_live_command_metrics_duration_ms_check;
        ALTER TABLE public.dice_live_command_metrics RENAME CONSTRAINT dice_live_command_metrics_hedge_delay_check TO dice_live_command_metrics_hedge_delay_ms_check;
        ALTER TABLE public.dice_live_command_metrics DROP CONSTRAINT dice_live_command_metrics_referee_id_fkey;
        ALTER TABLE public.dice_live_command_metrics ADD CONSTRAINT dice_live_command_metrics_referee_id_fkey FOREIGN KEY(referee_id) REFERENCES public.dice_profiles(user_id);
        CREATE INDEX dice_live_command_metrics_match_idx ON public.dice_live_command_metrics(match_id,created_at DESC);
        GRANT ALL ON TABLE public.dice_profiles,public.dice_games,public.dice_game_players,public.dice_game_comments,public.dice_tournaments,public.dice_tournament_enrollments TO anon,authenticated;
        GRANT ALL ON SEQUENCE public.analytics_events_id_seq,public.commons_scene_commands_id_seq,public.dice_live_command_metrics_id_seq,public.dice_virtual_ledger_id_seq,public.dice_virtual_markets_id_seq,public.dice_virtual_picks_id_seq TO anon,authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO anon,authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO anon,authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon,authenticated,service_role;
        INSERT INTO auth.users(id) VALUES('11111111-1111-1111-1111-111111111111');
        INSERT INTO public.dice_profiles(user_id,display_name) VALUES('11111111-1111-1111-1111-111111111111','Preserved profile');
    """)
    return database


def catalog_difference(expected, actual):
    left = {(row['kind'], row['key']): row['definition'] for row in expected}
    right = {(row['kind'], row['key']): row['definition'] for row in actual}
    return [key for key in sorted(left.keys() | right.keys()) if left.get(key) != right.get(key)]


def test_fresh_schema_without_legacy_supabase_default_grants(migration_database, canonical_catalog):
    database = migration_database
    database.sql("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT,INSERT,UPDATE,DELETE ON TABLES FROM service_role;")
    database.release()
    assert catalog_difference(canonical_catalog, database.catalog()) == []
    for family in ('dice', 'commons', 'beli', 'trips', 'venmo'):
        denied = database.sql(f"SET ROLE service_role; DELETE FROM public.{family}_schema_migrations;", check=False)
        assert denied.returncode != 0 and 'permission denied' in denied.stderr


def test_imported_and_fresh_schemas_are_identical(imported_database, canonical_catalog, reconciliation_release):
    database = imported_database
    receipts_before = database.sql("SELECT version,applied_at,checksum FROM public.dice_schema_migrations ORDER BY version;").stdout
    profile_before = database.sql("SELECT to_jsonb(p) FROM public.dice_profiles p;").stdout
    database.release(reconciliation_release)
    database.release()
    assert database.sql("SELECT version,applied_at,checksum FROM public.dice_schema_migrations WHERE version>=42 AND version<84 ORDER BY version;").stdout == receipts_before
    assert database.sql("SELECT to_jsonb(p) FROM public.dice_profiles p;").stdout == profile_before
    assert catalog_difference(canonical_catalog, database.catalog()) == []
    assert database.sql("SELECT count(*) FROM public.dice_schema_migrations WHERE recorded_via='reconciled' AND reconciled_by=84;").stdout.strip() == '13'
    assert database.sql("SELECT recorded_via FROM public.dice_schema_migrations WHERE version=84;").stdout.strip() == 'executed'
    assert 'Applying ' not in database.release().stdout
    assert database.sql("SET ROLE service_role; SELECT public.dice_release_readiness();").stdout.strip() == 't'
    for role in ('anon', 'authenticated'):
        assert database.sql(f"SET ROLE {role}; SELECT display_name FROM public.dice_profiles;").stdout.strip() == 'Preserved profile'
        denied = database.sql(f"SET ROLE {role}; UPDATE public.dice_profiles SET display_name='forbidden';", check=False)
        assert denied.returncode != 0 and 'permission denied' in denied.stderr
        denied = database.sql(f"SET ROLE {role}; SELECT nextval('public.dice_virtual_picks_id_seq');", check=False)
        assert denied.returncode != 0 and 'permission denied' in denied.stderr


@pytest.mark.parametrize('drift', [
    "ALTER TABLE public.dice_profiles ADD COLUMN unexpected_column text;",
    "GRANT SELECT(enabled) ON public.dice_feature_access TO anon;",
    "ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO anon;",
])
def test_unreviewed_drift_prevents_reconciling_history(imported_database, drift, reconciliation_release):
    database = imported_database
    database.sql(drift)
    result = database.release(reconciliation_release, check=False)
    assert result.returncode != 0 and 'schema convergence mismatch' in result.stderr
    assert database.sql("SELECT count(*) FROM public.dice_schema_migrations WHERE version IN (20,25,35,84);").stdout.strip() == '0'
    assert database.sql("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='dice_schema_migrations' AND column_name='reconciled_by';").stdout.strip() == '0'


def test_catalog_preserves_function_literals(migration_database):
    database = migration_database
    database.release()
    database.sql("CREATE FUNCTION public.catalog_literal_fixture() RETURNS text LANGUAGE sql AS $$SELECT 'two  spaces'::text$$;")
    before = database.catalog()
    database.sql("CREATE OR REPLACE FUNCTION public.catalog_literal_fixture() RETURNS text LANGUAGE sql AS $$SELECT 'two spaces'::text$$;")
    assert catalog_difference(before, database.catalog()) == [('function', 'public.catalog_literal_fixture()')]


def test_reconciliation_provenance_requires_a_source(migration_database):
    database = migration_database
    database.release()
    invalid = database.sql("UPDATE public.dice_schema_migrations SET recorded_via='reconciled',reconciliation_reason='fixture',reconciled_by=NULL WHERE version=20;", check=False)
    assert invalid.returncode != 0 and 'reconciliation_provenance' in invalid.stderr


def test_catalog_excludes_physical_runtime_state(migration_database):
    database = migration_database
    database.release()
    before = database.catalog()
    database.sql("SELECT setval('public.analytics_events_id_seq',9999);")
    assert catalog_difference(before, database.catalog()) == []


@pytest.mark.parametrize('version', [20, 25, 42])
def test_missing_early_receipt_blocks_every_release(migration_database, version):
    database = migration_database
    database.release()
    database.sql(f"DELETE FROM public.dice_schema_migrations WHERE version={version};")
    before = database.catalog()
    result = database.release(check=False)
    assert result.returncode != 0 and 'Migration history gap in dice' in result.stderr
    assert 'Applying ' not in result.stdout
    assert catalog_difference(before, database.catalog()) == []


def test_reconciled_checksum_is_verified(imported_database, reconciliation_release):
    database = imported_database
    database.release(reconciliation_release)
    database.sql("UPDATE public.dice_schema_migrations SET checksum=repeat('0',64) WHERE version=20;")
    result = database.release(check=False)
    assert result.returncode != 0 and 'Migration checksum changed in dice history' in result.stderr
    assert 'Applying ' not in result.stdout
