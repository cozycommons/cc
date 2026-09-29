"""The migration runner picks up the beli family without changing dice/commons."""

import migration_runner


def test_beli_family_rendering():
    script = migration_runner.render(["beli"])
    assert "Applying 0001_beli_accounts.sql" in script
    assert "Applying 0005_beli_ig_logger_platform.sql" in script
    assert "beli_schema_migrations" in script
    assert "Applying 0025_dice_schema.sql" not in script
    assert "Existing beli schema has no migration history" in script


def test_all_families_include_beli():
    script = migration_runner.render(["dice", "commons", "beli"])
    assert "Applying 0001_beli_accounts.sql" in script
    assert "Applying 0079_dice_staging_schema_reconciliation.sql" in script
