"""The migration runner picks up the Partiful table in the app ("beli") family."""

import migration_runner


def test_partiful_migration_renders_in_beli_family():
    script = migration_runner.render(["beli"])
    assert "Applying 0003_beli_partiful_accounts.sql" in script
    assert "Applying 0001_beli_accounts.sql" in script
    assert "partiful_accounts" in script


def test_all_families_include_partiful():
    script = migration_runner.render(["dice", "commons", "beli"])
    assert "Applying 0003_beli_partiful_accounts.sql" in script
