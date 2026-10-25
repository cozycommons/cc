"""The migration runner picks up the ESPN tables in the app ("beli") family."""

import migration_runner


def test_espn_migrations_render_in_beli_family():
    script = migration_runner.render(["beli"])
    assert "Applying 0006_beli_espn_accounts.sql" in script
    assert "Applying 0007_beli_espn_snapshots.sql" in script
    assert "Applying 0008_beli_espn_lineup.sql" in script
    assert "Applying 0009_beli_espn_public_predictions.sql" in script
    assert "Applying 0010_beli_espn_team_claims.sql" in script
    assert "Applying 0011_beli_espn_seed_team_claims.sql" in script
    assert "Applying 0001_beli_accounts.sql" in script
    assert "espn_accounts" in script
    assert "espn_snapshots" in script
    assert "espn_lineup_runs" in script
    assert "lineup_automation_enabled" in script


def test_all_families_include_espn():
    script = migration_runner.render(["dice", "commons", "beli"])
    assert "Applying 0006_beli_espn_accounts.sql" in script
    assert "Applying 0007_beli_espn_snapshots.sql" in script
    assert "Applying 0008_beli_espn_lineup.sql" in script
    assert "Applying 0009_beli_espn_public_predictions.sql" in script
    assert "Applying 0010_beli_espn_team_claims.sql" in script


def test_public_predictions_append_only_privileges_and_contract():
    directory = migration_runner.ROOT / "migrations"
    migration = (directory / "0009_beli_espn_public_predictions.sql").read_text()
    assert "unique (matchup_id, generated_at)" in migration
    assert "received_at timestamptz not null default now()" in migration
    assert "enable row level security" in migration
    assert "from public, anon, authenticated" in migration
    assert "grant select, insert on public.espn_public_predictions to service_role" in migration
    assert "revoke update, delete, truncate" in migration
    assert (directory / "BELI_SCHEMA_CONTRACT_VERSION").read_text().strip() == "12"
    contract = (directory / "beli_schema_contract.sql").read_text()
    for column in ("id", "matchup_id", "generated_at", "received_at", "payload"):
        assert f"espn_public_predictions.{column}" in contract


def test_team_claims_schema_privileges_atomic_move_and_contract():
    directory = migration_runner.ROOT / "migrations"
    migration = (directory / "0010_beli_espn_team_claims.sql").read_text()
    for definition in (
        "id uuid primary key default gen_random_uuid()",
        "season int not null", "team_id int not null",
        "user_id uuid not null references auth.users(id) on delete cascade",
        "created_at timestamptz not null default now()",
        "unique (season, team_id)", "unique (season, user_id)",
        "alter table public.espn_team_claims enable row level security",
        "revoke all on public.espn_team_claims from public, anon, authenticated, service_role",
        "grant select, insert, delete on public.espn_team_claims to service_role",
        "security invoker", "pg_advisory_xact_lock",
        "revoke all on function public.espn_claim_team(int, int, uuid) from public, anon, authenticated",
        "grant execute on function public.espn_claim_team(int, int, uuid) to service_role",
    ):
        assert definition in migration
    assert "grant update" not in migration
    assert "exception when" not in migration  # Conflicts must roll back the entire move.
    contract = (directory / "beli_schema_contract.sql").read_text()
    for column in ("id", "season", "team_id", "user_id", "created_at"):
        assert f"espn_team_claims.{column}" in contract
    assert "to_regprocedure('public.espn_claim_team(integer,integer,uuid)')" in contract


def test_seeded_claims_are_guarded_and_never_override_links():
    migration = (migration_runner.ROOT / "migrations" / "0011_beli_espn_seed_team_claims.sql").read_text()
    assert "where exists (select 1 from auth.users where id = seed.user_id)" in migration
    assert migration.rstrip().endswith("on conflict do nothing;")
    assert migration.count("::uuid)") == 10


def test_fantasy_settings_service_only_schema_and_release_contract():
    directory = migration_runner.ROOT / "migrations"
    migration = (directory / "0012_beli_fantasy_leagues.sql").read_text()
    for clause in (
        "season int primary key check (season between 2000 and 2100)",
        "espn_league_id text not null check (espn_league_id ~ '^[0-9]{1,12}$')",
        "alter table public.fantasy_leagues enable row level security",
        "revoke all on public.fantasy_leagues from public, anon, authenticated, service_role",
        "grant select, insert, update on public.fantasy_leagues to service_role",
    ):
        assert clause in migration
    assert "create policy" not in migration
    assert "Applying 0012_beli_fantasy_leagues.sql" in migration_runner.render(["beli"])
    contract = (directory / "beli_schema_contract.sql").read_text()
    for column in ("season", "espn_league_id", "updated_at", "updated_by"):
        assert f"fantasy_leagues.{column}" in contract
