"""The migration runner picks up the Resy table in the app ("beli") family."""

import migration_runner


def test_resy_migration_renders_in_beli_family():
    script = migration_runner.render(["beli"])
    assert "Applying 0004_beli_resy_accounts.sql" in script
    assert "Applying 0003_beli_partiful_accounts.sql" in script
    assert "resy_accounts" in script


def test_all_families_include_resy():
    script = migration_runner.render(["dice", "commons", "beli"])
    assert "Applying 0004_beli_resy_accounts.sql" in script
