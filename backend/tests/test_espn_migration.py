"""The migration runner picks up the ESPN tables in the app ("beli") family."""

import migration_runner


def test_espn_migrations_render_in_beli_family():
    script = migration_runner.render(["beli"])
    assert "Applying 0006_beli_espn_accounts.sql" in script
    assert "Applying 0007_beli_espn_snapshots.sql" in script
    assert "Applying 0008_beli_espn_lineup.sql" in script
    assert "Applying 0009_beli_espn_public_predictions.sql" in script
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


def test_public_predictions_append_only_privileges_and_contract():
    directory = migration_runner.ROOT / "migrations"
    migration = (directory / "0009_beli_espn_public_predictions.sql").read_text()
    assert "unique (matchup_id, generated_at)" in migration
    assert "received_at timestamptz not null default now()" in migration
    assert "enable row level security" in migration
    assert "from public, anon, authenticated" in migration
    assert "grant select, insert on public.espn_public_predictions to service_role" in migration
    assert "revoke update, delete, truncate" in migration
    assert (directory / "BELI_SCHEMA_CONTRACT_VERSION").read_text().strip() == "9"
    contract = (directory / "beli_schema_contract.sql").read_text()
    for column in ("id", "matchup_id", "generated_at", "received_at", "payload"):
        assert f"espn_public_predictions.{column}" in contract
