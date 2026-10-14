"""The migration runner picks up the ESPN tables in the app ("beli") family."""

import migration_runner


def test_espn_migrations_render_in_beli_family():
    script = migration_runner.render(["beli"])
    assert "Applying 0006_beli_espn_accounts.sql" in script
    assert "Applying 0007_beli_espn_snapshots.sql" in script
    assert "Applying 0008_beli_espn_lineup.sql" in script
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
