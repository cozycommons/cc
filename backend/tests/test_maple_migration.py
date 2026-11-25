"""The migration runner picks up the Maple telemetry tables in the
app ("beli") family, and the schema contract attests them."""

import migration_runner


def test_maple_migration_renders_in_beli_family():
    script = migration_runner.render(["beli"])
    assert "Applying 0094_beli_maple_telemetry.sql" in script
    assert "maple_accounts" in script
    assert "maple_exp_runs" in script


def test_maple_migration_schema_privileges_and_contract():
    directory = migration_runner.ROOT / "migrations"
    migration = (directory / "0094_beli_maple_telemetry.sql").read_text()
    for definition in (
        "create table if not exists public.maple_accounts",
        "token_hash text not null unique",
        "create table if not exists public.maple_exp_runs",
        "user_id uuid not null references public.maple_accounts(id) on delete cascade",
        "unique (user_id, run_id)",
        "alter table public.maple_accounts enable row level security",
        "alter table public.maple_exp_runs enable row level security",
        "revoke all on public.maple_accounts from public, anon, authenticated",
        "revoke all on public.maple_exp_runs from public, anon, authenticated",
        "grant select, insert, update, delete on public.maple_accounts to service_role",
        "grant select, insert, update, delete on public.maple_exp_runs to service_role",
    ):
        assert definition in migration
    assert (directory / "BELI_SCHEMA_CONTRACT_VERSION").read_text().strip() == "94"
    contract = (directory / "beli_schema_contract.sql").read_text()
    assert "'maple_accounts'" in contract
    assert "'maple_exp_runs'" in contract
    for column in (
        "id", "user_id", "run_id", "producer", "log_date", "map", "map_read",
        "level", "class", "party", "exp", "seconds", "mesos", "mesos_seconds",
        "potion_cost", "potion_seconds", "estimated", "source_install",
        "source_updated", "received_at",
    ):
        assert f"maple_exp_runs.{column}" in contract
    for column in ("id", "label", "token_hash", "token_prefix", "owner_user_id", "created_at"):
        assert f"maple_accounts.{column}" in contract
